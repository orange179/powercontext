"""Propagate Source availability through a per-scope evidence dependency graph.

Each scope owns one directed acyclic graph whose nodes are Sources, Memory entries, and Topic
Memory artifacts. A Source is the only node type a caller can turn off directly; every derived
node declares the parents that support it plus an ``all``/``any`` policy, and its availability is
recomputed from those parents whenever a Source changes.

Deactivating a node only removes its *eligibility*: the body is preserved, so a citation taken
before the withdrawal still resolves to the exact version that was there. Memory entries are
switched between the native ``active``/``inactive`` states, and Topic artifacts are hidden from
Topic search, which is what both native listings and prepared Context read.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory import MemoryCitation
from powercontext.builtin.sources import validate_scope_id
from powercontext.errors import ArtifactNotFoundError
from powercontext.sources import SourceRef

if TYPE_CHECKING:
    from powercontext.builtin.persistence.database import AsyncDatabase
    from powercontext.builtin.runtime.application import BuiltinRuntime


class SourceLifecycleError(ValueError):
    """Raised when a registration, event, or resolution breaks the lifecycle contract."""


class SourceLifecycleEvent(BaseModel):
    """One availability transition of a registered Source.

    ``revision`` addresses the Source's lifecycle version and must match the registered one, so
    an event can never be applied to a Source it was not written for. ``sequence`` orders events
    per Source: replaying the same event is a no-op, while a lower sequence or the same sequence
    with different content is rejected.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str = Field(strict=True, min_length=1)
    reason: str = Field(strict=True, min_length=1)
    revision: int = Field(strict=True, ge=1)
    sequence: int = Field(strict=True, ge=1)
    available: bool = Field(strict=True)

    @field_validator("node_id", "reason")
    @classmethod
    def _reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")  # noqa: TRY003
        return value


_SOURCE = "source"
_MEMORY = "memory"
_TOPIC = "topic"
_GENERATION = "generation"
_AUDIT = "audit"
_POLICIES = frozenset({"all", "any"})
_DEFAULT_REASON = "source-lifecycle"


@dataclass(frozen=True)
class _Node:
    """One registered graph node, plus the Source bookkeeping derived nodes do not use."""

    node_id: str
    kind: str
    ref: dict[str, Any]
    parents: tuple[str, ...]
    policy: str
    source_revision: int
    sequence: int
    available: bool
    reason: str | None
    order: int

    @property
    def binding(self) -> tuple[Any, ...]:
        return (self.kind, json.dumps(self.ref, sort_keys=True), self.parents, self.policy, self.source_revision)


_State = tuple[_Node, ...]


def _find(state: _State, node_id: str) -> _Node | None:
    return next((node for node in state if node.node_id == node_id), None)


def _by_id(state: _State) -> dict[str, _Node]:
    return {node.node_id: node for node in state}


def _replace(state: _State, updated: _Node) -> _State:
    return tuple(updated if node.node_id == updated.node_id else node for node in state)


def _policy_holds(node: _Node, availability: dict[str, bool]) -> bool:
    flags = [availability[parent] for parent in node.parents]
    return all(flags) if node.policy == "all" else any(flags)


def _propagate(state: _State) -> _State:
    """Recompute every derived node from its parents, walking the graph in registration order."""

    availability: dict[str, bool] = {}
    updated: list[_Node] = []
    for node in state:
        available = node.available if node.kind == _SOURCE else _policy_holds(node, availability)
        availability[node.node_id] = available
        updated.append(node if available == node.available else replace(node, available=available))
    return tuple(updated)


def _encode(state: _State) -> str:
    return json.dumps(
        [
            {
                "node_id": node.node_id,
                "kind": node.kind,
                "ref": node.ref,
                "parents": list(node.parents),
                "policy": node.policy,
                "source_revision": node.source_revision,
                "sequence": node.sequence,
                "available": node.available,
                "reason": node.reason,
                "order": node.order,
            }
            for node in state
        ],
        separators=(",", ":"),
        sort_keys=True,
    )


def _decode(payload: str) -> _State:
    return tuple(
        _Node(
            node_id=record["node_id"],
            kind=record["kind"],
            ref=record["ref"],
            parents=tuple(record["parents"]),
            policy=record["policy"],
            source_revision=record["source_revision"],
            sequence=record["sequence"],
            available=record["available"],
            reason=record["reason"],
            order=record["order"],
        )
        for record in json.loads(payload)
    )


class SourceLifecycleStore:
    """Persist one lifecycle graph per scope so restarts observe the same states.

    The payload is a single JSON document keyed by scope. It is written before native Memory
    state is touched: a crash between the two leaves the graph authoritative, and replaying the
    same event finishes the interrupted propagation instead of starting over.
    """

    def __init__(self, database: AsyncDatabase | None = None) -> None:
        self._database = database
        self._memory: dict[str, _State] = {}
        self._ready = False

    async def load(self, scope_id: str) -> _State:
        if self._database is None:
            return self._memory.get(scope_id, ())
        async with self._database.transaction() as connection:
            await self._ensure_table(connection)
            result = await connection.execute(
                text("SELECT payload FROM source_lifecycle_state WHERE scope_id = :scope_id"),
                {"scope_id": scope_id},
            )
            row = result.first()
        return () if row is None else _decode(row[0])

    async def save(self, scope_id: str, state: _State) -> None:
        if self._database is None:
            self._memory[scope_id] = state
            return
        payload = _encode(state)
        async with self._database.transaction() as connection:
            await self._ensure_table(connection)
            updated = await connection.execute(
                text("UPDATE source_lifecycle_state SET payload = :payload WHERE scope_id = :scope_id"),
                {"payload": payload, "scope_id": scope_id},
            )
            if not updated.rowcount:
                await connection.execute(
                    text("INSERT INTO source_lifecycle_state (scope_id, payload) VALUES (:scope_id, :payload)"),
                    {"payload": payload, "scope_id": scope_id},
                )

    async def _ensure_table(self, connection: Any) -> None:
        if self._ready:
            return
        await connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS source_lifecycle_state ("
                "scope_id VARCHAR(191) NOT NULL PRIMARY KEY, "
                "payload TEXT NOT NULL"
                ")"
            )
        )
        self._ready = True


def _reference(node: _Node) -> SourceRef | MemoryCitation | ArtifactRef:
    if node.kind == _SOURCE:
        return SourceRef.model_validate(node.ref)
    if node.kind == _MEMORY:
        return MemoryCitation.model_validate(node.ref)
    return ArtifactRef.model_validate(node.ref)


class ScopedSourceLifecycleApplication:
    """Register the evidence graph of one scope and drive Source availability through it."""

    def __init__(self, runtime: BuiltinRuntime, scope_id: str, store: SourceLifecycleStore) -> None:
        self._runtime = runtime
        self.scope_id = scope_id
        self._store = store

    async def register_source(self, node_id: str, source_ref: SourceRef, /, *, revision: int) -> None:
        await self._register(
            node_id,
            _SOURCE,
            source_ref,
            revision=_require_revision(revision),
            parents=(),
            policy="all",
        )

    async def register_memory(
        self,
        node_id: str,
        citation: MemoryCitation,
        /,
        *,
        parents: Sequence[str],
        policy: str,
    ) -> None:
        await self._register(node_id, _MEMORY, citation, revision=0, parents=parents, policy=policy)

    async def register_topic(
        self,
        node_id: str,
        reference: ArtifactRef,
        /,
        *,
        parents: Sequence[str],
        policy: str,
    ) -> None:
        await self._register(node_id, _TOPIC, reference, revision=0, parents=parents, policy=policy)

    async def apply(self, event: SourceLifecycleEvent, /) -> list[str]:
        async with self._runtime._context(self.scope_id) as context, self._runtime._locked(self.scope_id):
            state = await self._store.load(self.scope_id)
            node = _find(state, event.node_id)
            if node is None or node.kind != _SOURCE:
                raise SourceLifecycleError(f"node {event.node_id!r} is not a registered source")  # noqa: TRY003
            if node.source_revision != event.revision:
                raise SourceLifecycleError(  # noqa: TRY003
                    f"source {event.node_id!r} has lifecycle revision {node.source_revision}, not {event.revision}"
                )
            if event.sequence < node.sequence:
                raise SourceLifecycleError(f"source {event.node_id!r} already consumed sequence {node.sequence}")  # noqa: TRY003
            if event.sequence == node.sequence:
                if (event.available, event.reason) != (node.available, node.reason):
                    raise SourceLifecycleError(  # noqa: TRY003
                        f"source {event.node_id!r} already recorded a different event at sequence {event.sequence}"
                    )
                # Idempotent replay: the graph is already correct, but native Memory state may
                # still be behind if a previous attempt failed part way through propagation.
            else:
                state = _propagate(
                    _replace(
                        state,
                        replace(
                            node,
                            sequence=event.sequence,
                            available=event.available,
                            reason=event.reason,
                        ),
                    )
                )
                await self._store.save(self.scope_id, state)
            await self._synchronize(context, state)
            return sorted(item.node_id for item in state if item.available)

    async def resolve(
        self,
        node_id: str,
        /,
        *,
        purpose: Literal["generation", "audit"],
    ) -> SourceRef | MemoryCitation | ArtifactRef:
        if purpose not in (_GENERATION, _AUDIT):
            raise SourceLifecycleError(f"unknown resolution purpose {purpose!r}")  # noqa: TRY003
        node = _find(await self._store.load(self.scope_id), node_id)
        if node is None:
            raise SourceLifecycleError(f"node {node_id!r} is not registered")  # noqa: TRY003
        if purpose == _GENERATION and not node.available:
            raise SourceLifecycleError(f"node {node_id!r} is not available for generation")  # noqa: TRY003
        return _reference(node)

    async def withdrawn_topics(self) -> frozenset[str]:
        """Artifact ids of this scope's Topic nodes that no longer have enough support."""

        return frozenset(
            ArtifactRef.model_validate(node.ref).artifact_id
            for node in await self._store.load(self.scope_id)
            if node.kind == _TOPIC and not node.available
        )

    async def _register(
        self,
        node_id: str,
        kind: str,
        reference: SourceRef | MemoryCitation | ArtifactRef,
        *,
        revision: int,
        parents: Sequence[str],
        policy: str,
    ) -> None:
        validated_id = _require_node_id(node_id)
        # Sources are the roots of the graph; every derived node must name its support.
        validated_parents = () if kind == _SOURCE else _require_parents(validated_id, parents)
        validated_policy = _require_policy(policy)
        await self._assert_readable(kind, reference)
        candidate = _Node(
            node_id=validated_id,
            kind=kind,
            ref=reference.model_dump(mode="json"),
            parents=validated_parents,
            policy=validated_policy,
            source_revision=revision,
            sequence=0,
            available=True,
            reason=None,
            order=0,
        )
        async with self._runtime._context(self.scope_id) as context, self._runtime._locked(self.scope_id):
            state = await self._store.load(self.scope_id)
            existing = _find(state, validated_id)
            if existing is not None:
                if existing.binding != candidate.binding:
                    raise SourceLifecycleError(  # noqa: TRY003
                        f"node {validated_id!r} is already registered with a different binding"
                    )
                return
            for parent in validated_parents:
                if _find(state, parent) is None:
                    raise SourceLifecycleError(f"parent {parent!r} of {validated_id!r} must be registered first")  # noqa: TRY003
            node = replace(
                candidate,
                order=len(state),
                # Registration never defaults to available and waits: a derived node takes its
                # state from the parents it already has.
                available=kind == _SOURCE or _policy_holds(candidate, _availability(state)),
            )
            state = (*state, node)
            await self._store.save(self.scope_id, state)
            await self._synchronize(context, state)

    async def _assert_readable(
        self,
        kind: str,
        reference: SourceRef | MemoryCitation | ArtifactRef,
    ) -> None:
        records = self._runtime.records.for_scope(self.scope_id)
        try:
            if kind == _SOURCE:
                source = cast(SourceRef, reference)
                await records.get_source(source.source_type, source.source_id)
            elif kind == _MEMORY:
                citation = cast(MemoryCitation, reference)
                await records.get_artifact_revision(
                    "memory",
                    citation.memory_ref.artifact_id,
                    citation.memory_ref.revision,
                )
            else:
                artifact = cast(ArtifactRef, reference)
                await records.get_artifact_revision(
                    "topic-memory",
                    artifact.artifact_id,
                    artifact.revision,
                )
        except ArtifactNotFoundError as error:
            raise SourceLifecycleError(f"{kind} reference is missing or unreadable: {error}") from None  # noqa: TRY003

    async def _synchronize(self, context: Any, state: _State) -> None:
        """Make native Memory entry states agree with the graph.

        Only entries whose state disagrees are touched, and they are switched in one transition
        per direction, so a replayed event writes no new Memory revision.
        """

        targets = [node for node in state if node.kind == _MEMORY]
        if not targets:
            return
        service = context.artifacts.memory
        current = await service.head(context.artifacts.memory_artifact_id)
        manifest = {item.entry_id: item for item in current.content.manifest.entries}
        versions = {entry.entry_id: entry for entry in await service.entries(current)}
        wanted_inactive: list[tuple[Any, str]] = []
        wanted_active: list[tuple[Any, str]] = []
        for node in targets:
            citation = MemoryCitation.model_validate(node.ref)
            item = manifest.get(citation.entry_id)
            entry = versions.get(citation.entry_id)
            if item is None or entry is None:
                raise SourceLifecycleError(  # noqa: TRY003
                    f"memory entry {citation.entry_id!r} of node {node.node_id!r} is no longer in Memory"
                )
            target_state = "active" if node.available else "inactive"
            if item.state == target_state:
                continue
            bucket = wanted_active if node.available else wanted_inactive
            bucket.append((entry, node.reason or _DEFAULT_REASON))
        if wanted_inactive:
            current = await service.forget(
                current,
                entries=tuple(entry for entry, _ in wanted_inactive),
                reason=_reason_of(wanted_inactive),
            )
        if wanted_active:
            await service.reactivate(
                current,
                entries=tuple(entry for entry, _ in wanted_active),
                reason=_reason_of(wanted_active),
            )


def _availability(state: _State) -> dict[str, bool]:
    return {node.node_id: node.available for node in state}


def _reason_of(pairs: Iterable[tuple[Any, str]]) -> str:
    """One deterministic reason for a whole transition, so replays stay byte-identical."""

    reasons = {reason for _, reason in pairs}
    return reasons.pop() if len(reasons) == 1 else _DEFAULT_REASON


def _require_node_id(node_id: object) -> str:
    if not isinstance(node_id, str) or not node_id.strip():
        raise SourceLifecycleError("node_id must be a non-empty string")  # noqa: TRY003
    return node_id


def _require_revision(revision: object) -> int:
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise SourceLifecycleError("revision must be a positive integer")  # noqa: TRY003
    return revision


def _require_parents(node_id: str, parents: Sequence[str]) -> tuple[str, ...]:
    resolved = tuple(parents)
    if not resolved:
        raise SourceLifecycleError(f"node {node_id!r} needs at least one parent")  # noqa: TRY003
    for parent in resolved:
        _require_node_id(parent)
    if node_id in resolved:
        raise SourceLifecycleError(f"node {node_id!r} cannot depend on itself")  # noqa: TRY003
    if len(set(resolved)) != len(resolved):
        raise SourceLifecycleError(f"node {node_id!r} repeats a parent")  # noqa: TRY003
    return resolved


def _require_policy(policy: str) -> str:
    if policy not in _POLICIES:
        raise SourceLifecycleError(f"unknown dependency policy {policy!r}")  # noqa: TRY003
    return policy


class LifecycleApplication:
    """Select the scoped lifecycle service, and hide unsupported Topic nodes from Topic search."""

    def __init__(self, runtime: BuiltinRuntime, store: SourceLifecycleStore) -> None:
        self._runtime = runtime
        self._store = store

    def for_scope(self, scope_id: str, /) -> ScopedSourceLifecycleApplication:
        return ScopedSourceLifecycleApplication(self._runtime, validate_scope_id(scope_id), self._store)

    async def filter_topic_hits(
        self,
        scope_id: str,
        result: Any,
        /,
    ) -> Any:
        """Drop hits of Topic nodes that lost their support from one search result."""

        hidden = await self.for_scope(scope_id).withdrawn_topics()
        if not hidden:
            return result
        kept = tuple(hit for hit in result.hits if hit.artifact_ref.artifact_id not in hidden)
        return result if len(kept) == len(result.hits) else result.model_copy(update={"hits": kept})
