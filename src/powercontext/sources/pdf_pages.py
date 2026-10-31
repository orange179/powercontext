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

"""PDF page-level Source: parse full PDF documents into per-page captured Sources."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from io import BytesIO

from pydantic import BaseModel, ConfigDict, JsonValue

from powercontext.builtin.artifacts.memory.models import MemoryCitation
from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources import AdapterSourceDefinition, TextEvidence
from powercontext.sources.models import Source, SourceMaterialization

PDF_PAGE_SOURCE_NAME = "pdf-page"

_TOKEN_PATTERN = re.compile(r"[a-z]+|\d+")
_HEADING_PATTERN = re.compile(
    r"^(Item\s+\d+[A-Z]?\.|Note\s+\d+|PART\s+[IVX]+|Consolidated\s+(Statement|Balance))",
    re.IGNORECASE,
)
_TABLE_OF_CONTENTS = "table of contents"

_STOPWORDS = frozenset([
    "a",
    "an",
    "the",
    "of",
    "to",
    "in",
    "on",
    "for",
    "and",
    "or",
    "by",
    "as",
    "at",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "that",
    "this",
    "these",
    "those",
    "with",
    "from",
    "what",
    "which",
    "who",
    "whom",
    "whose",
    "when",
    "where",
    "why",
    "how",
    "has",
    "have",
    "had",
    "do",
    "does",
    "did",
    "any",
    "all",
    "some",
    "no",
    "not",
    "if",
    "then",
    "than",
    "so",
    "it",
    "its",
    "their",
    "they",
    "them",
    "we",
    "our",
    "you",
    "your",
    "he",
    "she",
    "his",
    "her",
    "there",
    "here",
    "about",
    "into",
    "over",
    "under",
    "between",
    "during",
    "per",
    "each",
    "more",
    "most",
    "less",
    "least",
    "other",
    "others",
    "such",
    "both",
    "either",
    "neither",
    "can",
    "could",
    "should",
    "would",
    "may",
    "might",
    "must",
    "will",
    "shall",
    "please",
    "state",
    "states",
    "stated",
    "show",
    "shown",
    "given",
    "give",
    "following",
    "follow",
    "based",
    "use",
    "used",
    "using",
    "respond",
    "response",
    "answer",
    "question",
    "questions",
    "only",
    "also",
    "just",
    "very",
    "much",
    "many",
    "define",
    "assume",
    "assuming",
    "perspective",
    "relying",
    "rely",
    "calculate",
    "compute",
    "tell",
    "describe",
    "list",
    "name",
    "identify",
    "value",
    "values",
    "number",
    "amount",
    "total",
    "reported",
    "report",
    "according",
    "within",
    "shown",
    "outlined",
    "explicitly",
    "important",
    "primarily",
    "directly",
    "ongoing",
    "materially",
])

# Canonical stems for irregular/derivational forms so paraphrased question words
# (e.g. "retain" vs "retention", "geographies" vs "geographic") land on the same term.
_IRREGULAR_STEMS = {
    "retain": "retain",
    "retention": "retain",
    "retained": "retain",
    "proceed": "proceed",
    "proceeding": "proceed",
    "geographies": "geograph",
    "geographic": "geograph",
    "geography": "geograph",
    "customer": "customer",
    "customers": "customer",
    "client": "customer",
    "clients": "customer",
    "cardmember": "cardmember",
}

# Generic finance-domain concept expansions. Each entry maps a query concept to the
# document-side terms that commonly carry the same meaning in a 10-K. This is domain
# vocabulary, not tied to any single document or question.
_CONCEPT_EXPANSIONS = {
    "geograph": [
        "geograph",
        "segment",
        "region",
        "division",
        "international",
        "domestic",
        "united states",
        "emea",
        "apac",
        "latin america",
        "americas",
        "europe",
        "asia",
        "lacc",
    ],
    "legal": [
        "legal",
        "litigation",
        "proceeding",
        "lawsuit",
        "claim",
        "action",
        "settle",
        "court",
        "dispute",
        "contingent",
    ],
    "customer": ["customer", "client", "concentration", "airline", "government", "retention", "cardmember"],
    "concentration": ["concentration", "customer", "account", "revenue"],
    "margin": [
        "margin",
        "gross profit",
        "operating income",
        "operating profit",
        "profitability",
        "cost of sales",
        "cost of products",
        "cost of services",
    ],
    "capex": ["capital expenditure", "capital spending", "purchase", "property", "plant", "equipment"],
    "capital": ["capital expenditure", "capital spending", "purchase", "property", "plant", "equipment"],
    "ebitda": ["ebitda", "operating income", "depreciation", "amortization"],
    "tax": ["tax", "income tax", "provision", "effective rate", "tax rate"],
    "revenue": ["revenue", "sales", "income", "net revenue", "total revenue"],
    "liabilit": ["liabilit", "balance sheet", "debt", "obligation", "borrowing"],
    "segment": ["segment", "business", "product", "service", "division"],
    "gross": ["gross", "margin", "cost of sales", "cost of products", "cost of services", "gross profit"],
    "operating": ["operating", "income", "operating income", "operating profit", "margin"],
    "quick": ["quick", "current asset", "current liabilit", "cash", "inventory", "liquidity", "balance sheet"],
    "liquidity": ["liquidity", "quick", "current asset", "current liabilit", "cash", "balance sheet"],
}

# A question about a financial metric usually points at the core financial statements,
# even when the metric is paraphrased ("gross margin" -> income statement).
_METRIC_PATTERN = re.compile(
    r"margin|rate|ratio|income|revenue|expense|cost|profit|ebitda|tax|cash flow|balance sheet|"
    r"liabilit|asset|equity|debt|depreciation|amortization|operating|gross|net|liquidity"
)

# Statement headings (normalized, singular/plural collapsed) that answer metric questions.
_STATEMENT_HEAD_KEYS = (
    "consolidated statement of income",
    "consolidated statement of operation",
    "consolidated balance sheet",
    "consolidated statement of cash flow",
)
_INCOME_STATEMENT_KEYS = ("consolidated statement of income", "consolidated statement of operation")
_CASH_FLOW_KEYS = ("consolidated statement of cash flow",)

# A metric concept pins the question to a specific financial statement, even when
# the question paraphrases the metric ("gross margin" -> income statement).
_CONCEPT_STATEMENT_KEYS = {
    "margin": _INCOME_STATEMENT_KEYS,
    "gross": _INCOME_STATEMENT_KEYS,
    "operating": _INCOME_STATEMENT_KEYS,
    "ebitda": _INCOME_STATEMENT_KEYS,
    "quick": ("consolidated balance sheet",),
    "liquidity": ("consolidated balance sheet",),
    "liabilit": ("consolidated balance sheet",),
    "capex": _CASH_FLOW_KEYS,
    "capital": _CASH_FLOW_KEYS,
}

_BM25_K1 = 1.2
_BM25_B = 0.75
_HEADING_WEIGHT = 3.0
_STATEMENT_HINT_BOOST = 6.0
_METRIC_STATEMENT_BOOST = 4.0
_STEM_MAX_LENGTH = 7


class PDFDocumentInput(BaseModel):
    """Full offline PDF document to be parsed into per-page inputs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    content: bytes


class PDFPageInput(BaseModel):
    """One parsed PDF page ready to become a captured Source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    document_sha256: str
    page_number: int
    text: str


class PDFPageSource(Source):
    """Captured Source representing one physical PDF page."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    document_id: str
    document_sha256: str
    page_number: int
    text: str


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    """Parse a full PDF document into per-page inputs in physical-page order.

    Page numbers start at 1 and include blank pages. Raises ``ValueError`` on
    empty, non-PDF, corrupt, or otherwise unparseable input. Never returns
    partial results.
    """
    if not value.document_id.strip():
        raise ValueError("document_id must not be empty or whitespace")  # noqa: TRY003

    document_sha256 = hashlib.sha256(value.content).hexdigest()

    from pypdf import PdfReader

    try:
        reader = PdfReader(BytesIO(value.content), strict=False)
        if reader.is_encrypted:
            reader.decrypt("")

        pages: list[PDFPageInput] = []
        for index, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            pages.append(
                PDFPageInput(
                    document_id=value.document_id,
                    document_sha256=document_sha256,
                    page_number=index,
                    text=text,
                )
            )
    except Exception as exc:
        raise ValueError(f"could not parse PDF: {exc}") from exc  # noqa: TRY003

    return tuple(pages)


def pdf_page_source_id(document_id: str, document_sha256: str, page_number: int) -> str:
    """Compute a stable, collision-free identity for one PDF page Source."""
    raw = f"{document_id}\n{document_sha256}\n{page_number}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    encoded = f"pdf-page:{digest}"
    if len(encoded) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"source_id exceeds {MAX_SOURCE_ID_LENGTH} chars")  # noqa: TRY003
    return encoded


class PDFPageSourceAdapter:
    """Resolve and read PDF page Sources."""

    input_class = PDFPageInput
    name = PDF_PAGE_SOURCE_NAME
    source_class = PDFPageSource

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        source_id = pdf_page_source_id(value.document_id, value.document_sha256, value.page_number)
        return PDFPageSource(
            name=source_id,
            source_id=source_id,
            materialization=SourceMaterialization.CAPTURED,
            document_id=value.document_id,
            document_sha256=value.document_sha256,
            page_number=value.page_number,
            text=value.text,
        )

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return PDFPageInput(
            document_id=source.document_id,
            document_sha256=source.document_sha256,
            page_number=source.page_number,
            text=source.text,
        )


class PDFPageTextEvidenceProjection:
    """Project a PDF page Source as TextEvidence for Memory retrieval."""

    name = "powercontext.text-evidence"
    version = "1"
    source_class = PDFPageSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PDFPageSource, /) -> TextEvidence:
        content = f"{source.document_id}\n{source.text}"
        metadata: dict[str, JsonValue] = {
            "document_id": source.document_id,
            "document_sha256": source.document_sha256,
            "page_number": source.page_number,
        }
        return TextEvidence(
            source_type=PDF_PAGE_SOURCE_NAME,
            source_id=source.source_id,
            content=content,
            metadata=metadata,
        )


PDF_PAGE_SOURCE_ADAPTER = PDFPageSourceAdapter()
PDF_PAGE_SOURCE_DEFINITION: AdapterSourceDefinition[PDFPageInput, PDFPageSource, PDFPageInput] = (
    AdapterSourceDefinition(
        PDF_PAGE_SOURCE_ADAPTER,
        projections=(PDFPageTextEvidenceProjection(),),
    )
)


def _tokenize(value: str) -> list[str]:
    return _TOKEN_PATTERN.findall(value.lower())


def _stem(token: str) -> str:
    """Fold common English inflections and a few derivational forms to one key."""
    token = token.lower()
    canonical = _IRREGULAR_STEMS.get(token)
    if canonical is not None:
        return canonical
    if len(token) <= 3 or not token.isalpha():
        return token
    if token.endswith("ies") and len(token) > 4:
        token = token[:-3] + "y"
    elif token.endswith("ing") and len(token) > 5:
        token = token[:-3]
    elif (token.endswith("ed") and len(token) > 4) or (token.endswith("ly") and len(token) > 4):
        token = token[:-2]
    elif (
        (token.endswith("ment") and len(token) > 6)
        or (token.endswith("ness") and len(token) > 6)
        or (token.endswith("tion") and len(token) > 6)
        or (token.endswith("sion") and len(token) > 6)
        or (token.endswith("ance") and len(token) > 6)
        or (token.endswith("ence") and len(token) > 6)
    ):
        token = token[:-4]
    elif token.endswith("s") and not token.endswith(("ss", "us", "is")) and len(token) > 4:
        token = token[:-1]
    if len(token) > _STEM_MAX_LENGTH:
        token = token[:_STEM_MAX_LENGTH]
    return token


def _normalize_heading(line: str) -> str:
    line = re.sub(r"\bstatements\b", "statement", line)
    line = re.sub(r"\bsheets\b", "sheet", line)
    return re.sub(r"\s+", " ", line)


def _query_terms(  # noqa: C901
    question: str, document_frequency: Counter[str]
) -> tuple[list[str], list[str], bool]:
    """Extract query terms with finance-domain expansion and statement targets."""
    text = question.lower()
    target_keys: list[str] = []
    if re.search(r"balance sheet", text):
        target_keys.append("consolidated balance sheet")
    if re.search(r"income statement|p&l|p and l", text):
        target_keys.extend(_INCOME_STATEMENT_KEYS)
    if re.search(r"cash flow", text):
        target_keys.append("consolidated statement of cash flow")

    terms: list[str] = []
    for token in _tokenize(question):
        if token in _STOPWORDS or (len(token) == 1 and token.isalpha()):
            continue
        stemmed = _stem(token)
        if stemmed in terms:
            continue
        terms.append(stemmed)
        for expansion in _CONCEPT_EXPANSIONS.get(stemmed, ()):
            for word in expansion.split():
                expanded = _stem(word)
                if expanded not in terms and document_frequency.get(expanded, 0) > 0:
                    terms.append(expanded)
        for key in _CONCEPT_STATEMENT_KEYS.get(stemmed, ()):
            if key not in target_keys:
                target_keys.append(key)

    terms = [term for term in terms if document_frequency.get(term, 0) > 0]
    is_metric = bool(_METRIC_PATTERN.search(text))
    return terms, target_keys, is_metric


def _heading_tokens(text: str) -> tuple[Counter[str], str]:
    """Return heading-term bag and normalized heading text for a page body."""
    lines: list[str] = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line or line.lower() == _TABLE_OF_CONTENTS:
            continue
        if _HEADING_PATTERN.match(line):
            lines.append(_normalize_heading(line.lower()))
    return Counter(_stem(token) for token in _tokenize("\n".join(lines))), " ".join(lines)


async def search_pdf_pages(memory, question: str, limit: int = 10) -> tuple[MemoryCitation, ...]:
    """Search scoped Memory for PDF page evidence matching a question.

    Retrieval runs offline over the pages already materialized in the scoped
    Memory: the public ``list`` API supplies the candidate entries, then a
    deterministic BM25 ranking over page text, section headings, statement hints
    and a small finance-domain concept expansion picks the best ``limit`` distinct
    pages. Every returned citation is the real stored entry, so callers can ``get``
    it back to the exact page.
    """
    if limit <= 0:
        return ()

    listing = await memory.list()

    candidates: list[dict] = []
    seen_sources: set[str] = set()
    for record in listing.entries:
        entry = record.entry
        if not entry.sources:
            continue
        source_id = entry.sources[0].source_id
        if source_id in seen_sources:
            continue
        seen_sources.add(source_id)
        _, _, body = entry.text.partition("\n")
        headings, headtext = _heading_tokens(body)
        candidates.append({
            "citation": record.citation,
            "bag": Counter(_stem(token) for token in _tokenize(body)),
            "length": len(_tokenize(body)),
            "headings": headings,
            "headtext": headtext,
        })

    citations = _rank_citations(question, candidates)
    return tuple(citations[:limit])


def _rank_citations(question: str, candidates: list[dict]) -> list[MemoryCitation]:  # noqa: C901
    if not candidates:
        return []

    document_frequency: Counter[str] = Counter()
    for candidate in candidates:
        document_frequency.update(candidate["bag"].keys())
    average_length = sum(candidate["length"] for candidate in candidates) / len(candidates) or 1.0

    terms, target_keys, is_metric = _query_terms(question, document_frequency)
    if not terms:
        return [candidate["citation"] for candidate in candidates]

    total = len(candidates)
    scored: list[tuple[float, int]] = []
    for position, candidate in enumerate(candidates):
        score = 0.0
        bag = candidate["bag"]
        headings = candidate["headings"]
        for term in terms:
            frequency = document_frequency[term]
            idf = math.log((total - frequency + 0.5) / (frequency + 0.5) + 1.0)
            term_frequency = bag.get(term, 0)
            if term_frequency:
                norm = 1 - _BM25_B + _BM25_B * candidate["length"] / average_length
                score += idf * term_frequency * (_BM25_K1 + 1) / (term_frequency + _BM25_K1 * norm)
            if term in headings:
                score += _HEADING_WEIGHT * idf
        headtext = candidate["headtext"]
        for key in target_keys:
            if key in headtext:
                score += _STATEMENT_HINT_BOOST
        if is_metric:
            for key in _STATEMENT_HEAD_KEYS:
                if key in headtext:
                    score += _METRIC_STATEMENT_BOOST
                    break
        if score > 0:
            scored.append((score, position))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [candidates[position]["citation"] for _score, position in scored]


__all__ = [
    "PDF_PAGE_SOURCE_ADAPTER",
    "PDF_PAGE_SOURCE_DEFINITION",
    "PDF_PAGE_SOURCE_NAME",
    "PDFDocumentInput",
    "PDFPageInput",
    "PDFPageSource",
    "PDFPageSourceAdapter",
    "PDFPageTextEvidenceProjection",
    "parse_pdf_document",
    "pdf_page_source_id",
    "search_pdf_pages",
]
