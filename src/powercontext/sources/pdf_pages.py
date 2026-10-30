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
from io import BytesIO

from pydantic import BaseModel, ConfigDict, JsonValue

from powercontext.builtin.artifacts.memory.models import MemoryCitation
from powercontext.builtin.runtime import GetMemoryEntryRequest, SearchMemoryRequest
from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources import AdapterSourceDefinition, TextEvidence
from powercontext.sources.models import Source, SourceMaterialization

PDF_PAGE_SOURCE_NAME = "pdf-page"


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
    if not value.document_id or value.document_id != value.document_id.strip():
        raise ValueError("document_id must be non-empty without surrounding whitespace")  # noqa: TRY003

    document_sha256 = hashlib.sha256(value.content).hexdigest()

    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        reader = PdfReader(BytesIO(value.content), strict=False)
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:
                raise ValueError(f"encrypted PDF cannot be read: {exc}") from exc  # noqa: TRY003

        pages: list[PDFPageInput] = []
        for index, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception as exc:
                raise ValueError(f"page {index} text extraction failed: {exc}") from exc  # noqa: TRY003
            pages.append(
                PDFPageInput(
                    document_id=value.document_id,
                    document_sha256=document_sha256,
                    page_number=index,
                    text=text,
                )
            )
    except ValueError:
        raise
    except PdfReadError as exc:
        raise ValueError(f"invalid or corrupt PDF: {exc}") from exc  # noqa: TRY003
    except Exception as exc:
        raise ValueError(f"PDF parsing failed: {exc}") from exc  # noqa: TRY003

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


async def search_pdf_pages(memory, question: str, limit: int = 10) -> tuple[MemoryCitation, ...]:
    """Search scoped Memory for PDF page evidence matching a question.

    Returns up to ``limit`` distinct page-level citations. Each citation maps
    to exactly one physical page; duplicate pages are collapsed by their
    Source identity, which is determined by ``(document_id, document_sha256,
    page_number)``.
    """
    candidate_limit = max(limit * 4, 100)
    page = await memory.search(SearchMemoryRequest(query=question, mode="fts", limit=candidate_limit))

    citations: list[MemoryCitation] = []
    seen_sources: set[str] = set()

    for hit in page.hits:
        citation = MemoryCitation(
            memory_ref=hit.memory_ref,
            entry_id=hit.entry_id,
            entry_version_id=hit.entry_version_id,
        )
        entry_result = await memory.get(GetMemoryEntryRequest(citation=citation))
        entry = entry_result.entry
        if not entry.sources:
            continue
        source_id = entry.sources[0].source_id
        if source_id in seen_sources:
            continue
        seen_sources.add(source_id)
        citations.append(citation)
        if len(citations) >= limit:
            break

    return tuple(citations)


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
