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

"""Coalescing embedding wrapper that shares batched work and caches vectors."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from typing import TYPE_CHECKING

from powercontext.builtin.inference.models import EmbeddingResult, InferenceUsage

if TYPE_CHECKING:
    from powercontext.builtin.inference.protocols import EmbeddingModel


class CoalescingEmbeddingModel:
    """Share in-flight embedding work across concurrent callers and cache successes.

    Each distinct text has one future at a time — either freshly registered by this
    caller or discovered already running. One future can be awaited by many callers,
    and canceling one does not affect the others because all awaits go through
    ``asyncio.shield``.
    """

    def __init__(
        self,
        model: EmbeddingModel,
        *,
        max_batch_size: int = 64,
        coalesce_ms: float = 5.0,
        cache_size: int = 1024,
    ) -> None:
        if type(max_batch_size) is not int or max_batch_size < 1:
            raise ValueError("max_batch_size must be a positive integer")
        if cache_size < 0:
            raise ValueError("cache_size must be non-negative")
        self._model = model
        self._max_batch_size = max_batch_size
        self._coalesce_ms = max(coalesce_ms, 0.0)
        self._cache_size = cache_size
        self._cache: OrderedDict[str, tuple[tuple[float, ...], InferenceUsage]] = OrderedDict()
        # text -> (future that returns (dict[text]->vec, usage), batch_id)
        self._running: dict[str, tuple[asyncio.Future[tuple[dict[str, tuple[float, ...]], InferenceUsage]], int]] = {}
        self._lock = asyncio.Lock()
        self._batch_counter = 0

    @property
    def profile(self):  # noqa: ANN201
        return self._model.profile

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult(vectors=(), usage=InferenceUsage(requests=0))

        distinct = tuple(dict.fromkeys(texts))
        async_texts: dict[str, str] = {}  # text -> itself (preserve order)
        cached_vec: dict[str, tuple[float, ...]] = {}
        text_meta: dict[str, int] = {}  # text -> batch_id (0 = cache hit)
        text_future: dict[str, asyncio.Future] = {}  # type: ignore[type-arg]

        # --- Phase A: lock, check cache and in-flight, register missing ones ---
        async with self._lock:
            self._gc_locked()
            missing: list[str] = []
            for text in distinct:
                async_texts[text] = text
                if text in self._cache:
                    vec, _ = self._cache[text]
                    self._cache.move_to_end(text)
                    cached_vec[text] = vec
                    text_meta[text] = 0
                elif text in self._running:
                    fut, bid = self._running[text]
                    text_future[text] = fut
                    text_meta[text] = bid
                else:
                    missing.append(text)
            if missing:
                self._batch_counter += 1
                batch_id = self._batch_counter
                for i in range(0, len(missing), self._max_batch_size):
                    batch = missing[i : i + self._max_batch_size]
                    fut = asyncio.get_running_loop().create_future()
                    for text in batch:
                        self._running[text] = (fut, batch_id)
                        text_future[text] = fut
                        text_meta[text] = batch_id
                    asyncio.create_task(self._run_batch(tuple(batch), fut))

        # --- Phase B: yield so later callers can fold in, then re-check ---
        if self._coalesce_ms > 0:
            await asyncio.sleep(self._coalesce_ms / 1000.0)
            async with self._lock:
                self._gc_locked()
                for text in distinct:
                    if text_meta.get(text, 0) > 0:
                        # We are already waiting on a future for this text.
                        # Even if the batch finished and the vector is now in
                        # the cache, keep the original batch_id so Phase E can
                        # correctly attribute usage. The future is completed
                        # by now but awaiting it still yields the usage.
                        continue
                    if text in self._cache and text not in cached_vec:
                        vec, _ = self._cache[text]
                        self._cache.move_to_end(text)
                        cached_vec[text] = vec
                        text_meta[text] = 0
                        text_future.pop(text, None)
                    elif text in self._running and text not in cached_vec:
                        fut, bid = self._running[text]
                        text_future[text] = fut
                        text_meta[text] = bid

        # --- Phase C: await all distinct futures, gather per-text results ---
        text_result_vec: dict[str, tuple[float, ...]] = {}
        text_result_usage: dict[str, InferenceUsage] = {}
        text_errors: dict[str, BaseException] = {}

        # Await each unique future once; map all its texts to the result.
        awaited: dict[asyncio.Future, tuple[dict[str, tuple[float, ...]], InferenceUsage]] = {}  # type: ignore[type-arg]
        for text in distinct:
            if text in cached_vec:
                text_result_vec[text] = cached_vec[text]
                # Usage for pure cache hit is effectively 0 (we aggregate later).
                continue
            fut = text_future[text]
            if fut in awaited:
                continue
            try:
                mapping, usage = await asyncio.shield(fut)
                awaited[fut] = (mapping, usage)
            except asyncio.CancelledError:
                raise
            except BaseException as exc:  # noqa: BLE001
                text_errors[text] = exc
                continue

        # Fill per-text from awaited futures.
        for text in distinct:
            if text in cached_vec or text in text_errors:
                continue
            fut = text_future[text]
            mapping, usage = awaited[fut]
            text_result_vec[text] = mapping[text]
            text_result_usage[text] = usage

        # --- Phase D: assemble output in original input order ---
        vectors: list[tuple[float, ...]] = []
        for text in texts:
            if text in text_errors:
                raise text_errors[text]
            vectors.append(text_result_vec[text])

        # --- Phase E: aggregate usage, dedup by batch_id ---
        seen_batches: set[int] = set()
        requests = 0
        input_tokens = 0
        output_tokens = 0
        any_cache = False
        for text in distinct:
            bid = text_meta[text]
            if bid == 0:
                any_cache = True
                continue
            if bid in seen_batches:
                continue
            seen_batches.add(bid)
            usage = text_result_usage.get(text)
            if usage is None:
                continue
            requests += usage.requests or 0
            input_tokens += usage.input_tokens or 0
            output_tokens += usage.output_tokens or 0
        if any_cache and not seen_batches:
            requests = 0
        return EmbeddingResult(
            vectors=tuple(vectors),
            usage=InferenceUsage(
                requests=requests,
                input_tokens=input_tokens or 0,
                output_tokens=output_tokens or 0,
            ),
        )

    async def _run_batch(
        self,
        key: tuple[str, ...],
        future: asyncio.Future[tuple[dict[str, tuple[float, ...]], InferenceUsage]],
    ) -> None:
        try:
            result = await self._model.embed(key)
            if len(result.vectors) != len(key):
                raise ValueError(  # noqa: TRY003
                    f"provider returned {len(result.vectors)} vectors for {len(key)} texts"
                )
            vectors_by_text = dict(zip(key, result.vectors, strict=True))
            usage = InferenceUsage(
                requests=result.usage.requests or 0 if result.usage is not None else 0,
                input_tokens=result.usage.input_tokens or 0 if result.usage is not None else 0,
                output_tokens=result.usage.output_tokens or 0 if result.usage is not None else 0,
            )
            if self._cache_size > 0:
                for text, vec in vectors_by_text.items():
                    self._cache[text] = (vec, usage)
                    self._cache.move_to_end(text)
                while len(self._cache) > self._cache_size:
                    self._cache.popitem(last=False)
            future.set_result((vectors_by_text, usage))
        except BaseException as exc:  # noqa: BLE001
            if not future.done():
                future.set_exception(exc)
        finally:
            async with self._lock:
                for text in key:
                    entry = self._running.get(text)
                    if entry is not None and entry[0] is future:
                        self._running.pop(text, None)

    def _gc_locked(self) -> None:
        dead = [t for t, (f, _) in self._running.items() if f.done() or f.cancelled()]
        for text in dead:
            self._running.pop(text, None)


__all__ = ["CoalescingEmbeddingModel"]
