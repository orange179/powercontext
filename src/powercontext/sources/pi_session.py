# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Pi session history Source: parse Pi JSONL sessions into per-event captured Sources."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources import (
    AdapterSourceDefinition,
    SourceMaterialization,
    TextEvidence,
)
from powercontext.sources.models import Source

PI_EVENT_SOURCE_NAME = "pi-event"
PI_SESSION_CONNECTOR_NAME = "pi-session-history"

_CONTROL_EVENT_TYPES = frozenset({
    "model_change",
    "thinking_level_change",
    "usage",
    "context_edit",
})


class PiSessionInput(BaseModel):
    """Full offline Pi session JSONL document."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    content: bytes
    leaf_id: str | None = None


class PiEventInput(BaseModel):
    """One parsed Pi event ready to become a captured Source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, Any]


class PiEventSource(Source):
    """Captured Source representing one Pi session event."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, Any]


def _parse_jsonl(content: bytes) -> list[dict[str, Any]]:
    """Decode UTF-8 (with optional BOM) and parse JSONL lines."""
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Session content is not valid UTF-8: {exc}") from exc

    if text.startswith("\ufeff"):
        text = text[1:]

    records: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            records.append(json.loads(stripped))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON on line {line_no}: {exc}") from exc
    return records


def _format_content_block(block: dict[str, Any], tool_call_names: dict[str, str]) -> str | None:
    """Format a single content block into visible text. Returns None if not visible."""
    block_type = block.get("type")

    if block_type == "text":
        return block.get("text", "")

    if block_type == "toolCall":
        name = block.get("toolName", "")
        tool_call_id = block.get("toolCallId", "")
        input_data = block.get("input", {})
        args_json = json.dumps(input_data, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        return f"[tool_call {name} {tool_call_id}] {args_json}"

    if block_type == "toolResult":
        tool_name = block.get("toolName", "")
        tool_call_id = block.get("toolCallId", "")
        if not tool_name:
            tool_name = tool_call_names.get(tool_call_id, "unknown")
        content = block.get("content", "")
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(item.get("text", ""))
                elif isinstance(item, str):
                    parts.append(item)
            text = "\n".join(parts)
        else:
            text = str(content) if content else ""
        return f"[tool_result {tool_name} {tool_call_id}] {text}"

    if block_type == "bashExecution":
        command = block.get("command", "")
        output = block.get("output", "")
        return f"$ {command}\n{output}"

    # thinking, image, and other non-visible blocks
    return None


def _format_message_content(message: dict[str, Any], tool_call_names: dict[str, str]) -> str | None:
    """Format message content into visible text. Returns None if no visible content."""
    content = message.get("content")

    if content is None:
        return None

    if isinstance(content, str):
        return content if content else None

    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            formatted = _format_content_block(block, tool_call_names)
            if formatted is not None:
                parts.append(formatted)
        return "\n".join(parts) if parts else None

    return None


def _format_event_content(record: dict[str, Any], tool_call_names: dict[str, str]) -> tuple[str, str] | None:
    """Format an event record into (role, body). Returns None if not visible."""
    event_type = record.get("type", "")

    if event_type == "message":
        message = record.get("message", {})
        role = message.get("role", "unknown")
        body = _format_message_content(message, tool_call_names)
        if body is None:
            return None
        return (role, body)

    if event_type == "compaction":
        summary = record.get("summary", "")
        return ("compaction", summary) if summary else None

    if event_type == "branch_summary":
        summary = record.get("summary", "")
        return ("branch_summary", summary) if summary else None

    if event_type == "custom_message":
        message = record.get("message", {})
        body = _format_message_content(message, tool_call_names)
        if body is None:
            return None
        return ("custom", body)

    # Control events and unknown types
    return None


def parse_pi_session(value: PiSessionInput) -> tuple[PiEventInput, ...]:
    """Parse a Pi session JSONL document and return events on the selected branch."""
    records = _parse_jsonl(value.content)

    if not records:
        raise ValueError("Session file is empty")

    # Validate session header
    header = records[0]
    if header.get("type") != "session":
        raise ValueError("First record must be a session header with type='session'")
    if header.get("version") != 3:
        raise ValueError(f"Session version must be 3, got {header.get('version')!r}")
    session_id = header.get("id")
    if not session_id or not isinstance(session_id, str):
        raise ValueError("Session header must have a non-empty string 'id'")

    # Build node map from remaining records
    nodes: dict[str, dict[str, Any]] = {}
    children: dict[str, list[str]] = {}
    node_order: list[str] = []

    for record in records[1:]:
        node_id = record.get("id")
        if not node_id or not isinstance(node_id, str):
            raise ValueError("Each record must have a non-empty string 'id'")
        if node_id in nodes:
            raise ValueError(f"Duplicate node id: {node_id!r}")

        parent_id = record.get("parentId")
        if parent_id is not None:
            if not isinstance(parent_id, str):
                raise ValueError(f"parentId must be a string or null, got {type(parent_id).__name__}")
            if parent_id and parent_id not in nodes:
                raise ValueError(f"Parent id {parent_id!r} not found for node {node_id!r}")

        nodes[node_id] = record
        node_order.append(node_id)

        if parent_id:
            children.setdefault(parent_id, []).append(node_id)

    # Check for cycles by walking parent chains
    for node_id in nodes:
        visited: set[str] = set()
        current: str | None = node_id
        while current is not None:
            if current in visited:
                raise ValueError(f"Cycle detected involving node {current!r}")
            visited.add(current)
            current = nodes[current].get("parentId")

    # Determine leaf node
    if value.leaf_id is not None:
        if value.leaf_id not in nodes:
            raise ValueError(f"Leaf id {value.leaf_id!r} not found in session")
        leaf_id = value.leaf_id
    else:
        if not node_order:
            raise ValueError("Session has no events")
        leaf_id = node_order[-1]

    # Build ancestor chain from root to leaf
    ancestor_chain: list[str] = []
    current: str | None = leaf_id
    while current is not None:
        ancestor_chain.append(current)
        current = nodes[current].get("parentId")
    ancestor_chain.reverse()

    # Build tool call name lookup (for toolResult formatting)
    tool_call_names: dict[str, str] = {}
    for node_id in ancestor_chain:
        record = nodes[node_id]
        if record.get("type") == "message":
            message = record.get("message", {})
            content = message.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "toolCall":
                        tc_id = block.get("toolCallId", "")
                        tc_name = block.get("toolName", "")
                        if tc_id and tc_name:
                            tool_call_names[tc_id] = tc_name

    # Process events on the selected branch
    result: list[PiEventInput] = []
    for node_id in ancestor_chain:
        record = nodes[node_id]
        event_type = record.get("type", "")

        # Skip control events
        if event_type in _CONTROL_EVENT_TYPES:
            continue

        formatted = _format_event_content(record, tool_call_names)
        if formatted is None:
            continue

        role, body = formatted
        parent_id = record.get("parentId")

        result.append(
            PiEventInput(
                session_id=session_id,
                event_id=node_id,
                parent_id=parent_id,
                event_type=event_type,
                role=role,
                content=f"{role}: {body}",
                record=record,
            )
        )

    return tuple(result)


def pi_event_source_id(session_id: str, event_id: str) -> str:
    """Compute the stable percent-encoded identity for one Pi event."""
    encoded = f"pi:{quote(session_id, safe='')}/{quote(event_id, safe='')}"
    if len(encoded) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(
            f"source_id length {len(encoded)} exceeds limit {MAX_SOURCE_ID_LENGTH}"
        )
    return encoded


class PiEventSourceAdapter:
    """Resolve and read Pi event Sources."""

    input_class = PiEventInput
    name = PI_EVENT_SOURCE_NAME
    source_class = PiEventSource

    async def resolve(self, value: PiEventInput, /) -> PiEventSource:
        source_id = pi_event_source_id(value.session_id, value.event_id)
        return PiEventSource(
            name=source_id,
            source_id=source_id,
            materialization=SourceMaterialization.CAPTURED,
            session_id=value.session_id,
            event_id=value.event_id,
            parent_id=value.parent_id,
            event_type=value.event_type,
            role=value.role,
            content=value.content,
            record=value.record,
        )

    async def read(self, source: PiEventSource, /) -> PiEventInput:
        return PiEventInput(
            session_id=source.session_id,
            event_id=source.event_id,
            parent_id=source.parent_id,
            event_type=source.event_type,
            role=source.role,
            content=source.content,
            record=source.record,
        )


class PiEventTextEvidenceProjection:
    """Project a Pi event Source as TextEvidence for Memory retrieval."""

    name = "powercontext.text-evidence"
    version = "1"
    source_class = PiEventSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PiEventSource, /) -> TextEvidence:
        metadata: dict[str, JsonValue] = {
            "session_id": source.session_id,
            "event_id": source.event_id,
            "parent_id": source.parent_id,
            "event_type": source.event_type,
            "role": source.role,
        }
        return TextEvidence(
            source_type=PI_EVENT_SOURCE_NAME,
            source_id=source.source_id,
            content=source.content,
            metadata=metadata,
        )


PI_EVENT_SOURCE_ADAPTER = PiEventSourceAdapter()
PI_EVENT_SOURCE_DEFINITION: AdapterSourceDefinition[
    PiEventInput, PiEventSource, PiEventInput
] = AdapterSourceDefinition(
    PI_EVENT_SOURCE_ADAPTER,
    projections=(PiEventTextEvidenceProjection(),),
)


# --- Connector ---


class PiSessionCheckpoint(BaseModel):
    """Checkpoint tracking imported Pi events."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["1"] = "1"
    session_id: str = ""
    event_digests: dict[str, str] = Field(default_factory=dict)


def _load_checkpoint(checkpoint: JsonValue | None) -> PiSessionCheckpoint:
    """Load checkpoint from JSON value."""
    if checkpoint is None:
        return PiSessionCheckpoint()
    try:
        return PiSessionCheckpoint.model_validate(checkpoint)
    except Exception:
        return PiSessionCheckpoint()


def _compute_digest(record: dict[str, Any]) -> str:
    """Compute SHA-256 digest of a record for change detection."""
    serialized = json.dumps(record, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class PiSessionConnector:
    """Connector for incremental Pi session history collection."""

    name = PI_SESSION_CONNECTOR_NAME
    version = "1"
    source_definitions = frozenset({PI_EVENT_SOURCE_NAME})

    def __init__(self, path: str | Path, leaf_id: str | None = None) -> None:
        self._path = Path(path)
        self._leaf_id = leaf_id

    async def run(self, session: Any, /) -> Any:
        """Run the connector, submitting only new/changed events."""
        from powercontext.sources.connectors import ConnectorRunCompletion, ConnectorRunStatus

        # Read and parse the session file
        content = self._path.read_bytes()
        pi_input = PiSessionInput(content=content, leaf_id=self._leaf_id)
        events = parse_pi_session(pi_input)

        if not events:
            # No visible events; return current checkpoint unchanged
            previous = _load_checkpoint(session.checkpoint)
            return ConnectorRunCompletion(
                status=ConnectorRunStatus.COMPLETE,
                checkpoint=previous.model_dump(mode="json"),
            )

        session_id = events[0].session_id
        previous = _load_checkpoint(session.checkpoint)

        # Check session ID consistency
        if previous.session_id and previous.session_id != session_id:
            raise ValueError(
                f"Session ID mismatch: checkpoint has {previous.session_id!r}, "
                f"file has {session_id!r}"
            )

        # Process events
        new_digests = dict(previous.event_digests)

        for event in events:
            digest = _compute_digest(event.record)
            existing_digest = previous.event_digests.get(event.event_id)

            if existing_digest is not None:
                if existing_digest != digest:
                    raise ValueError(
                        f"Imported event {event.event_id!r} has been rewritten"
                    )
                # Already imported with same content; skip
                continue

            # New event; submit it
            await session.submit(
                event.event_id,
                PI_EVENT_SOURCE_NAME,
                event,
            )
            new_digests[event.event_id] = digest

        checkpoint = PiSessionCheckpoint(
            session_id=session_id,
            event_digests=new_digests,
        )

        return ConnectorRunCompletion(
            status=ConnectorRunStatus.COMPLETE,
            checkpoint=checkpoint.model_dump(mode="json"),
        )


__all__ = [
    "PI_EVENT_SOURCE_ADAPTER",
    "PI_EVENT_SOURCE_DEFINITION",
    "PI_EVENT_SOURCE_NAME",
    "PI_SESSION_CONNECTOR_NAME",
    "PiEventInput",
    "PiEventSource",
    "PiEventSourceAdapter",
    "PiEventTextEvidenceProjection",
    "PiSessionCheckpoint",
    "PiSessionConnector",
    "PiSessionInput",
    "parse_pi_session",
    "pi_event_source_id",
]
