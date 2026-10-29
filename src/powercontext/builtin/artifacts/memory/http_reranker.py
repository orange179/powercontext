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

"""HTTP cross-encoder reranking over a bounded Memory candidate pool."""

from __future__ import annotations

import math
from typing import Any

import httpx

from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.artifacts.memory.reranking import MemoryRerankDecision
from powercontext.builtin.inference import InferenceUsage

HTTP_RERANK_DEFAULT_POLICY_ID = "http-cross-encoder-v1"


class HTTPMemoryReranker:
    """Score candidates through an HTTP service and select them globally.

    The service enforces a per-request candidate cap, so a pool larger than
    ``batch_size`` is split into consecutive batches. Batches always carry the
    candidate's rank in the complete input, which lets scores from every batch
    participate in one global ordering without renumbering anything.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        client: httpx.AsyncClient,
        batch_size: int = 32,
        policy_id: str = HTTP_RERANK_DEFAULT_POLICY_ID,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be at least one")  # noqa: TRY003
        self.policy_id = policy_id
        self._endpoint = endpoint
        self._client = client
        self._batch_size = batch_size

    async def rerank(
        self,
        query: str,
        candidates: tuple[MemoryHit, ...],
        limit: int,
        /,
    ) -> MemoryRerankDecision:
        """Return the highest scored original ranks without changing hit identity."""

        _validate_bounds(len(candidates), limit)
        scores: dict[int, float] = {}
        request_count = 0
        for start in range(0, len(candidates), self._batch_size):
            batch = candidates[start : start + self._batch_size]
            first_rank = start + 1
            expected_ranks = range(first_rank, first_rank + len(batch))
            response = await self._client.post(
                self._endpoint,
                json={
                    "query": query,
                    "candidates": [
                        {"rank": rank, "text": candidate.text}
                        for rank, candidate in zip(expected_ranks, batch, strict=True)
                    ],
                },
            )
            request_count += 1
            response.raise_for_status()
            scores.update(_parse_scores(response, expected_ranks=frozenset(expected_ranks)))
        # Descending score with the original global rank as the stable tie-break.
        ordered = sorted(scores, key=lambda rank: (-scores[rank], rank))
        return MemoryRerankDecision(
            selected_ranks=tuple(ordered[:limit]),
            usage=InferenceUsage(requests=request_count),
        )


def _parse_scores(response: httpx.Response, *, expected_ranks: frozenset[int]) -> dict[int, float]:
    """Validate one batch response and return its rank-to-score mapping."""

    try:
        payload = response.json()
    except ValueError as error:
        raise ValueError("rerank response is not valid JSON") from error  # noqa: TRY003
    if not isinstance(payload, dict) or set(payload) != {"scores"}:
        raise ValueError("rerank response must contain exactly the 'scores' field")  # noqa: TRY003
    entries = payload["scores"]
    if not isinstance(entries, list):
        raise ValueError("rerank response 'scores' must be a list")  # noqa: TRY003
    scores: dict[int, float] = {}
    for entry in entries:
        rank, score = _parse_score_entry(entry)
        if rank not in expected_ranks:
            raise ValueError(f"rerank response rank {rank} is not part of the requested batch")  # noqa: TRY003
        if rank in scores:
            raise ValueError(f"rerank response repeats rank {rank}")  # noqa: TRY003
        scores[rank] = score
    missing = expected_ranks.difference(scores)
    if missing:
        raise ValueError(f"rerank response is missing ranks {sorted(missing)}")  # noqa: TRY003
    return scores


def _parse_score_entry(entry: Any) -> tuple[int, float]:
    if not isinstance(entry, dict) or set(entry) != {"rank", "score"}:
        raise ValueError("each rerank score must contain exactly 'rank' and 'score'")  # noqa: TRY003
    rank = entry["rank"]
    # ``bool`` is an ``int`` subclass, so exclude it explicitly.
    if isinstance(rank, bool) or not isinstance(rank, int):
        raise ValueError("rerank score rank must be an integer")  # noqa: TRY003
    score = entry["score"]
    if isinstance(score, bool) or not isinstance(score, int | float):
        raise ValueError("rerank score must be a number")  # noqa: TRY003
    value = float(score)
    if not math.isfinite(value):
        raise ValueError("rerank score must be finite")  # noqa: TRY003
    return rank, value


def _validate_bounds(candidate_count: int, limit: int) -> None:
    if candidate_count < 1:
        raise ValueError("rerank requires at least one candidate")  # noqa: TRY003
    if limit < 1 or limit > candidate_count:
        raise ValueError("rerank limit must be between one and the candidate count")  # noqa: TRY003


__all__ = [
    "HTTP_RERANK_DEFAULT_POLICY_ID",
    "HTTPMemoryReranker",
]
