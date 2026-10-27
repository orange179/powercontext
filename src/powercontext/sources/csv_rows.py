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

"""CSV row-level Source: parse offline CSV into per-row captured Sources."""

from __future__ import annotations

import csv
import io
import json
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, JsonValue

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources import AdapterSourceDefinition, TextEvidence
from powercontext.sources.models import Source, SourceMaterialization

CSV_ROW_SOURCE_NAME = "csv-row"


class CSVDocumentInput(BaseModel):
    """Full offline CSV document to be parsed into row-level inputs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    primary_key: str
    content: bytes


class CSVRowInput(BaseModel):
    """One parsed CSV row ready to become a captured Source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]


class CSVRowSource(Source):
    """Captured Source representing one CSV row with full field fidelity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]


def parse_csv_document(value: CSVDocumentInput) -> tuple[CSVRowInput, ...]:
    """Parse an offline CSV document into per-row inputs.

    Raises ``ValueError`` on any encoding, CSV format, or data validation
    error. Never returns partial results.
    """
    if not value.document_id or value.document_id != value.document_id.strip():
        raise ValueError("document_id must be non-empty without surrounding whitespace")
    if not value.primary_key:
        raise ValueError("primary_key must be non-empty")

    try:
        text = value.content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"CSV content is not valid UTF-8: {exc}") from exc

    if text.startswith("\ufeff"):
        text = text[1:]

    reader = csv.reader(io.StringIO(text), strict=True)

    rows: list[list[str]] = []
    try:
        for row in reader:
            rows.append(row)
    except csv.Error as exc:
        raise ValueError(f"Malformed CSV content: {exc}") from exc

    if not rows:
        raise ValueError("CSV document is empty")

    header = rows[0]
    if not header:
        raise ValueError("CSV header is empty")

    for i, col in enumerate(header):
        if not col or not col.strip():
            raise ValueError(f"Header column {i} is empty or blank")

    if len(set(header)) != len(header):
        raise ValueError("Header columns are not unique")

    if value.primary_key not in header:
        raise ValueError(f"primary_key {value.primary_key!r} not found in header")

    pk_index = header.index(value.primary_key)
    width = len(header)
    seen_pk: set[str] = set()
    result: list[CSVRowInput] = []

    for row in rows[1:]:
        if not row:
            continue

        if len(row) != width:
            raise ValueError(
                f"Row has {len(row)} fields, expected {width}"
            )

        pk_value = row[pk_index]
        if not pk_value or not pk_value.strip():
            raise ValueError("Primary key value must not be empty or blank")

        if pk_value in seen_pk:
            raise ValueError(f"Duplicate primary key value: {pk_value!r}")
        seen_pk.add(pk_value)

        result.append(
            CSVRowInput(
                document_id=value.document_id,
                primary_key=value.primary_key,
                primary_key_value=pk_value,
                columns=tuple(header),
                values=tuple(row),
            )
        )

    return tuple(result)


def csv_row_source_id(document_id: str, primary_key_value: str) -> str:
    """Compute the stable percent-encoded identity for one CSV row."""
    if not document_id or document_id != document_id.strip():
        raise ValueError("document_id must be non-empty without surrounding whitespace")
    encoded = (
        f"csv:{quote(document_id, safe='')}"
        f":{quote(primary_key_value, safe='')}"
    )
    if len(encoded) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(
            f"source_id length {len(encoded)} exceeds limit {MAX_SOURCE_ID_LENGTH}"
        )
    return encoded


class CSVRowSourceAdapter:
    """Resolve and read CSV row Sources."""

    input_class = CSVRowInput
    name = CSV_ROW_SOURCE_NAME
    source_class = CSVRowSource

    async def resolve(self, value: CSVRowInput, /) -> CSVRowSource:
        source_id = csv_row_source_id(value.document_id, value.primary_key_value)
        return CSVRowSource(
            name=source_id,
            source_id=source_id,
            materialization=SourceMaterialization.CAPTURED,
            document_id=value.document_id,
            primary_key=value.primary_key,
            primary_key_value=value.primary_key_value,
            columns=value.columns,
            values=value.values,
        )

    async def read(self, source: CSVRowSource, /) -> CSVRowInput:
        return CSVRowInput(
            document_id=source.document_id,
            primary_key=source.primary_key,
            primary_key_value=source.primary_key_value,
            columns=source.columns,
            values=source.values,
        )


class CSVRowTextEvidenceProjection:
    """Project a CSV row Source as TextEvidence for Memory retrieval."""

    name = "powercontext.text-evidence"
    version = "1"
    source_class = CSVRowSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: CSVRowSource, /) -> TextEvidence:
        row_dict: dict[str, str] = {}
        for col, val in zip(source.columns, source.values):
            row_dict[col] = val
        content = json.dumps(row_dict, ensure_ascii=False, separators=(",", ":"))
        metadata: dict[str, JsonValue] = {
            "document_id": source.document_id,
            "primary_key": source.primary_key,
            "primary_key_value": source.primary_key_value,
            "columns": list(source.columns),
            "row": row_dict,
        }
        return TextEvidence(
            source_type=CSV_ROW_SOURCE_NAME,
            source_id=source.source_id,
            content=content,
            metadata=metadata,
        )


CSV_ROW_SOURCE_ADAPTER = CSVRowSourceAdapter()
CSV_ROW_SOURCE_DEFINITION: AdapterSourceDefinition[
    CSVRowInput, CSVRowSource, CSVRowInput
] = AdapterSourceDefinition(
    CSV_ROW_SOURCE_ADAPTER,
    projections=(CSVRowTextEvidenceProjection(),),
)

__all__ = [
    "CSV_ROW_SOURCE_ADAPTER",
    "CSV_ROW_SOURCE_DEFINITION",
    "CSV_ROW_SOURCE_NAME",
    "CSVDocumentInput",
    "CSVRowInput",
    "CSVRowSource",
    "CSVRowSourceAdapter",
    "CSVRowTextEvidenceProjection",
    "csv_row_source_id",
    "parse_csv_document",
]
