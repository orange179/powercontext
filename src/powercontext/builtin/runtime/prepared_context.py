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

"""Prepare final, bounded context from approved Artifact evidence."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from itertools import chain
from typing import TypeVar

from powercontext.artifacts import ArtifactAddress, ArtifactRef
from powercontext.builtin.artifacts.experience import Experience, ExperienceSearchHit, render_experience
from powercontext.builtin.artifacts.memory.models import MemoryCitation, MemoryHit
from powercontext.builtin.artifacts.profile.models import Profile
from powercontext.builtin.artifacts.topic_memory import TopicMemory, TopicMemorySearchHit
from powercontext.builtin.runtime.errors import PreparedContextInvariantError
from powercontext.builtin.runtime.models import PrepareContextRequest, PreparedContext
from powercontext.builtin.runtime.prepared_code import (
    CodeEvidenceRef,
    PreparedCodeCandidate,
    assemble_code,
)
from powercontext.builtin.runtime.prepared_text import (
    TRUST_POLICY,
    ContextTextItem,
    fit_context_text_item,
    render_context_text,
)
from powercontext.builtin.runtime.recall_sufficiency import RecallBudgetView

_MIN_TRUNCATED_CONTENT_BYTES = 64
_ELLIPSIS = "…"
_BEGIN_MARKER = "BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1"
_END_MARKER = "END_POWERCONTEXT_PREPARED_CONTEXT_V1"
_Item = TypeVar("_Item")


@dataclass(frozen=True)
class _PreparedContextEntry:
    origin: PreparedContextOrigin
    kind: str
    citation: dict[str, object]
    content: str
    truncated: bool
    start: int | None = None
    end: int | None = None


@dataclass(frozen=True)
class _EntryFit:
    """One fit attempt on the non-assembly path: the entry that fitted, or why none did.

    The two drop reasons are disjoint and mirror the assembly path's
    :class:`~powercontext.builtin.runtime.prepared_text.FitOutcome`. An entry is dropped
    *below the minimum truncated content* when a shorter rendering exists and fits but is too
    short to be an honest delivery; it is dropped *with no fitting truncation* when no
    shortened rendering fits at all.
    """

    entry: _PreparedContextEntry | None = None
    dropped_below_min_bytes: bool = False
    dropped_no_fitting_truncation: bool = False


@dataclass(frozen=True)
class PreparedContextOmissions:
    """Aggregate counts of the items the byte budget omitted in one build.

    Every count is a per-call aggregate, never per-entry attribution and never a verdict about
    an entry: an entry losing to the budget is not a negative result about that entry.

    ``dropped_items`` is the sum of its two sub-counts, so "the budget could not fit this
    item" can be told apart from "this item was too short to truncate into the remaining
    space". A single merged counter would misreport the second cause as the first.
    """

    truncated_items: int = 0
    dropped_items: int = 0
    dropped_below_min_bytes: int = 0
    dropped_no_fitting_truncation: int = 0


@dataclass(frozen=True)
class PreparedContextBuild:
    """Final public context and the exact origins selected to produce it.

    ``omissions`` is always filled by the Builder. The RFC 1560 recall trace is deliberately
    **not** a field here: ``ScopedContextApplication._prepare`` returns ``build.context`` and
    discards the rest, so such a field would have no production observer. The trace is
    delivered through the Runtime's optional ``RecallEffortSink`` instead.

    ``fragments`` is filled only when the request enabled ``evidence_selection``; it is the
    literal-span projection of ``origins`` and is empty on every other path.
    """

    context: PreparedContext
    origins: tuple[PreparedContextOrigin, ...]
    omissions: PreparedContextOmissions = PreparedContextOmissions()
    code_origins: tuple[CodeEvidenceRef, ...] = ()
    fragments: tuple[PreparedContextFragment, ...] = ()


@dataclass(frozen=True)
class MemoryEntryAddress:
    """Identify one exact Memory entry version across Scope boundaries."""

    memory: ArtifactAddress
    entry_id: str
    entry_version_id: str


PreparedContextOrigin = MemoryCitation | ArtifactRef | MemoryEntryAddress | ArtifactAddress


@dataclass(frozen=True)
class PreparedContextFragment:
    """One literal span of a Memory entry chosen as query-relevant evidence.

    ``text`` is always ``entry.text[start:end]`` of the cited entry version: fragments are
    read-outs of the original body, never rewrites, translations, or generated summaries.
    """

    address: MemoryEntryAddress
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class PreparedMemoryCandidates:
    """Memory candidates read from one Scope."""

    scope_id: str
    memory_ref: ArtifactRef | None = None
    hits: tuple[MemoryHit, ...] = ()


@dataclass(frozen=True)
class PreparedExperienceCandidates:
    """Experience candidates read from one Scope."""

    scope_id: str
    hits: tuple[ExperienceSearchHit, ...] = ()


@dataclass(frozen=True)
class PreparedProfileCandidate:
    """The latest committed Profile snapshot read from one Scope."""

    scope_id: str
    profile: Profile


class PreparedContextBuilder:
    """Select and render final context without I/O, persistence, or reranking."""

    memory_candidate_limit = 16
    topic_memory_candidate_limit = 8
    experience_candidate_limit = 8
    candidate_limit = memory_candidate_limit
    entry_limit = 8
    topic_memory_entry_limit = 8
    experience_entry_limit = 2
    max_entry_content_bytes = 2000
    _text_entry_limit: int | None = None

    def empty(self) -> PreparedContext:
        return PreparedContext(status="empty", content=None, content_bytes=0)

    def build(
        self,
        *,
        request: PrepareContextRequest,
        scope_id: str | None = None,
        memory_ref: ArtifactRef | None = None,
        hits: Sequence[MemoryHit] = (),
        topic_memory_hits: Sequence[TopicMemorySearchHit] = (),
        experience_hits: Sequence[ExperienceSearchHit] = (),
    ) -> PreparedContext:
        return self.build_result(
            request=request,
            scope_id=scope_id,
            memory_ref=memory_ref,
            hits=hits,
            topic_memory_hits=topic_memory_hits,
            experience_hits=experience_hits,
        ).context

    def build_result(
        self,
        *,
        request: PrepareContextRequest,
        scope_id: str | None = None,
        memory_ref: ArtifactRef | None = None,
        hits: Sequence[MemoryHit] = (),
        topic_memory_hits: Sequence[TopicMemorySearchHit] = (),
        experience_hits: Sequence[ExperienceSearchHit] = (),
    ) -> PreparedContextBuild:
        return self.build_scopes_result(
            request=request,
            current_scope_id=scope_id,
            memory_candidates=(
                PreparedMemoryCandidates(scope_id=scope_id or "", memory_ref=memory_ref, hits=tuple(hits)),
            ),
            experience_candidates=(PreparedExperienceCandidates(scope_id=scope_id or "", hits=tuple(experience_hits)),),
            topic_memory_hits=topic_memory_hits,
        )

    def build_scopes_result(
        self,
        *,
        request: PrepareContextRequest,
        current_scope_id: str | None,
        memory_candidates: Sequence[PreparedMemoryCandidates] = (),
        topic_memory_hits: Sequence[TopicMemorySearchHit] = (),
        experience_candidates: Sequence[PreparedExperienceCandidates] = (),
        profile_candidates: Sequence[PreparedProfileCandidate] = (),
        code_candidates: Sequence[PreparedCodeCandidate] = (),
    ) -> PreparedContextBuild:
        if request.evidence_selection:
            return self._build_selection_result(
                request=request,
                current_scope_id=current_scope_id,
                memory_candidates=memory_candidates,
            )

        if request.include_code:

            def historical(history_request: PrepareContextRequest, entries: int) -> PreparedContextBuild:
                builder = PreparedContextBuilder()
                builder.entry_limit = entries
                builder._text_entry_limit = entries if entries < self.entry_limit else None
                return builder.build_scopes_result(
                    request=history_request.model_copy(update={"include_code": False}),
                    current_scope_id=current_scope_id,
                    memory_candidates=memory_candidates,
                    topic_memory_hits=topic_memory_hits,
                    experience_candidates=experience_candidates,
                    profile_candidates=profile_candidates,
                )

            return assemble_code(request, code_candidates, self.entry_limit, historical)

        if sum(len(candidates.hits) for candidates in memory_candidates) > self.memory_candidate_limit:
            raise PreparedContextInvariantError("memory-candidate-limit")
        if len(topic_memory_hits) > self.topic_memory_candidate_limit:
            raise PreparedContextInvariantError("topic-memory-candidate-limit")
        if sum(len(candidates.hits) for candidates in experience_candidates) > self.experience_candidate_limit:
            raise PreparedContextInvariantError("experience-candidate-limit")

        content, origins, fragments, omissions = self._select_entries(
            request=request,
            current_scope_id=current_scope_id,
            memory_candidates=memory_candidates,
            experience_candidates=experience_candidates,
            profile_candidates=profile_candidates,
            topic_memory_hits=topic_memory_hits,
        )
        if content is None:
            return PreparedContextBuild(context=self.empty(), origins=(), omissions=omissions)
        content_bytes = len(content.encode("utf-8"))
        # The assembly path is bounded by construction (every fitted item is measured against
        # `max_bytes`), so the ceiling check belongs to the non-assembly renderer only.
        if request.assembly is None and content_bytes > request.max_bytes:
            raise PreparedContextInvariantError("output-budget")
        return PreparedContextBuild(
            context=PreparedContext(status="ready", content=content, content_bytes=content_bytes),
            origins=origins,
            omissions=omissions,
            fragments=fragments,
        )

    def probe_budget(
        self,
        *,
        request: PrepareContextRequest,
        current_scope_id: str | None,
        memory_candidates: Sequence[PreparedMemoryCandidates] = (),
        topic_memory_hits: Sequence[TopicMemorySearchHit] = (),
        experience_candidates: Sequence[PreparedExperienceCandidates] = (),
        profile_candidates: Sequence[PreparedProfileCandidate] = (),
    ) -> RecallBudgetView:
        """Report what the byte budget does to one candidate set, without delivering it.

        This is the RFC 1560 *budget probe*: one pass of this Builder's own pure selection and
        rendering code, keeping only the counters and discarding the rendered output. It lets
        the gate tell budget-limited thinness from recall-limited thinness.

        Pure and side-effect free: no I/O, no persistence, nothing reported to any sink, and
        the same inputs as :meth:`build_scopes_result` are guaranteed to yield the same
        counters because both go through :meth:`_select_for_request`.
        """

        content, origins, _fragments, omissions = self._select_for_request(
            request=request,
            current_scope_id=current_scope_id,
            memory_candidates=memory_candidates,
            experience_candidates=experience_candidates,
            profile_candidates=profile_candidates,
            topic_memory_hits=topic_memory_hits,
        )
        content_bytes = 0 if content is None else len(content.encode("utf-8"))
        return RecallBudgetView(
            max_bytes=request.max_bytes,
            delivered_items=len(origins),
            truncated_items=omissions.truncated_items,
            dropped_items=omissions.dropped_items,
            unused_bytes=max(0, request.max_bytes - content_bytes),
        )

    def _select_for_request(
        self,
        *,
        request: PrepareContextRequest,
        current_scope_id: str | None,
        memory_candidates: Sequence[PreparedMemoryCandidates],
        experience_candidates: Sequence[PreparedExperienceCandidates],
        profile_candidates: Sequence[PreparedProfileCandidate],
        topic_memory_hits: Sequence[TopicMemorySearchHit],
    ) -> tuple[
        str | None, tuple[PreparedContextOrigin, ...], tuple[PreparedContextFragment, ...], PreparedContextOmissions
    ]:
        """Dispatch to the selection mode the request asked for."""

        if request.evidence_selection:
            return self._select_fragments(request=request, memory_candidates=memory_candidates)
        return self._select_entries(
            request=request,
            current_scope_id=current_scope_id,
            memory_candidates=memory_candidates,
            experience_candidates=experience_candidates,
            profile_candidates=profile_candidates,
            topic_memory_hits=topic_memory_hits,
        )

    def _select_entries(
        self,
        *,
        request: PrepareContextRequest,
        current_scope_id: str | None,
        memory_candidates: Sequence[PreparedMemoryCandidates],
        topic_memory_hits: Sequence[TopicMemorySearchHit],
        experience_candidates: Sequence[PreparedExperienceCandidates],
        profile_candidates: Sequence[PreparedProfileCandidate],
    ) -> tuple[
        str | None, tuple[PreparedContextOrigin, ...], tuple[PreparedContextFragment, ...], PreparedContextOmissions
    ]:
        """Run one complete pure selection pass and render it.

        Returns ``(content, origins, fragments, omissions)``; ``content`` is ``None`` exactly
        when nothing was selected, which is the empty-result case for both paths. This is the
        single selection path shared by :meth:`build_scopes_result` and :meth:`probe_budget`,
        so the probe's counters always describe the selection the build would actually perform.
        """

        if request.assembly is not None:
            return self._select_text(
                request,
                current_scope_id=current_scope_id,
                memory_candidates=memory_candidates,
                experience_candidates=experience_candidates,
                profile_candidates=profile_candidates,
                topic_memory_hits=topic_memory_hits,
            )

        memory_entries = _interleave_groups(
            tuple(
                self._memory_entries(
                    candidates.memory_ref,
                    candidates.hits,
                    scope_id=None if candidates.scope_id == current_scope_id else candidates.scope_id or None,
                )
                for candidates in memory_candidates
            )
        )
        topic_memory_entries = self._topic_memory_entries(topic_memory_hits)
        experience_entries = _interleave_groups(
            tuple(
                self._experience_entries(
                    candidates.hits,
                    scope_id=None if candidates.scope_id == current_scope_id else candidates.scope_id or None,
                )
                for candidates in experience_candidates
            )
        )[: self.experience_entry_limit]
        entries, omissions = self._fit_entries(request, memory_entries, topic_memory_entries, experience_entries)
        if not entries:
            return None, (), (), omissions
        return _render(entries), tuple(entry.origin for entry in entries), (), omissions

    def _select_text(
        self,
        request: PrepareContextRequest,
        *,
        current_scope_id: str | None,
        memory_candidates: Sequence[PreparedMemoryCandidates],
        experience_candidates: Sequence[PreparedExperienceCandidates],
        profile_candidates: Sequence[PreparedProfileCandidate],
        topic_memory_hits: Sequence[TopicMemorySearchHit],
    ) -> tuple[
        str | None, tuple[PreparedContextOrigin, ...], tuple[PreparedContextFragment, ...], PreparedContextOmissions
    ]:
        assembly = request.assembly
        if assembly is None:
            raise PreparedContextInvariantError("text-assembly-missing")
        included: list[ContextTextItem] = []
        origins: list[PreparedContextOrigin] = []
        truncated_items = 0
        dropped_below_min_bytes = 0
        dropped_no_fitting_truncation = 0
        for section in assembly.sections:
            # Unfilled earlier sections leave their capacity available to later ones.
            limit = (
                section.limit
                if self._text_entry_limit is None
                else min(section.limit, self._text_entry_limit - len(included))
            )
            if section.family == "profile":
                entries = self._profile_entries(profile_candidates)
            elif section.family == "topic-memory":
                entries = self._topic_memory_entries(topic_memory_hits, scope_id=current_scope_id)
            else:
                groups = (
                    tuple(
                        tuple(
                            self._memory_entries(group.memory_ref, (hit,), scope_id=group.scope_id)
                            for hit in group.hits
                        )
                        for group in memory_candidates
                    )
                    if section.family == "memory"
                    else tuple(
                        tuple(self._experience_entries((hit,), scope_id=group.scope_id) for hit in group.hits)
                        for group in experience_candidates
                    )
                )
                entries = tuple(chain.from_iterable(_interleave_groups(groups)))
            seen: set[tuple[str, str, str, int, str | None, str | None]] = set()
            rank = 0
            selected_count = 0
            for entry in entries:
                if selected_count >= limit:
                    break
                item = _text_item(entry)
                artifact = item.artifact
                identity = (
                    artifact.scope_id,
                    artifact.artifact.family,
                    artifact.artifact.artifact_id,
                    artifact.artifact.revision,
                    item.entry_id,
                    item.entry_version_id,
                )
                if identity in seen or not item.content.strip():
                    continue
                seen.add(identity)
                rank += 1
                outcome = fit_context_text_item(included, replace(item, recall_rank=rank), assembly, request.max_bytes)
                if outcome.item is None:
                    dropped_below_min_bytes += int(outcome.dropped_below_min_bytes)
                    dropped_no_fitting_truncation += int(outcome.dropped_no_fitting_truncation)
                    continue
                fitted = outcome.item
                included.append(fitted)
                origins.append(entry.origin)
                selected_count += 1
                truncated_items += int(fitted.truncated)
        omissions = PreparedContextOmissions(
            truncated_items=truncated_items,
            dropped_items=dropped_below_min_bytes + dropped_no_fitting_truncation,
            dropped_below_min_bytes=dropped_below_min_bytes,
            dropped_no_fitting_truncation=dropped_no_fitting_truncation,
        )
        if not included:
            return None, (), (), omissions
        content = render_context_text(included, assembly)
        return content, tuple(origins), (), omissions

    def _build_selection_result(
        self,
        *,
        request: PrepareContextRequest,
        current_scope_id: str | None,
        memory_candidates: Sequence[PreparedMemoryCandidates],
    ) -> PreparedContextBuild:
        if sum(len(candidates.hits) for candidates in memory_candidates) > self.memory_candidate_limit:
            raise PreparedContextInvariantError("memory-candidate-limit")
        content, origins, fragments, omissions = self._select_fragments(
            request=request,
            memory_candidates=memory_candidates,
        )
        if content is None:
            return PreparedContextBuild(context=self.empty(), origins=(), omissions=omissions)
        content_bytes = len(content.encode("utf-8"))
        if content_bytes > request.max_bytes:
            raise PreparedContextInvariantError("output-budget")
        return PreparedContextBuild(
            context=PreparedContext(status="ready", content=content, content_bytes=content_bytes),
            origins=origins,
            omissions=omissions,
            fragments=fragments,
        )

    def _select_fragments(
        self,
        *,
        request: PrepareContextRequest,
        memory_candidates: Sequence[PreparedMemoryCandidates],
    ) -> tuple[
        str | None,
        tuple[PreparedContextOrigin, ...],
        tuple[PreparedContextFragment, ...],
        PreparedContextOmissions,
    ]:
        """Choose literal sentence runs whose terms answer ``request.query``.

        Selection is organised per candidate entry, not per sentence. Every emitted fragment
        starts from that entry's best-matching sentence and then grows outward over adjacent
        sentences, so each entry contributes one contiguous, re-readable slice of its original
        body. Growing instead of scattering matters because the per-item citation overhead is
        several hundred bytes: starting a second fragment in the same entry would spend that
        overhead again and leave less room for original text.

        The number of entries that receive a slice is derived from the budget itself, and the
        content budget is split with a decay so the best-matching entry receives the largest
        share while weaker candidates still contribute a hedge.
        """

        groups = self._fragment_groups(memory_candidates)
        if not groups:
            return None, (), (), PreparedContextOmissions()
        ranked_groups = _ranked_scored_groups(groups, _query_terms(request.query))
        merged = [region for region in _plan_fragment_regions(ranked_groups, request.max_bytes) if region is not None]
        if not merged:
            # Not even one whole sentence fits. Emit the longest literal prefix that does, so
            # the caller still receives citable original text instead of an empty context.
            merged = _first_clamped_fragment(ranked_groups, request.max_bytes)
        else:
            merged = _top_up_fragments(merged, request.max_bytes)
        if not merged:
            return None, (), (), PreparedContextOmissions()

        ordered = sorted(merged, key=lambda span: span.order)
        entries = tuple(_fragment_entry(span) for span in ordered)
        fragments = tuple(_fragment_citation(span) for span in ordered)
        return _render(entries), tuple(entry.origin for entry in entries), fragments, PreparedContextOmissions()

    def _fragment_groups(
        self,
        memory_candidates: Sequence[PreparedMemoryCandidates],
    ) -> tuple[tuple[_FragmentSpan, ...], ...]:
        """Split every distinct candidate entry into its whole-sentence spans."""

        grouped: dict[tuple[str, str, str], tuple[_FragmentSpan, ...]] = {}
        order = 0
        for candidates in memory_candidates:
            for hit in _citable_hits(candidates):
                key = (candidates.scope_id, hit.entry_id, hit.entry_version_id)
                if key in grouped:
                    continue
                spans = _sentence_fragments(candidates.scope_id, hit, order)
                order += len(spans)
                if spans:
                    grouped[key] = spans
        return tuple(grouped.values())

    def _profile_entries(self, candidates: Sequence[PreparedProfileCandidate]) -> tuple[_PreparedContextEntry, ...]:
        entries = []
        for candidate in candidates:
            origin = ArtifactAddress(scope_id=candidate.scope_id, artifact=candidate.profile.as_ref())
            entries.append(
                _PreparedContextEntry(
                    origin=origin,
                    kind="profile",
                    citation={"artifact": origin.model_dump(mode="json")},
                    content=candidate.profile.content.content,
                    truncated=False,
                )
            )
        return tuple(entries)

    def _memory_entries(
        self,
        memory_ref: ArtifactRef | None,
        hits: Sequence[MemoryHit],
        *,
        scope_id: str | None = None,
    ) -> tuple[_PreparedContextEntry, ...]:
        if hits and memory_ref is None:
            raise PreparedContextInvariantError("memory-ref-missing")
        memory_entries: list[_PreparedContextEntry] = []
        seen: set[tuple[str, str]] = set()
        for hit in hits:
            if hit.memory_ref != memory_ref:
                raise PreparedContextInvariantError("memory-ref-mismatch")

            citation_key = (hit.entry_id, hit.entry_version_id)
            if citation_key in seen:
                continue
            seen.add(citation_key)
            if not hit.entry_id.strip() or not hit.entry_version_id.strip() or not hit.text.strip():
                continue
            citation = MemoryCitation(
                memory_ref=hit.memory_ref,
                entry_id=hit.entry_id,
                entry_version_id=hit.entry_version_id,
            )
            origin: PreparedContextOrigin = citation
            rendered_citation = citation.model_dump(mode="json")
            if scope_id is not None:
                memory = ArtifactAddress(scope_id=scope_id, artifact=hit.memory_ref)
                origin = MemoryEntryAddress(
                    memory=memory,
                    entry_id=hit.entry_id,
                    entry_version_id=hit.entry_version_id,
                )
                rendered_citation = {
                    "memory": memory.model_dump(mode="json"),
                    "entry_id": hit.entry_id,
                    "entry_version_id": hit.entry_version_id,
                }
            memory_entries.append(
                _PreparedContextEntry(
                    origin=origin,
                    kind="memory",
                    citation=rendered_citation,
                    content=hit.text,
                    truncated=False,
                )
            )
        return tuple(memory_entries)

    def _topic_memory_entries(
        self,
        hits: Sequence[TopicMemorySearchHit],
        *,
        scope_id: str | None = None,
    ) -> tuple[_PreparedContextEntry, ...]:
        topic_entries: list[_PreparedContextEntry] = []
        seen_topics: set[tuple[str, int]] = set()
        for hit in hits:
            if hit.artifact_ref.family != TopicMemory.family:
                raise PreparedContextInvariantError("topic-memory-family-mismatch")
            identity = (hit.artifact_ref.artifact_id, hit.artifact_ref.revision)
            if identity in seen_topics:
                continue
            seen_topics.add(identity)
            if len(topic_entries) >= self.topic_memory_entry_limit:
                break
            content = {"title": hit.title, "summary": hit.summary}
            if hit.snippet is not None:
                content["snippet"] = hit.snippet
            origin: PreparedContextOrigin = hit.artifact_ref
            citation = {"artifact_ref": hit.artifact_ref.model_dump(mode="json")}
            body = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
            if scope_id is not None:
                origin = ArtifactAddress(scope_id=scope_id, artifact=hit.artifact_ref)
                citation = {"artifact": origin.model_dump(mode="json")}
                body = "\n\n".join(f"{label.capitalize()}: {value}" for label, value in content.items())
            topic_entries.append(
                _PreparedContextEntry(
                    origin=origin,
                    kind="topic-memory",
                    citation=citation,
                    content=body,
                    truncated=False,
                )
            )
        return tuple(topic_entries)

    def _experience_entries(
        self,
        hits: Sequence[ExperienceSearchHit],
        *,
        scope_id: str | None = None,
    ) -> tuple[_PreparedContextEntry, ...]:
        experience_entries: list[_PreparedContextEntry] = []
        seen_experiences: set[tuple[str, int]] = set()
        for hit in hits:
            if hit.artifact_ref.family != Experience.family:
                raise PreparedContextInvariantError("experience-family-mismatch")
            identity = (hit.artifact_ref.artifact_id, hit.artifact_ref.revision)
            if identity in seen_experiences:
                continue
            seen_experiences.add(identity)
            origin: PreparedContextOrigin = hit.artifact_ref
            rendered_citation: dict[str, object] = {"artifact_ref": hit.artifact_ref.model_dump(mode="json")}
            if scope_id is not None:
                origin = ArtifactAddress(scope_id=scope_id, artifact=hit.artifact_ref)
                rendered_citation = {"artifact": origin.model_dump(mode="json")}
            experience_entries.append(
                _PreparedContextEntry(
                    origin=origin,
                    kind="experience",
                    citation=rendered_citation,
                    content=render_experience(hit.content),
                    truncated=False,
                )
            )
        return tuple(experience_entries)

    def _fit_entries(
        self,
        request: PrepareContextRequest,
        memory_entries: Sequence[_PreparedContextEntry],
        topic_memory_entries: Sequence[_PreparedContextEntry],
        experience_entries: Sequence[_PreparedContextEntry],
    ) -> tuple[tuple[_PreparedContextEntry, ...], PreparedContextOmissions]:
        entries: list[_PreparedContextEntry] = []
        truncated_items = 0
        dropped_below_min_bytes = 0
        dropped_no_fitting_truncation = 0
        for candidate in _interleave(memory_entries, topic_memory_entries, experience_entries):
            if len(entries) >= self.entry_limit:
                break
            fit = self._fit_entry(
                entries,
                origin=candidate.origin,
                kind=candidate.kind,
                citation=candidate.citation,
                text=candidate.content,
                max_bytes=request.max_bytes,
            )
            if fit.entry is None:
                dropped_below_min_bytes += int(fit.dropped_below_min_bytes)
                dropped_no_fitting_truncation += int(fit.dropped_no_fitting_truncation)
                continue
            entries.append(fit.entry)
            if fit.entry.truncated:
                truncated_items += 1
        return tuple(entries), PreparedContextOmissions(
            truncated_items=truncated_items,
            dropped_items=dropped_below_min_bytes + dropped_no_fitting_truncation,
            dropped_below_min_bytes=dropped_below_min_bytes,
            dropped_no_fitting_truncation=dropped_no_fitting_truncation,
        )

    def _fit_entry(
        self,
        entries: Sequence[_PreparedContextEntry],
        *,
        origin: PreparedContextOrigin,
        kind: str,
        citation: dict[str, object],
        text: str,
        max_bytes: int,
    ) -> _EntryFit:
        """Fit one entry into the remaining budget, reporting why it was dropped if it was.

        The two ``None`` paths of the original code are kept apart: ``below-min-bytes`` means a
        shorter rendering exists and fits but is too short to deliver honestly, while
        ``no-fitting-truncation`` means no shortened rendering fitted at all.
        """

        source_bytes = len(text.encode("utf-8"))
        entry_budget = min(source_bytes, self.max_entry_content_bytes)
        candidate = _PreparedContextEntry(
            origin=origin,
            kind=kind,
            citation=citation,
            content=text if source_bytes <= entry_budget else _truncate_utf8(text, entry_budget),
            truncated=source_bytes > entry_budget,
        )
        if _rendered_bytes((*entries, candidate)) <= max_bytes:
            return _EntryFit(entry=candidate)
        if source_bytes < _MIN_TRUNCATED_CONTENT_BYTES:
            return _EntryFit(dropped_below_min_bytes=True)

        lower = _MIN_TRUNCATED_CONTENT_BYTES
        upper = min(entry_budget, source_bytes - 1)
        best: _PreparedContextEntry | None = None
        while lower <= upper:
            byte_budget = (lower + upper) // 2
            candidate = _PreparedContextEntry(
                origin=origin,
                kind=kind,
                citation=citation,
                content=_truncate_utf8(text, byte_budget),
                truncated=True,
            )
            if len(candidate.content.encode("utf-8")) < _MIN_TRUNCATED_CONTENT_BYTES:
                lower = byte_budget + 1
                continue
            if _rendered_bytes((*entries, candidate)) <= max_bytes:
                best = candidate
                lower = byte_budget + 1
            else:
                upper = byte_budget - 1
        if best is None:
            return _EntryFit(dropped_no_fitting_truncation=True)
        return _EntryFit(entry=best)


def _interleave(
    memory: Sequence[_PreparedContextEntry],
    topics: Sequence[_PreparedContextEntry],
    experiences: Sequence[_PreparedContextEntry],
) -> tuple[_PreparedContextEntry, ...]:
    """Preserve each family's rank while alternating Memory, Topic, Experience."""

    ordered: list[_PreparedContextEntry] = []
    for index in range(max(len(memory), len(topics), len(experiences))):
        if index < len(memory):
            ordered.append(memory[index])
        if index < len(topics):
            ordered.append(topics[index])
        if index < len(experiences):
            ordered.append(experiences[index])
    return tuple(ordered)


def _interleave_groups(groups: Sequence[Sequence[_Item]]) -> tuple[_Item, ...]:
    ordered: list[_Item] = []
    for index in range(max((len(group) for group in groups), default=0)):
        ordered.extend(group[index] for group in groups if index < len(group))
    return tuple(ordered)


def _render(entries: Sequence[_PreparedContextEntry]) -> str:
    envelope = {
        "trust": "untrusted_history",
        "items": [_render_entry(entry) for entry in entries],
    }
    encoded = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
    return "\n\n".join((TRUST_POLICY, f"{_BEGIN_MARKER}\n{encoded}\n{_END_MARKER}"))


def _text_item(entry: _PreparedContextEntry) -> ContextTextItem:
    origin = entry.origin
    if isinstance(origin, MemoryEntryAddress):
        return ContextTextItem(
            artifact=origin.memory,
            content=entry.content,
            recall_rank=0,
            entry_id=origin.entry_id,
            entry_version_id=origin.entry_version_id,
        )
    if isinstance(origin, ArtifactAddress):
        return ContextTextItem(artifact=origin, content=entry.content, recall_rank=0)
    raise PreparedContextInvariantError("text-scope-missing")


def _render_entry(entry: _PreparedContextEntry) -> dict[str, object]:
    rendered: dict[str, object] = {"citation": entry.citation, "content": entry.content}
    if entry.start is None or entry.end is None:
        rendered["truncated"] = entry.truncated
    else:
        rendered["start"] = entry.start
        rendered["end"] = entry.end
    if entry.kind != "memory":
        rendered["kind"] = entry.kind
    return rendered


def _rendered_bytes(entries: Sequence[_PreparedContextEntry]) -> int:
    return len(_render(entries).encode("utf-8"))


def _truncate_utf8(text: str, byte_budget: int) -> str:
    prefix_budget = byte_budget - len(_ELLIPSIS.encode("utf-8"))
    encoded_prefix = text.encode("utf-8")[:prefix_budget]
    return f"{encoded_prefix.decode('utf-8', errors='ignore')}{_ELLIPSIS}"


@dataclass(frozen=True)
class _FragmentSpan:
    """One whole-sentence slice of a Memory entry version, ready to score and grow."""

    scope_id: str
    memory_ref: ArtifactRef
    entry_id: str
    entry_version_id: str
    text: str
    start: int
    end: int
    score: float
    order: int
    tokens: frozenset[str] = frozenset()


_TOKEN_PATTERN = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+")
# Sentence terminators cover Latin stops plus the CJK full stops and question marks, which are
# written as escapes so the literal never depends on ambiguous full-width glyphs.
_SENTENCE_ENDS = ".!?\u3002\uff01\uff1f"
_SENTENCE_CLOSERS = "\"'\u201d\u2019)]}\u00bb"
_STOPWORD_TEXT = """
    a about after again against all also an and any are as at be because been before being between both but by
    can could did do does during each few for from further had has have having he her here hers herself him
    himself his how however i if in into is it its itself just may me might more most must my myself no nor not
    now of off on once only or other our ours ourselves out over own same she should so some such than that the
    their theirs them themselves then there these they this those through to too under until up very was we were
    what when where which while who whom why will with would you your yours yourself yourselves
"""
_STOPWORDS = frozenset(_STOPWORD_TEXT.split())


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(_TOKEN_PATTERN.findall(text.lower()))


def _query_terms(query: str) -> frozenset[str]:
    tokens = _tokens(query)
    content = frozenset(token for token in tokens if token not in _STOPWORDS)
    return content if content else frozenset(tokens)


def _sentence_spans(text: str) -> tuple[tuple[int, int], ...]:
    """Split ``text`` into whole-sentence spans that are exact slices of the original."""

    spans: list[tuple[int, int]] = []
    length = len(text)
    start = 0
    for index in range(length):
        if not _is_sentence_break(text, index):
            continue
        spans.append(_trim_span(text, start, index + 1))
        start = index + 1
    spans.append(_trim_span(text, start, length))
    return tuple(span for span in spans if span[1] > span[0])


def _is_sentence_break(text: str, index: int) -> bool:
    char = text[index]
    if char == "\n":
        return True
    if char not in _SENTENCE_ENDS:
        return False
    cursor = index + 1
    while cursor < len(text) and text[cursor] in _SENTENCE_CLOSERS:
        cursor += 1
    if cursor >= len(text):
        return True
    if not text[cursor].isspace():
        # Decimal points and dotted abbreviations stay inside their sentence.
        return False
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1
    if cursor >= len(text):
        return True
    following = text[cursor]
    # A new sentence starts on any character that cannot continue a lowercase Latin word,
    # which covers capitals, digits, opening punctuation, and non-Latin scripts.
    return not (following.isascii() and following.islower())


def _trim_span(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _citable_hits(candidates: PreparedMemoryCandidates) -> tuple[MemoryHit, ...]:
    """Validate one candidate group and return its deduplicated, citable, non-empty hits."""

    if candidates.hits and candidates.memory_ref is None:
        raise PreparedContextInvariantError("memory-ref-missing")
    memory_ref = candidates.memory_ref
    hits: list[MemoryHit] = []
    seen: set[tuple[str, str]] = set()
    for hit in candidates.hits:
        if hit.memory_ref != memory_ref:
            raise PreparedContextInvariantError("memory-ref-mismatch")
        citation_key = (hit.entry_id, hit.entry_version_id)
        if citation_key in seen:
            continue
        seen.add(citation_key)
        if memory_ref is None:
            continue
        if not hit.entry_id.strip() or not hit.entry_version_id.strip() or not hit.text.strip():
            continue
        hits.append(hit)
    return tuple(hits)


def _sentence_fragments(scope_id: str, hit: MemoryHit, order: int) -> tuple[_FragmentSpan, ...]:
    """Project one hit onto its whole-sentence spans, numbering them from ``order``."""

    return tuple(
        _FragmentSpan(
            scope_id=scope_id,
            memory_ref=hit.memory_ref,
            entry_id=hit.entry_id,
            entry_version_id=hit.entry_version_id,
            text=hit.text,
            start=start,
            end=end,
            score=0.0,
            order=order + offset,
        )
        for offset, (start, end) in enumerate(_sentence_spans(hit.text))
    )


def _slot_weights(slots: int) -> tuple[float, ...]:
    """Split a content budget with a decay, so rank 0 always receives the largest share."""

    raw = tuple(0.6**rank for rank in range(max(slots, 0)))
    total = sum(raw)
    return tuple(value / total for value in raw) if total else ()


def _ranked_scored_groups(
    groups: Sequence[Sequence[_FragmentSpan]],
    terms: frozenset[str],
) -> tuple[tuple[_FragmentSpan, ...], ...]:
    """Score every sentence by the IDF weight of the query terms it contains, then rank entries."""

    scored_groups: list[tuple[_FragmentSpan, ...]] = []
    token_sets: list[frozenset[str]] = []
    for spans in groups:
        scored: list[_FragmentSpan] = []
        for span in spans:
            tokens = frozenset(_tokens(span.text[span.start : span.end]))
            token_sets.append(tokens)
            scored.append(replace(span, tokens=tokens))
        scored_groups.append(tuple(scored))

    if terms:
        document_frequency = dict.fromkeys(terms, 0)
        for tokens in token_sets:
            for term in terms:
                if term in tokens:
                    document_frequency[term] += 1
        total = len(token_sets)
        idf = {term: math.log(1.0 + total / (1.0 + document_frequency[term])) for term in terms}
        scored_groups = [
            tuple(replace(span, score=sum(idf[term] for term in terms if term in span.tokens)) for span in spans)
            for spans in scored_groups
        ]

    return tuple(sorted(scored_groups, key=lambda spans: (-max(span.score for span in spans), spans[0].order)))


def _plan_fragment_regions(
    ranked_groups: Sequence[Sequence[_FragmentSpan]],
    max_bytes: int,
) -> tuple[_FragmentSpan | None, ...]:
    """Assign each of the best-ranked entries one contiguous slice of its own body.

    Planning runs in two phases. Seeding first spreads small slices across as many entries as
    the budget can afford, because the entry that holds the answer is not always the top-ranked
    one. Growing then deepens those slices in rank order on a decaying share, so the
    best-matching entry still ends up with the most original text.
    """

    if not ranked_groups:
        return ()

    fixed_bytes = _rendered_bytes(())
    probe = ranked_groups[0][0]
    item_overhead = max(1, _fragment_render_bytes((probe,)) - fixed_bytes - _span_bytes(probe))
    available = max_bytes - fixed_bytes
    # A slice shorter than this cannot hold a meaningful run of original sentences, so it is
    # not worth paying a whole entry's citation overhead for.
    min_share = 120
    max_slots = (available - min_share) // (item_overhead + min_share) if available > min_share else 0
    slots = max(1, min(len(ranked_groups), max_slots))

    regions: list[_FragmentSpan | None] = [None] * len(ranked_groups)
    bounds: dict[int, tuple[int, int]] = {}

    remaining = _seed_regions(ranked_groups, regions, bounds, slots, min_share, max_bytes, fixed_bytes, item_overhead)
    _grow_regions(ranked_groups, regions, bounds, remaining, max_bytes)
    return tuple(regions)


def _seed_regions(
    ranked_groups: Sequence[Sequence[_FragmentSpan]],
    regions: list[_FragmentSpan | None],
    bounds: dict[int, tuple[int, int]],
    slots: int,
    min_share: int,
    max_bytes: int,
    fixed_bytes: int,
    item_overhead: int,
) -> int:
    """Give each servable entry its best-matching sentence, reserving room for the rest."""

    remaining = max_bytes - fixed_bytes
    for rank in range(slots):
        reserved = (slots - rank - 1) * (item_overhead + min_share)
        cap = remaining - item_overhead - reserved
        if cap < min_share:
            break
        if not _seed_region(ranked_groups, regions, bounds, rank, cap, max_bytes):
            continue
        remaining -= _span_bytes(regions[rank]) + item_overhead
    return remaining


def _grow_regions(
    ranked_groups: Sequence[Sequence[_FragmentSpan]],
    regions: list[_FragmentSpan | None],
    bounds: dict[int, tuple[int, int]],
    remaining: int,
    max_bytes: int,
) -> None:
    """Deepen the seeded slices in rank order, decaying the share so rank 0 grows most."""

    seeded = [index for index, region in enumerate(regions) if region is not None]
    pool = max(0, remaining)
    for position, index in enumerate(seeded):
        if pool <= 0:
            return
        weight = _slot_weights(len(seeded) - position)[0]
        cap = _span_bytes(regions[index]) + int(pool * weight)
        before = _region_content_bytes(regions)
        _grow_region(ranked_groups, regions, bounds, index, cap, max_bytes)
        pool -= _region_content_bytes(regions) - before


def _grow_region(
    ranked_groups: Sequence[Sequence[_FragmentSpan]],
    regions: list[_FragmentSpan | None],
    bounds: dict[int, tuple[int, int]],
    group_index: int,
    cap: int,
    max_bytes: int,
) -> None:
    """Give one entry the longest run of adjacent sentences that fits ``cap`` and the budget."""

    spans = ranked_groups[group_index]
    if group_index not in bounds and not _seed_region(ranked_groups, regions, bounds, group_index, cap, max_bytes):
        return
    while True:
        low, high = bounds[group_index]
        options = [index for index in (low - 1, high + 1) if 0 <= index < len(spans)]
        if not options:
            return
        options.sort(key=lambda index: (-spans[index].score, index))
        if not _grow_once(spans, regions, bounds, group_index, options, cap, max_bytes):
            return


def _seed_region(
    ranked_groups: Sequence[Sequence[_FragmentSpan]],
    regions: list[_FragmentSpan | None],
    bounds: dict[int, tuple[int, int]],
    group_index: int,
    cap: int,
    max_bytes: int,
) -> bool:
    """Start one entry's slice at its best sentence that fits ``cap``; report success.

    A sentence far weaker than the entry's own best match is not accepted as a fallback: the
    citation overhead is worth paying only for evidence the query actually asked for.
    """

    spans = ranked_groups[group_index]
    threshold = max(span.score for span in spans) * 0.5
    for seed in sorted(range(len(spans)), key=lambda index: (-spans[index].score, index)):
        if spans[seed].score < threshold:
            return False
        if _span_bytes(spans[seed]) > cap:
            continue
        trial = list(regions)
        trial[group_index] = spans[seed]
        if _render_regions(trial) > max_bytes:
            continue
        regions[group_index] = spans[seed]
        bounds[group_index] = (seed, seed)
        return True
    return False


def _grow_once(
    spans: Sequence[_FragmentSpan],
    regions: list[_FragmentSpan | None],
    bounds: dict[int, tuple[int, int]],
    group_index: int,
    options: Sequence[int],
    cap: int,
    max_bytes: int,
) -> bool:
    """Extend one entry's slice by the best adjacent sentence that still fits; report success."""

    low, high = bounds[group_index]
    for index in options:
        new_low, new_high = min(low, index), max(high, index)
        grown = replace(spans[low], start=spans[new_low].start, end=spans[new_high].end)
        if _span_bytes(grown) > cap:
            continue
        trial = list(regions)
        trial[group_index] = grown
        if _render_regions(trial) > max_bytes:
            continue
        regions[group_index] = grown
        bounds[group_index] = (new_low, new_high)
        return True
    return False


def _render_regions(values: Sequence[_FragmentSpan | None]) -> int:
    return _fragment_render_bytes(tuple(value for value in values if value is not None))


def _first_clamped_fragment(
    ranked_groups: Sequence[Sequence[_FragmentSpan]],
    max_bytes: int,
) -> list[_FragmentSpan]:
    for spans in ranked_groups:
        for span in sorted(spans, key=lambda item: -item.score):
            clamped = _clamp_fragment(span, max_bytes)
            if clamped is not None:
                return [clamped]
    return []


def _top_up_fragments(fragments: Sequence[_FragmentSpan], max_bytes: int) -> list[_FragmentSpan]:
    """Spend any budget the sentence-aligned plan left unused on literal continuation text.

    Whole sentences keep each slice readable, but a run often cannot grow to exactly its share
    because the next sentence overshoots. Extending the tail with the longest literal prefix of
    the following text keeps the output inside ``max_bytes`` without ever wasting the caller's
    room for evidence.
    """

    extended = list(fragments)
    for index, fragment in enumerate(extended):
        if fragment.end >= len(fragment.text):
            continue
        best = fragment
        lower, upper = fragment.end, len(fragment.text)
        while lower <= upper:
            middle = (lower + upper) // 2
            candidate = replace(fragment, end=middle)
            trial = list(extended)
            trial[index] = candidate
            if _render_regions(trial) <= max_bytes:
                best = candidate
                lower = middle + 1
            else:
                upper = middle - 1
        extended[index] = best
    return extended


def _span_bytes(span: _FragmentSpan) -> int:
    return len(span.text[span.start : span.end].encode("utf-8"))


def _fragment_citation(span: _FragmentSpan) -> PreparedContextFragment:
    return PreparedContextFragment(
        address=MemoryEntryAddress(
            memory=ArtifactAddress(scope_id=span.scope_id, artifact=span.memory_ref),
            entry_id=span.entry_id,
            entry_version_id=span.entry_version_id,
        ),
        start=span.start,
        end=span.end,
        text=span.text[span.start : span.end],
    )


def _region_content_bytes(regions: Sequence[_FragmentSpan | None]) -> int:
    return sum(_span_bytes(span) for span in regions if span is not None)


def _fragment_entry(span: _FragmentSpan) -> _PreparedContextEntry:
    memory = ArtifactAddress(scope_id=span.scope_id, artifact=span.memory_ref)
    return _PreparedContextEntry(
        origin=MemoryEntryAddress(memory=memory, entry_id=span.entry_id, entry_version_id=span.entry_version_id),
        kind="memory",
        citation={
            "scope_id": span.scope_id,
            "memory_ref": span.memory_ref.model_dump(mode="json"),
            "entry_id": span.entry_id,
            "entry_version_id": span.entry_version_id,
        },
        content=span.text[span.start : span.end],
        truncated=False,
        start=span.start,
        end=span.end,
    )


def _fragment_render_bytes(spans: Sequence[_FragmentSpan]) -> int:
    return _rendered_bytes(tuple(_fragment_entry(span) for span in spans))


def _clamp_fragment(span: _FragmentSpan, max_bytes: int) -> _FragmentSpan | None:
    """Shorten one span to the longest literal prefix that fits ``max_bytes``."""

    lower, upper = span.start + 1, span.end
    best: _FragmentSpan | None = None
    while lower <= upper:
        middle = (lower + upper) // 2
        candidate = replace(span, end=middle)
        if _fragment_render_bytes((candidate,)) <= max_bytes:
            best = candidate
            lower = middle + 1
        else:
            upper = middle - 1
    return best
