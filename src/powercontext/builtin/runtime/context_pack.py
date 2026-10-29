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

"""Chunked Context Pack wire format and prefix-reuse deltas.

A pack carries one prepared context as an ordered tuple of UTF-8-safe chunks plus the
digest and wire size that let a receiver verify it. A delta says how many leading chunks
of a known base pack survive and carries the remaining target chunks, so consecutive
prepares can share the unchanged head instead of resending it.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable

PACK_SCHEMA = "powercontext.context-pack.v1"
DELTA_SCHEMA = "powercontext.context-pack-delta.v1"
DEFAULT_CHUNK_BYTES = 512

_PACK_FIELDS = frozenset({"schema", "items", "digest", "byte_count"})
_DELTA_FIELDS = frozenset({"schema", "base_digest", "target_digest", "prefix_items", "appended"})


class ContextPackError(ValueError):
    """A Context Pack or delta violates the wire protocol or its checksums."""


@dataclass(frozen=True, slots=True)
class ContextPack:
    """One complete, verifiable prepared context split into ordered chunks."""

    items: tuple[bytes, ...]
    digest: str
    byte_count: int

    @classmethod
    def build(cls, items: Iterable[bytes], /) -> ContextPack:
        """Wrap already chunked bytes without re-chunking them."""

        chunks = tuple(_as_bytes(item) for item in items)
        digest = _pack_digest(chunks)
        return cls(items=chunks, digest=digest, byte_count=_settle_byte_count(chunks, digest))

    @classmethod
    def from_content(cls, content: str | bytes, *, chunk_bytes: int = DEFAULT_CHUNK_BYTES) -> ContextPack:
        """Chunk a context deterministically so every chunk stays valid UTF-8 and bounded."""

        return cls.build(_chunk_content(content, chunk_bytes))

    @classmethod
    def from_bytes(cls, payload: bytes, /) -> ContextPack:
        """Decode and verify one serialized pack."""

        document = _decode_json(payload, "context pack")
        if set(document) != _PACK_FIELDS:
            raise ContextPackError("context pack must contain exactly schema, items, digest and byte_count")
        if document["schema"] != PACK_SCHEMA:
            raise ContextPackError(f"unsupported context pack schema: {document['schema']!r}")
        chunks = _decode_chunks(document["items"], "context pack items")
        digest = _pack_digest(chunks)
        if document["digest"] != digest:
            raise ContextPackError("context pack digest does not match its items")
        byte_count = document["byte_count"]
        if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count != len(payload):
            raise ContextPackError("context pack byte_count does not match the received bytes")
        return cls(items=chunks, digest=digest, byte_count=byte_count)

    def to_bytes(self) -> bytes:
        """Serialize the pack with its canonical, self-describing size."""

        return _serialize_pack(self.items, self.digest, self.byte_count)


@dataclass(frozen=True, slots=True)
class ContextPackDelta:
    """A retained base prefix together with the target suffix that completes it."""

    base_digest: str
    target_digest: str
    prefix_items: int
    appended: tuple[bytes, ...]

    def __post_init__(self) -> None:
        if isinstance(self.prefix_items, bool) or not isinstance(self.prefix_items, int) or self.prefix_items < 0:
            raise ContextPackError("delta prefix_items must be a non-negative integer")
        object.__setattr__(self, "appended", tuple(_as_bytes(item) for item in self.appended))

    @classmethod
    def between(cls, base: ContextPack, target: ContextPack, /) -> ContextPackDelta:
        """Reuse the longest shared leading chunks and carry the rest of the target."""

        prefix_items = 0
        for base_item, target_item in zip(base.items, target.items, strict=False):
            if base_item != target_item:
                break
            prefix_items += 1
        return cls(
            base_digest=base.digest,
            target_digest=target.digest,
            prefix_items=prefix_items,
            appended=target.items[prefix_items:],
        )

    @classmethod
    def from_bytes(cls, payload: bytes, /) -> ContextPackDelta:
        """Decode and verify one serialized delta."""

        document = _decode_json(payload, "context pack delta")
        if set(document) != _DELTA_FIELDS:
            raise ContextPackError(
                "context pack delta must contain exactly schema, base_digest, target_digest, prefix_items and appended"
            )
        if document["schema"] != DELTA_SCHEMA:
            raise ContextPackError(f"unsupported context pack delta schema: {document['schema']!r}")
        return cls(
            base_digest=_require_digest(document["base_digest"], "base_digest"),
            target_digest=_require_digest(document["target_digest"], "target_digest"),
            prefix_items=document["prefix_items"],
            appended=_decode_chunks(document["appended"], "context pack delta appended"),
        )

    @property
    def byte_count(self) -> int:
        """Wire size of this delta; it is derived, never stored as a field."""

        return len(self.to_bytes())

    def to_bytes(self) -> bytes:
        """Serialize the delta with canonical key order and no extra whitespace."""

        return _canonical_json(
            {
                "schema": DELTA_SCHEMA,
                "base_digest": self.base_digest,
                "target_digest": self.target_digest,
                "prefix_items": self.prefix_items,
                "appended": [_encode_chunk(item) for item in self.appended],
            }
        )


def apply_context_pack_delta(base: ContextPack, delta: ContextPackDelta, /) -> ContextPack:
    """Rebuild the delta's target pack from a base pack alone."""

    if delta.base_digest != base.digest:
        raise ContextPackError("delta base_digest does not match the supplied base pack")
    prefix_items = delta.prefix_items
    if isinstance(prefix_items, bool) or not isinstance(prefix_items, int) or prefix_items < 0:
        raise ContextPackError("delta prefix_items must be a non-negative integer")
    if prefix_items > len(base.items):
        raise ContextPackError("delta prefix_items exceeds the base pack item count")
    target = ContextPack.build((*base.items[:prefix_items], *delta.appended))
    if target.digest != delta.target_digest:
        raise ContextPackError("rebuilt pack digest does not match the delta target_digest")
    return target


def _chunk_content(content: str | bytes, chunk_bytes: int) -> tuple[bytes, ...]:
    if isinstance(chunk_bytes, bool) or not isinstance(chunk_bytes, int) or chunk_bytes < 1:
        raise ContextPackError("chunk_bytes must be a positive integer")
    if isinstance(content, str):
        data = content.encode("utf-8")
    else:
        data = _as_bytes(content)
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ContextPackError("context content is not valid UTF-8") from error
    if not data:
        return ()

    chunks: list[bytes] = []
    current = bytearray()
    for line in data.decode("utf-8").splitlines(keepends=True):
        for piece in _split_line(line.encode("utf-8"), chunk_bytes):
            if len(current) + len(piece) > chunk_bytes and current:
                chunks.append(bytes(current))
                current.clear()
            current += piece
            if len(current) == chunk_bytes:
                chunks.append(bytes(current))
                current.clear()
    if current:
        chunks.append(bytes(current))
    return tuple(chunks)


def _split_line(line: bytes, chunk_bytes: int) -> tuple[bytes, ...]:
    """Split an oversized line at UTF-8 character boundaries, keeping each piece bounded."""

    if len(line) <= chunk_bytes:
        return (line,)
    pieces: list[bytes] = []
    start = 0
    while len(line) - start > chunk_bytes:
        end = start + chunk_bytes
        # A UTF-8 continuation byte means the cut landed inside a character.
        while end > start and line[end] & 0xC0 == 0x80:
            end -= 1
        if end == start:
            raise ContextPackError(f"chunk_bytes={chunk_bytes} cannot hold a single character")
        pieces.append(line[start:end])
        start = end
    if start < len(line):
        pieces.append(line[start:])
    return tuple(pieces)


def _pack_digest(chunks: tuple[bytes, ...]) -> str:
    canonical = _canonical_json({"schema": PACK_SCHEMA, "items": [_encode_chunk(item) for item in chunks]})
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _serialize_pack(chunks: tuple[bytes, ...], digest: str, byte_count: int) -> bytes:
    return _canonical_json(
        {
            "schema": PACK_SCHEMA,
            "items": [_encode_chunk(item) for item in chunks],
            "digest": digest,
            "byte_count": byte_count,
        }
    )


def _settle_byte_count(chunks: tuple[bytes, ...], digest: str) -> int:
    """Find the byte_count that equals the length of its own serialization."""

    byte_count = 0
    for _ in range(8):
        serialized = _serialize_pack(chunks, digest, byte_count)
        if len(serialized) == byte_count:
            return byte_count
        byte_count = len(serialized)
    raise ContextPackError("context pack byte_count did not converge")


def _canonical_json(document: dict[str, Any]) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _decode_json(payload: bytes, label: str) -> dict[str, Any]:
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContextPackError(f"{label} is not valid UTF-8 JSON") from error
    if not isinstance(document, dict):
        raise ContextPackError(f"{label} must be a JSON object")
    return document


def _decode_chunks(value: Any, label: str) -> tuple[bytes, ...]:
    if not isinstance(value, list):
        raise ContextPackError(f"{label} must be a list of Base64 strings")
    chunks: list[bytes] = []
    for item in value:
        if not isinstance(item, str):
            raise ContextPackError(f"{label} must be a list of Base64 strings")
        try:
            chunks.append(base64.b64decode(item.encode("ascii"), validate=True))
        except (UnicodeEncodeError, binascii.Error) as error:
            raise ContextPackError(f"{label} contains an invalid Base64 chunk") from error
    return tuple(chunks)


def _encode_chunk(chunk: bytes) -> str:
    return base64.b64encode(chunk).decode("ascii")


def _require_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 71 or not value.startswith("sha256:"):
        raise ContextPackError(f"{label} must be a 'sha256:<hex>' digest")
    try:
        bytes.fromhex(value[7:])
    except ValueError as error:
        raise ContextPackError(f"{label} must be a 'sha256:<hex>' digest") from error
    return value


def _as_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray | memoryview):
        return bytes(value)
    raise ContextPackError("chunks must be bytes")


__all__ = [
    "DEFAULT_CHUNK_BYTES",
    "DELTA_SCHEMA",
    "PACK_SCHEMA",
    "ContextPack",
    "ContextPackDelta",
    "ContextPackError",
    "apply_context_pack_delta",
]
