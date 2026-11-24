"""Local ingestion for common tabular and business-report file formats."""
from __future__ import annotations

import csv
import json
import re
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from io import BytesIO, StringIO
from pathlib import Path, PurePosixPath
from typing import Iterable

import pandas as pd

from .uploaded import _numeric_values, parse_date_values

SUPPORTED_EXTENSIONS = {
    ".csv", ".tsv", ".txt", ".xlsx", ".xls", ".ods",
    ".json", ".jsonl", ".ndjson", ".parquet", ".pq", ".feather", ".arrow",
    ".html", ".htm", ".xml", ".pdf", ".docx", ".db", ".sqlite", ".sqlite3", ".zip",
}
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 2_000


@dataclass(frozen=True)
class DataTable:
    name: str
    source_name: str
    frame: pd.DataFrame


def _clean_frame(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    if frame.empty:
        return frame
    frame = frame.dropna(axis=0, how="all").dropna(axis=1, how="all").copy()
    frame.columns = [
        str(column).strip() if str(column).strip() else f"未命名列 {index + 1}"
        for index, column in enumerate(frame.columns)
    ]
    if not frame.empty and len(frame.columns):
        key_columns = [
            column for column in frame.columns
            if re.search(r"(?:^|[_\s-])(id|key|batch|order|product|sku)(?:$|[_\s-])", column, re.I)
        ]
        if key_columns:
            repeated_header = pd.Series(False, index=frame.index)
            for column in key_columns:
                repeated_header |= frame[column].astype("string").str.strip().str.casefold().eq(column.casefold())
            frame = frame.loc[~repeated_header].copy()
    return frame.reset_index(drop=True)


def _csv_frames(data: bytes, suffix: str) -> list[tuple[str, pd.DataFrame]]:
    errors = []
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "cp1252"):
        try:
            text = data.decode(encoding)
            delimiter = "\t" if suffix == ".tsv" else _detect_delimiter(text)
            frame = pd.read_csv(
                StringIO(text),
                sep=delimiter,
                engine="python",
            )
            return [("", frame)]
        except (UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
            errors.append(str(exc))
    raise ValueError(f"Unable to parse delimited text: {errors[-1]}")


def _detect_delimiter(text: str) -> str | None:
    sample = [line for line in text.splitlines()[:30] if line.strip()]
    best_delimiter, best_score = None, (0.0, 0, 0.0)
    for delimiter in (",", "|", "\t", ";"):
        counts = [len(next(csv.reader([line], delimiter=delimiter))) for line in sample]
        if not counts:
            continue
        columns = max(set(counts), key=counts.count)
        if columns < 2:
            continue
        consistency = counts.count(columns) / len(counts)
        average_columns = sum(counts) / len(counts)
        score = (consistency, columns, average_columns)
        if score > best_score:
            best_delimiter, best_score = delimiter, score
    return best_delimiter


def _json_frames(data: bytes, suffix: str) -> list[tuple[str, pd.DataFrame]]:
    if suffix in (".jsonl", ".ndjson"):
        return [("", pd.read_json(BytesIO(data), lines=True))]
    try:
        decoded = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc
    if isinstance(decoded, list):
        return [("", pd.json_normalize(decoded))]
    if isinstance(decoded, dict):
        record_lists = [
            (key, value) for key, value in decoded.items()
            if isinstance(value, list) and value and all(isinstance(item, dict) for item in value)
        ]
        if record_lists:
            key, records = max(record_lists, key=lambda item: len(item[1]))
            return [(key, pd.json_normalize(records))]
        return [("", pd.json_normalize([decoded]))]
    raise ValueError("JSON root must be an object or an array of records.")


def _sqlite_frames(data: bytes, source_name: str) -> list[tuple[str, pd.DataFrame]]:
    with tempfile.NamedTemporaryFile(suffix=Path(source_name).suffix) as file:
        file.write(data)
        file.flush()
        connection = sqlite3.connect(f"{Path(file.name).as_uri()}?mode=ro", uri=True)
        try:
            names = [
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            ]
            frames = []
            for name in names:
                escaped = name.replace('"', '""')
                frames.append((name, pd.read_sql_query(f'SELECT * FROM "{escaped}"', connection)))
            return frames
        finally:
            connection.close()


def _pdf_frames(data: bytes) -> list[tuple[str, pd.DataFrame]]:
    try:
        import pdfplumber
    except ImportError as exc:
        raise ValueError("PDF table import requires pdfplumber; reinstall the project dependencies.") from exc
    frames = []
    with pdfplumber.open(BytesIO(data)) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            for table_number, rows in enumerate(page.extract_tables() or [], start=1):
                if len(rows) < 2:
                    continue
                header = [str(value or "").strip() or f"未命名列 {index + 1}" for index, value in enumerate(rows[0])]
                frame = pd.DataFrame(rows[1:], columns=header)
                frames.append((f"第 {page_number} 页表格 {table_number}", frame))
    if not frames:
        raise ValueError("No text tables found in this PDF. Scanned/image-only PDFs need OCR before import.")
    return frames


def _docx_frames(data: bytes) -> list[tuple[str, pd.DataFrame]]:
    try:
        from docx import Document
    except ImportError as exc:
        raise ValueError("Word table import requires python-docx; reinstall the project dependencies.") from exc
    document = Document(BytesIO(data))
    frames = []
    for table_number, table in enumerate(document.tables, start=1):
        rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
        if len(rows) >= 2:
            frames.append((f"表格 {table_number}", pd.DataFrame(rows[1:], columns=rows[0])))
    if not frames:
        raise ValueError("No tables found in this Word document.")
    return frames


def _read_file(name: str, data: bytes, depth: int = 0) -> tuple[list[DataTable], list[str]]:
    suffix = Path(name).suffix.lower()
    if Path(name).name.startswith(".") or "__MACOSX" in PurePosixPath(name).parts:
        return [], []
    if len(data) > MAX_FILE_BYTES:
        return [], [f"{name}: file exceeds the 512 MB per-file safety limit."]
    if suffix == ".zip":
        if depth >= 3:
            return [], [f"{name}: nested archive depth exceeds the limit."]
        try:
            archive = zipfile.ZipFile(BytesIO(data))
        except zipfile.BadZipFile:
            return [], [f"{name}: invalid ZIP archive."]
        infos = [info for info in archive.infolist() if not info.is_dir()]
        if len(infos) > MAX_ARCHIVE_MEMBERS or sum(info.file_size for info in infos) > MAX_ARCHIVE_BYTES:
            return [], [f"{name}: archive exceeds the file-count or expanded-size limit."]
        tables, warnings = [], []
        with archive:
            for info in infos:
                member_path = PurePosixPath(info.filename)
                if member_path.is_absolute() or ".." in member_path.parts:
                    warnings.append(f"{name}: ignored unsafe archive path {info.filename}.")
                    continue
                member = member_path.as_posix()
                if Path(member).suffix.lower() not in SUPPORTED_EXTENSIONS - {".zip"} and not member.endswith(".zip"):
                    warnings.append(f"{member}: unsupported file format; skipped.")
                    continue
                parsed, notes = _read_file(f"{Path(name).stem}/{member}", archive.read(info), depth + 1)
                tables.extend(parsed)
                warnings.extend(notes)
        return tables, warnings

    try:
        if suffix in (".csv", ".tsv", ".txt"):
            frames = _csv_frames(data, suffix)
        elif suffix in (".json", ".jsonl", ".ndjson"):
            frames = _json_frames(data, suffix)
        elif suffix in (".xlsx", ".xls", ".ods"):
            frames = list(pd.read_excel(BytesIO(data), sheet_name=None).items())
        elif suffix in (".parquet", ".pq"):
            frames = [("", pd.read_parquet(BytesIO(data)))]
        elif suffix in (".feather", ".arrow"):
            frames = [("", pd.read_feather(BytesIO(data)))]
        elif suffix in (".html", ".htm"):
            text = data.decode("utf-8", errors="replace")
            frames = [(f"HTML 表格 {index + 1}", frame) for index, frame in enumerate(pd.read_html(StringIO(text)))]
        elif suffix == ".xml":
            frames = [("", pd.read_xml(BytesIO(data)))]
        elif suffix == ".pdf":
            frames = _pdf_frames(data)
        elif suffix == ".docx":
            frames = _docx_frames(data)
        elif suffix in (".db", ".sqlite", ".sqlite3"):
            frames = _sqlite_frames(data, name)
        else:
            return [], [f"{name}: unsupported format; skipped."]
    except (
        ValueError,
        ImportError,
        OSError,
        KeyError,
        sqlite3.Error,
        zipfile.BadZipFile,
        pd.errors.ParserError,
    ) as exc:
        return [], [f"{name}: {exc}"]

    tables = []
    for suffix_name, frame in frames:
        frame = _clean_frame(frame, name)
        if frame.empty or not len(frame.columns):
            continue
        table_name = name if not suffix_name else f"{name} · {suffix_name}"
        tables.append(DataTable(table_name, name, frame))
    if not tables:
        return [], [f"{name}: no tabular rows found."]
    return tables, []


def read_uploaded_datasets(files: Iterable[tuple[str, bytes]]) -> tuple[list[DataTable], list[str]]:
    """Parse multiple uploaded files, folder contents, and ZIP members without extracting to disk."""
    tables, warnings = [], []
    total_bytes = 0
    for name, data in files:
        total_bytes += len(data)
        if total_bytes > MAX_ARCHIVE_BYTES:
            warnings.append("Total uploaded data exceeds the 2 GB processing limit; remaining files were skipped.")
            break
        parsed, notes = _read_file(name, data)
        tables.extend(parsed)
        warnings.extend(notes)
    return tables, warnings


def _is_metadata(table: DataTable) -> bool:
    columns = {re.sub(r"[^a-z]", "", str(column).lower()) for column in table.frame.columns}
    filename = Path(table.source_name).stem.lower()
    return "metadata" in filename or "dictionary" in filename or {"table", "field", "description"}.issubset(columns)


def _date_columns(frame: pd.DataFrame) -> list[str]:
    return [
        column for column in frame.columns
        if (parsed := parse_date_values(frame[column], str(column))).notna().mean() >= 0.8
        and parsed.notna().any()
    ]


def date_tables(tables: list[DataTable]) -> list[DataTable]:
    """Return non-dictionary tables that contain at least one usable date column."""
    return [table for table in tables if not _is_metadata(table) and _date_columns(table.frame)]


def _join_key_candidates(left: pd.DataFrame, right: pd.DataFrame) -> list[tuple[str, str]]:
    common = []
    key_words = ("id", "batch", "product", "sku", "order", "customer", "machine", "line", "serial")
    for left_column in left.columns:
        normalized_left = re.sub(r"[^a-z0-9]", "", str(left_column).lower())
        if not any(word in normalized_left for word in key_words):
            continue
        for right_column in right.columns:
            if normalized_left == re.sub(r"[^a-z0-9]", "", str(right_column).lower()):
                common.append((left_column, right_column))
    return common


def _matching_ratio(left: pd.Series, right: pd.Series) -> float:
    left_values = set(left.dropna().astype("string").str.strip())
    right_values = set(right.dropna().astype("string").str.strip())
    if not left_values or not right_values:
        return 0
    return len(left_values & right_values) / min(len(left_values), len(right_values))


def _add_derived_metrics(frame: pd.DataFrame, source_name: str) -> pd.DataFrame:
    result = frame.copy()
    lowered = {str(column).lower(): column for column in result.columns}
    batch_column = next((column for column in result.columns if "batch" in str(column).lower()), None)
    if batch_column is not None and _date_columns(result):
        result["Record count"] = 1

    start_column = next((column for column in result.columns if "start" in str(column).lower() and "time" in str(column).lower()), None)
    end_column = next((column for column in result.columns if "end" in str(column).lower() and "time" in str(column).lower()), None)
    if start_column is not None and end_column is not None:
        time_pattern = re.compile(r"(\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?)")
        start = result[start_column].astype("string").str.extract(time_pattern, expand=False)
        end = result[end_column].astype("string").str.extract(time_pattern, expand=False)
        start_seconds = pd.to_timedelta(start, errors="coerce").dt.total_seconds()
        end_seconds = pd.to_timedelta(end, errors="coerce").dt.total_seconds()
        duration = (end_seconds - start_seconds).mod(24 * 60 * 60) / 60
        if duration.notna().any():
            result["Batch duration (min)"] = duration

    if "downtime" in Path(source_name).stem.lower():
        factor_columns = [
            column for column in result.columns
            if column != batch_column and _numeric_values(result[column]).notna().any()
        ]
        if factor_columns:
            factor_values = pd.DataFrame({
                column: _numeric_values(result[column]) for column in factor_columns
            })
            result["Total downtime (min)"] = factor_values.sum(axis=1, min_count=1)
    return result


def combine_related_tables(
    tables: list[DataTable],
    primary_name: str,
) -> tuple[pd.DataFrame, list[str]]:
    """Join related fact/dimension tables to a date-bearing table using shared identifier keys."""
    primary = next((table for table in tables if table.name == primary_name), None)
    if primary is None:
        raise ValueError(f"Selected data table not found: {primary_name}")
    frame = _add_derived_metrics(primary.frame, primary.source_name)
    notes = []
    for table in tables:
        if table.name == primary.name or _is_metadata(table):
            continue
        other = _add_derived_metrics(table.frame, table.source_name)
        candidates = sorted(
            _join_key_candidates(frame, other),
            key=lambda keys: _matching_ratio(frame[keys[0]], other[keys[1]]),
            reverse=True,
        )
        if not candidates or _matching_ratio(frame[candidates[0][0]], other[candidates[0][1]]) < 0.5:
            continue
        left_key, right_key = candidates[0]
        duplicate_suffix = Path(table.source_name).stem
        right = other.copy()
        right["__report_join_key"] = right[right_key].astype("string").str.strip()
        payload_columns = [column for column in right.columns if column not in (right_key, "__report_join_key")]
        if right["__report_join_key"].duplicated().any():
            grouped = right.groupby("__report_join_key", dropna=False, sort=False)
            pieces = []
            for column in payload_columns:
                values = _numeric_values(right[column])
                if values.notna().any():
                    pieces.append(values.groupby(right["__report_join_key"], sort=False).sum(min_count=1).rename(column))
                else:
                    pieces.append(right.groupby("__report_join_key", sort=False)[column].first())
            right = pd.concat(pieces, axis=1).reset_index()
        rename = {
            column: f"{duplicate_suffix} — {column}"
            for column in right.columns
            if column not in (right_key, "__report_join_key")
        }
        right = right.rename(columns=rename)
        left = frame.copy()
        left["__report_join_key"] = left[left_key].astype("string").str.strip()
        columns = ["__report_join_key", *rename.values()]
        merged = left.merge(right[columns], on="__report_join_key", how="left", sort=False)
        frame = merged.drop(columns="__report_join_key")
        notes.append(f"已按 {left_key} 自动关联 {table.name}")

    if "Record count" not in frame.columns and _date_columns(frame):
        frame["Record count"] = 1
    if "Batch duration (min)" not in frame.columns:
        start_column = next((column for column in frame.columns if "start time" in str(column).lower()), None)
        end_column = next((column for column in frame.columns if "end time" in str(column).lower()), None)
        if start_column and end_column:
            frame = _add_derived_metrics(frame, primary.source_name)
    if not notes:
        notes.append("没有找到可安全自动关联的共同业务编号；仅使用所选数据表。")
    return frame, notes
