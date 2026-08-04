"""Peewee-backed SQLite read model for Olive's WPT review application."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from peewee import BooleanField, FloatField, Model, SqliteDatabase, TextField


VALID_STATUSES = {"PASS", "FAIL", "REVW", "UNKN", "NONE"}
ROW_FIELDS = (
    "path", "status", "wpt_url", "output_directory",
    "result_exists", "reference_exists", "metadata_status",
    "approved_result_sha256", "review_state", "review_reason",
    "wpt_passed", "run_passed", "run_outcome", "current_diff_percent",
    "metadata_json", "review_state_json",
    "current_json", "updated_at",
)


class WptTestRecord(Model):
    path = TextField(primary_key=True)
    status = TextField()
    wpt_url = TextField()
    output_directory = TextField()
    result_exists = BooleanField()
    reference_exists = BooleanField()
    metadata_status = TextField(null=True)
    approved_result_sha256 = TextField(null=True)
    review_state = TextField(null=True)
    review_reason = TextField(null=True)
    wpt_passed = BooleanField(null=True)
    run_passed = BooleanField(null=True)
    run_outcome = TextField(null=True)
    current_diff_percent = FloatField(null=True)
    metadata_json = TextField(null=True)
    review_state_json = TextField(null=True)
    current_json = TextField(null=True)
    updated_at = TextField()

    class Meta:
        table_name = "wpt_tests"
        indexes = ((('status',), False),)


def bind_database(database_path: Path) -> SqliteDatabase:
    database = SqliteDatabase(database_path, pragmas={"foreign_keys": 1, "journal_mode": "wal"})
    WptTestRecord.bind(database, bind_refs=False, bind_backrefs=False)
    return database


def open_database(database_path: Path) -> SqliteDatabase:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    database = bind_database(database_path)
    database.connect(reuse_if_open=True)
    database.create_tables([WptTestRecord])
    return database


def output_directory(project_root: Path, wpt_path: str) -> Path:
    source = PurePosixPath(wpt_path)
    suffix = source.suffix.removeprefix(".")
    stem = source.name[: -(len(suffix) + 1)] if suffix else source.name
    directory_name = f"{stem}-{suffix}-test" if suffix else f"{stem}-test"
    return project_root / "outputs" / source.parent / directory_name


def load_paths(path: Path) -> tuple[str, ...]:
    paths = []
    seen = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.split("#", 1)[0].strip()
        if not value:
            continue
        candidate = PurePosixPath(value)
        if candidate.is_absolute() or ".." in candidate.parts or "\\" in value:
            raise ValueError(f"unsafe WPT path: {value}")
        normalized = candidate.as_posix()
        if normalized in seen:
            raise ValueError(f"duplicate WPT path: {normalized}")
        seen.add(normalized)
        paths.append(normalized)
    return tuple(sorted(paths))


def read_json(path: Path) -> tuple[str | None, dict[str, object] | None]:
    if not path.is_file():
        return None, None
    text = path.read_text(encoding="utf-8")
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return text, value


def result_hash(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def derive_status(result_path: Path, metadata, review_state, current) -> str:
    current_hash = result_hash(result_path)
    if current_hash is None:
        return "NONE"
    if review_state is not None:
        return "FAIL" if review_state.get("olive_result_sha256") == current_hash else "REVW"
    if current and current.get("run_passed") is False:
        return "FAIL"
    if metadata and metadata.get("status") == "approved":
        return "PASS" if metadata.get("approved_result_sha256") == current_hash else "REVW"
    return "UNKN"


def row_for_test(project_root: Path, path: str, status=None) -> dict[str, object]:
    directory = output_directory(project_root, path)
    result_path = directory / "result.png"
    reference_path = directory / "reference.png"
    metadata_text, metadata = read_json(directory / "metadata.json")
    review_text, review_state = read_json(directory / "review-state.json")
    current_text, current = read_json(directory / "current.json")
    status = status or derive_status(result_path, metadata, review_state, current)
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid WPT status for {path}: {status}")
    return {
        "path": path,
        "status": status,
        "wpt_url": f"https://wpt.live/{quote(path, safe='/')}",
        "output_directory": str(directory.relative_to(project_root)),
        "result_exists": result_path.is_file(),
        "reference_exists": reference_path.is_file(),
        "metadata_status": metadata.get("status") if metadata else None,
        "approved_result_sha256": metadata.get("approved_result_sha256") if metadata else None,
        "review_state": review_state.get("state") if review_state else None,
        "review_reason": review_state.get("reason") if review_state else None,
        "wpt_passed": current.get("wpt_passed") if current and isinstance(current.get("wpt_passed"), bool) else None,
        "run_passed": current.get("run_passed") if current and isinstance(current.get("run_passed"), bool) else None,
        "run_outcome": current.get("run_outcome") if current and isinstance(current.get("run_outcome"), str) else None,
        "current_diff_percent": current.get("current_diff_percent") if current else None,
        "metadata_json": metadata_text,
        "review_state_json": review_text,
        "current_json": current_text,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def insert_row(row: dict[str, object]) -> None:
    WptTestRecord.replace(**{field: row[field] for field in ROW_FIELDS}).execute()


def rebuild_database(project_root: Path) -> int:
    database_path = project_root / "data.sqlite"
    temporary_path = project_root / ".data.sqlite.tmp"
    if temporary_path.exists():
        temporary_path.unlink()
    paths = load_paths(project_root / "wpt_paths.txt")
    database = open_database(temporary_path)
    try:
        with database.atomic():
            for path in paths:
                insert_row(row_for_test(project_root, path))
    finally:
        database.close()
    os.replace(temporary_path, database_path)
    return len(paths)


def upsert_test(project_root: Path, path: str, status: str) -> None:
    database = open_database(project_root / "data.sqlite")
    try:
        with database.atomic():
            insert_row(row_for_test(project_root, path, status))
    finally:
        database.close()


def load_statuses(database_path: Path) -> dict[str, str]:
    if not database_path.is_file():
        raise FileNotFoundError(database_path)
    database = open_database(database_path)
    try:
        return {record.path: record.status for record in WptTestRecord.select()}
    finally:
        database.close()
