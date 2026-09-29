#!/usr/bin/env python3
"""Maintain a local transcript cache for call recordings stored in Notes.

This worker reads Apple's stores only through ``notes.py``. It never writes to
Notes and never creates semantic work. Its only durable state is a source-local
transcript cache and retry metadata.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import notes as source  # noqa: E402


STATE_ROOT = Path(
    os.environ.get(
        "NOTES_TRANSCRIPTIONS_ROOT",
        Path.home() / "Library/Application Support/notes/transcriptions",
    )
)
DEFAULT_LIMIT = 10
MAX_RETRY_DELAY_SECONDS = 3600
ELEVENLABS_MODEL = "scribe_v2"


class TranscriptionWorkerError(RuntimeError):
    pass


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat(timespec="seconds")


def _parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _database_path() -> Path:
    return STATE_ROOT / "cache.sqlite3"


def _transcript_dir() -> Path:
    return STATE_ROOT / "transcripts"


def _lock_dir() -> Path:
    return STATE_ROOT / "locks"


def _receipt_path() -> Path:
    return STATE_ROOT / "last-run.json"


def _ensure_private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass


def _connection() -> sqlite3.Connection:
    _ensure_private_directory(STATE_ROOT)
    con = sqlite3.connect(_database_path(), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS transcription_items (
            source_id TEXT PRIMARY KEY,
            source_revision TEXT,
            source_path TEXT,
            source_time TEXT,
            source_title TEXT,
            state TEXT NOT NULL CHECK (state IN ('baseline', 'completed', 'failed')),
            transcript_path TEXT,
            provider TEXT,
            model TEXT,
            response_format TEXT,
            diarized INTEGER,
            transcript_sha256 TEXT,
            completion_sequence INTEGER,
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            next_retry_at TEXT,
            completed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS transcription_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    columns = {row[1] for row in con.execute("PRAGMA table_info(transcription_items)")}
    for name, declaration in (
        ("source_time", "TEXT"),
        ("source_title", "TEXT"),
        ("completed_at", "TEXT"),
        ("completion_sequence", "INTEGER"),
    ):
        if name not in columns:
            con.execute(f"ALTER TABLE transcription_items ADD COLUMN {name} {declaration}")
    next_sequence = con.execute(
        "SELECT COALESCE(MAX(completion_sequence), 0) FROM transcription_items"
    ).fetchone()[0]
    for row in con.execute(
        """
        SELECT source_id FROM transcription_items
        WHERE state = 'completed' AND completion_sequence IS NULL
        ORDER BY completed_at, source_id
        """
    ):
        next_sequence += 1
        con.execute(
            "UPDATE transcription_items SET completion_sequence = ? WHERE source_id = ?",
            (next_sequence, row["source_id"]),
        )
    con.commit()
    return con


@contextlib.contextmanager
def _open_connection():
    con = _connection()
    try:
        yield con
    finally:
        con.close()


def _safe_name(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in value)
    return safe[:160] or hashlib.sha256(value.encode("utf-8")).hexdigest()


def _item_id(call: dict) -> str:
    value = str(call.get("id") or "").strip()
    if not value:
        raise TranscriptionWorkerError("Notes returned a call without a stable attachment UUID")
    return value


def _item_path(call: dict) -> Path:
    value = call.get("path")
    if not value:
        raise TranscriptionWorkerError(f"call {_item_id(call)} has no materialized audio path")
    return Path(str(value))


def _item_time(call: dict) -> str | None:
    value = call.get("started_at")
    return str(value) if value else None


def _item_title(call: dict) -> str | None:
    value = call.get("title")
    return str(value) if value else None


def _source_revision(call: dict, audio_path: Path | None) -> str:
    size = None
    if audio_path is not None:
        try:
            size = audio_path.stat().st_size
        except OSError:
            pass
    payload = {
        "source_id": _item_id(call),
        "started_at": call.get("started_at"),
        # A source path or sync mtime may change while the stable attachment
        # UUID still identifies the same recording.  Size catches normal trim
        # edits without turning a rename or iCloud rematerialization into paid
        # duplicate work.
        "size": size,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _transcript_path(source_id: str) -> Path:
    return _transcript_dir() / f"{_safe_name(source_id)}.txt"


def _atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    _ensure_private_directory(path.parent)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


@contextlib.contextmanager
def _item_lock(source_id: str):
    _ensure_private_directory(_lock_dir())
    identity = hashlib.sha256(source_id.encode("utf-8")).hexdigest()
    lock_path = _lock_dir() / f"{identity}.lock"
    with lock_path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _row(source_id: str) -> sqlite3.Row | None:
    with _open_connection() as con:
        return con.execute(
            "SELECT * FROM transcription_items WHERE source_id = ?", (source_id,)
        ).fetchone()


def _row_dict(row: sqlite3.Row) -> dict:
    result = dict(row)
    result["diarized"] = bool(result["diarized"]) if result["diarized"] is not None else None
    result["uuid"] = result["source_id"]
    result["title"] = result["source_title"]
    result["call_started_at"] = result["source_time"]
    return result


def _cached(row: sqlite3.Row | None, revision: str) -> bool:
    if row is None or row["state"] != "completed" or row["source_revision"] != revision:
        return False
    transcript_path = row["transcript_path"]
    if not transcript_path or not row["transcript_sha256"]:
        return False
    try:
        content = Path(transcript_path).read_bytes()
    except OSError:
        return False
    return bool(
        content
        and hashlib.sha256(content).hexdigest() == row["transcript_sha256"]
    )


def _retry_is_due(row: sqlite3.Row | None, revision: str, *, force: bool) -> bool:
    if force or row is None or row["state"] != "failed":
        return True
    if row["source_revision"] != revision:
        return True
    next_retry = _parse_time(row["next_retry_at"])
    return next_retry is None or _now() >= next_retry


def _record_failure(
    source_id: str,
    revision: str,
    audio_path: Path | None,
    error: Exception,
    *,
    source_time: str | None,
    source_title: str | None,
) -> dict:
    now = _now()
    with _open_connection() as con:
        existing = con.execute(
            "SELECT state, source_revision, attempts, created_at FROM transcription_items WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        same_failure = bool(
            existing
            and existing["state"] == "failed"
            and existing["source_revision"] == revision
        )
        attempts = int(existing["attempts"] or 0) + 1 if same_failure else 1
        delay = min(60 * (2 ** (attempts - 1)), MAX_RETRY_DELAY_SECONDS)
        next_retry = now + dt.timedelta(seconds=delay)
        created_at = existing["created_at"] if existing else _iso(now)
        con.execute(
            """
            INSERT INTO transcription_items (
                source_id, source_revision, source_path, source_time, source_title,
                state, attempts,
                last_error, next_retry_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'failed', ?, ?, ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
                source_revision = excluded.source_revision,
                source_path = excluded.source_path,
                source_time = excluded.source_time,
                source_title = excluded.source_title,
                state = 'failed',
                transcript_path = NULL,
                provider = NULL,
                model = NULL,
                response_format = NULL,
                diarized = NULL,
                transcript_sha256 = NULL,
                completion_sequence = NULL,
                attempts = excluded.attempts,
                last_error = excluded.last_error,
                next_retry_at = excluded.next_retry_at,
                completed_at = NULL,
                updated_at = excluded.updated_at
            """,
            (
                source_id,
                revision,
                str(audio_path) if audio_path is not None else None,
                source_time,
                source_title,
                attempts,
                str(error)[:4000],
                _iso(next_retry),
                created_at,
                _iso(now),
            ),
        )
        con.commit()
    return {
        "source_id": source_id,
        "state": "failed",
        "attempts": attempts,
        "next_retry_at": _iso(next_retry),
        "error": str(error),
        "attempted": True,
    }


def _mark_completed(
    source_id: str,
    revision: str,
    audio_path: Path | None,
    transcript: str,
    *,
    source_time: str | None,
    source_title: str | None,
    provider: str,
    model: str | None,
    response_format: str,
    diarized: bool,
) -> dict:
    if not transcript.strip():
        raise TranscriptionWorkerError(f"transcription for {source_id} was empty")
    path = _transcript_path(source_id)
    encoded = transcript.encode("utf-8")
    _atomic_write(path, encoded)
    now = _iso(_now())
    with _open_connection() as con:
        con.execute("BEGIN IMMEDIATE")
        existing = con.execute(
            "SELECT created_at FROM transcription_items WHERE source_id = ?", (source_id,)
        ).fetchone()
        created_at = existing["created_at"] if existing else now
        completion_sequence = con.execute(
            "SELECT COALESCE(MAX(completion_sequence), 0) + 1 FROM transcription_items"
        ).fetchone()[0]
        con.execute(
            """
            INSERT INTO transcription_items (
                source_id, source_revision, source_path, source_time, source_title,
                state, transcript_path,
                provider, model, response_format, diarized, transcript_sha256,
                completion_sequence, attempts, last_error, next_retry_at,
                completed_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'completed', ?, ?, ?, ?, ?, ?, ?, 0, NULL, NULL, ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
                source_revision = excluded.source_revision,
                source_path = excluded.source_path,
                source_time = excluded.source_time,
                source_title = excluded.source_title,
                state = 'completed',
                transcript_path = excluded.transcript_path,
                provider = excluded.provider,
                model = excluded.model,
                response_format = excluded.response_format,
                diarized = excluded.diarized,
                transcript_sha256 = excluded.transcript_sha256,
                completion_sequence = excluded.completion_sequence,
                attempts = 0,
                last_error = NULL,
                next_retry_at = NULL,
                completed_at = excluded.completed_at,
                updated_at = excluded.updated_at
            """,
            (
                source_id,
                revision,
                str(audio_path) if audio_path is not None else None,
                source_time,
                source_title,
                str(path),
                provider,
                model,
                response_format,
                int(diarized),
                hashlib.sha256(encoded).hexdigest(),
                completion_sequence,
                now,
                created_at,
                now,
            ),
        )
        con.commit()
    return {
        "source_id": source_id,
        "state": "completed",
        "provider": provider,
        "model": model,
        "response_format": response_format,
        "diarized": diarized,
        "transcript_path": str(path),
        "attempted": True,
    }


def _elevenlabs_transcribe(audio_path: Path) -> str:
    cli = shutil.which("elevenlabs")
    if not cli:
        raise TranscriptionWorkerError("the elevenlabs CLI was not found on PATH")
    _ensure_private_directory(STATE_ROOT / "tmp")
    with tempfile.TemporaryDirectory(dir=STATE_ROOT / "tmp") as temporary:
        output_path = Path(temporary) / "transcript.txt"
        command = [
            cli,
            "transcribe",
            str(audio_path),
            "--model",
            ELEVENLABS_MODEL,
            "--response-format",
            "diarized_text",
            "--diarize",
            "--out",
            str(output_path),
            "--timeout-seconds",
            "1800",
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=1830,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise TranscriptionWorkerError("ElevenLabs transcription timed out") from exc
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
            raise TranscriptionWorkerError(f"ElevenLabs transcription failed: {detail[-2000:]}")
        try:
            return output_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise TranscriptionWorkerError(
                "ElevenLabs completed without a readable transcript artifact"
            ) from exc


def process_call(
    call: dict,
    *,
    retry_failed: bool = False,
    include_baseline: bool = False,
    refresh: bool = False,
) -> dict:
    source_id = _item_id(call)
    path_value = call.get("path")
    audio_path = Path(str(path_value)) if path_value else None
    revision = _source_revision(call, audio_path)

    with _item_lock(source_id):
        row = _row(source_id)
        if row is not None and row["state"] == "baseline" and not include_baseline:
            return {"source_id": source_id, "state": "baseline", "attempted": False}
        if not refresh and _cached(row, revision):
            return {
                "source_id": source_id,
                "state": "cached",
                "provider": row["provider"],
                "transcript_path": row["transcript_path"],
                "attempted": False,
            }
        if not _retry_is_due(row, revision, force=retry_failed):
            return {
                "source_id": source_id,
                "state": "deferred",
                "next_retry_at": row["next_retry_at"],
                "attempted": False,
            }

        try:
            apple = source.apple_transcript(call).strip()
            if apple:
                return _mark_completed(
                    source_id,
                    revision,
                    audio_path,
                    apple + ("\n" if not apple.endswith("\n") else ""),
                    source_time=_item_time(call),
                    source_title=_item_title(call),
                    provider="apple",
                    model=None,
                    response_format="text",
                    diarized=False,
                )
            audio_path = _item_path(call)
            revision = _source_revision(call, audio_path)
            if not audio_path.is_file():
                raise TranscriptionWorkerError(f"audio is not materialized at {audio_path}")
            transcript = _elevenlabs_transcribe(audio_path)
            return _mark_completed(
                source_id,
                revision,
                audio_path,
                transcript,
                source_time=_item_time(call),
                source_title=_item_title(call),
                provider="elevenlabs",
                model=ELEVENLABS_MODEL,
                response_format="diarized_text",
                diarized=True,
            )
        except Exception as exc:
            return _record_failure(
                source_id,
                revision,
                audio_path,
                exc,
                source_time=_item_time(call),
                source_title=_item_title(call),
            )


def reconcile(*, limit: int = DEFAULT_LIMIT, retry_failed: bool = False) -> dict:
    if limit < 1:
        raise TranscriptionWorkerError("limit must be at least one")
    calls = source.read_calls()
    counts = {"completed": 0, "cached": 0, "baseline": 0, "deferred": 0, "failed": 0}
    changed: list[dict] = []
    attempts = 0
    for call in calls:
        if attempts >= limit:
            break
        result = process_call(call, retry_failed=retry_failed)
        state = result["state"]
        counts[state] = counts.get(state, 0) + 1
        if result.get("attempted"):
            attempts += 1
            changed.append({key: value for key, value in result.items() if key != "attempted"})
    return {
        "source": "notes",
        "source_count": len(calls),
        "attempted": attempts,
        "counts": counts,
        "items": changed,
        "cache_path": str(_database_path()),
    }


def baseline_current() -> dict:
    calls = source.read_calls()
    now = _iso(_now())
    inserted = 0
    with _open_connection() as con:
        for call in calls:
            source_id = _item_id(call)
            path_value = call.get("path")
            path = Path(str(path_value)) if path_value else None
            revision = _source_revision(call, path)
            cursor = con.execute(
                """
                INSERT INTO transcription_items (
                    source_id, source_revision, source_path, source_time,
                    source_title, state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'baseline', ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    source_revision = excluded.source_revision,
                    source_path = excluded.source_path,
                    source_time = excluded.source_time,
                    source_title = excluded.source_title,
                    state = 'baseline',
                    transcript_path = NULL,
                    provider = NULL,
                    model = NULL,
                    response_format = NULL,
                    diarized = NULL,
                    transcript_sha256 = NULL,
                    completion_sequence = NULL,
                    attempts = 0,
                    last_error = NULL,
                    next_retry_at = NULL,
                    completed_at = NULL,
                    updated_at = excluded.updated_at
                WHERE transcription_items.state != 'completed'
                """,
                (
                    source_id,
                    revision,
                    str(path) if path is not None else None,
                    _item_time(call),
                    _item_title(call),
                    now,
                    now,
                ),
            )
            inserted += cursor.rowcount
        con.execute(
            "INSERT OR REPLACE INTO transcription_meta (key, value) VALUES ('initial_baseline_at', ?)",
            (now,),
        )
        con.commit()
    return {"source_count": len(calls), "baselined": inserted, "cache_path": str(_database_path())}


def _encode_cursor(kind: str, position: str | int, source_id: str) -> str:
    payload = json.dumps([kind, position, source_id], separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> tuple[str, str | int, str]:
    try:
        padding = "=" * (-len(value) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(value + padding))
    except (ValueError, json.JSONDecodeError) as exc:
        raise TranscriptionWorkerError("invalid status cursor") from exc
    if (
        not isinstance(decoded, list)
        or len(decoded) != 3
        or decoded[0] not in ("completed", "updated")
        or not isinstance(decoded[2], str)
        or (
            decoded[0] == "completed"
            and (not isinstance(decoded[1], int) or decoded[1] < 1)
        )
        or (decoded[0] == "updated" and not isinstance(decoded[1], str))
    ):
        raise TranscriptionWorkerError("invalid status cursor")
    return decoded[0], decoded[1], decoded[2]


def cache_status(
    *,
    state: str | None = None,
    limit: int = 100,
    after_cursor: str | None = None,
) -> dict:
    if state not in (None, "baseline", "completed", "failed"):
        raise TranscriptionWorkerError(f"invalid cache state {state!r}")
    if not 1 <= limit <= 500:
        raise TranscriptionWorkerError("status limit must be between 1 and 500")
    decoded_cursor = _decode_cursor(after_cursor) if after_cursor else None
    path = _database_path()
    if not path.is_file():
        return {
            "count": 0,
            "returned": 0,
            "counts": {},
            "items": [],
            "has_more": False,
            "next_cursor": after_cursor,
            "filter": {"state": state, "limit": limit, "after_cursor": after_cursor},
            "cache_path": str(path),
        }
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        counts = {
            row["state"]: row["count"]
            for row in con.execute(
                "SELECT state, COUNT(*) AS count FROM transcription_items GROUP BY state"
            )
        }
        clauses: list[str] = []
        values: list[object] = []
        if state:
            clauses.append("state = ?")
            values.append(state)
        if decoded_cursor:
            kind, position, source_id = decoded_cursor
            expected_kind = "completed" if state == "completed" else "updated"
            if kind != expected_kind:
                raise TranscriptionWorkerError(
                    "status cursor does not match the requested state filter"
                )
            if kind == "completed":
                clauses.append(
                    "(completion_sequence > ? OR (completion_sequence = ? AND source_id > ?))"
                )
            else:
                clauses.append("(updated_at > ? OR (updated_at = ? AND source_id > ?))")
            values.extend((position, position, source_id))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order = (
            "completion_sequence, source_id"
            if state == "completed"
            else "updated_at, source_id"
        )
        rows = con.execute(
            f"SELECT * FROM transcription_items {where} "
            f"ORDER BY {order} LIMIT ?",
            (*values, limit + 1),
        ).fetchall()
    finally:
        con.close()
    has_more = len(rows) > limit
    visible = rows[:limit]
    if visible:
        last = visible[-1]
        if state == "completed":
            next_cursor = _encode_cursor(
                "completed", last["completion_sequence"], last["source_id"]
            )
        else:
            next_cursor = _encode_cursor("updated", last["updated_at"], last["source_id"])
    else:
        next_cursor = after_cursor
    return {
        "count": sum(counts.values()),
        "returned": len(visible),
        "counts": counts,
        "items": [_row_dict(row) for row in visible],
        "has_more": has_more,
        "next_cursor": next_cursor,
        "filter": {"state": state, "limit": limit, "after_cursor": after_cursor},
        "cache_path": str(_database_path()),
    }


def show_transcript(ref: str) -> dict:
    path = _database_path()
    if not path.is_file():
        raise TranscriptionWorkerError(f"no cached transcript matches {ref!r}")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        exact = con.execute(
            "SELECT * FROM transcription_items WHERE source_id = ? AND state = 'completed'",
            (ref,),
        ).fetchall()
        rows = exact or con.execute(
            "SELECT * FROM transcription_items WHERE source_id LIKE ? AND state = 'completed'",
            (f"{ref}%",),
        ).fetchall()
    finally:
        con.close()
    if not rows:
        raise TranscriptionWorkerError(f"no cached transcript matches {ref!r}")
    if len(rows) != 1:
        raise TranscriptionWorkerError(f"{ref!r} matches {len(rows)} cached transcripts")
    item = _row_dict(rows[0])
    try:
        transcript_bytes = Path(item["transcript_path"]).read_bytes()
    except OSError as exc:
        raise TranscriptionWorkerError(f"cached transcript is unreadable: {exc}") from exc
    actual_hash = hashlib.sha256(transcript_bytes).hexdigest()
    if actual_hash != item["transcript_sha256"]:
        raise TranscriptionWorkerError("cached transcript hash does not match its provenance")
    try:
        item["text"] = transcript_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TranscriptionWorkerError("cached transcript is not valid UTF-8") from exc
    return item


def retry_one(ref: str) -> dict:
    call = source.resolve(ref)
    return process_call(
        call,
        retry_failed=True,
        include_baseline=True,
        refresh=True,
    )


def _emit(result: dict, *, as_json: bool, transcript_text: bool = False) -> None:
    if transcript_text and not as_json:
        sys.stdout.write(result["text"])
        if result["text"] and not result["text"].endswith("\n"):
            sys.stdout.write("\n")
        return
    if as_json:
        json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return
    print(json.dumps(result, indent=2, ensure_ascii=False))


def _reconcile_with_receipt(*, limit: int, retry_failed: bool) -> dict:
    started_at = _iso(_now())
    try:
        result = reconcile(limit=limit, retry_failed=retry_failed)
    except Exception as exc:
        _atomic_write(
            _receipt_path(),
            (json.dumps(
                {
                    "source": "notes",
                    "started_at": started_at,
                    "finished_at": _iso(_now()),
                    "state": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                indent=2,
                sort_keys=True,
            ) + "\n").encode("utf-8"),
        )
        raise
    _atomic_write(
        _receipt_path(),
        (json.dumps(
            {
                "source": "notes",
                "started_at": started_at,
                "finished_at": _iso(_now()),
                "state": "failed" if result["counts"].get("failed") else "completed",
                "attempted": result["attempted"],
                "counts": result["counts"],
            },
            indent=2,
            sort_keys=True,
        ) + "\n").encode("utf-8"),
    )
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="notes calls transcriptions",
        description="Maintain the source-local transcript cache for Apple call recordings.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    reconcile_parser = sub.add_parser("reconcile", help="transcribe uncached calls that are due")
    reconcile_parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    reconcile_parser.add_argument("--retry-failed", action="store_true")
    reconcile_parser.add_argument("--json", action="store_true")

    baseline_parser = sub.add_parser("baseline", help="mark current calls as pre-existing without transcribing")
    baseline_parser.add_argument("--json", action="store_true")

    status_parser = sub.add_parser("status", help="inspect the local transcript cache")
    status_parser.add_argument(
        "--state", choices=("baseline", "completed", "failed")
    )
    status_parser.add_argument("--limit", type=int, default=100)
    status_parser.add_argument("--after-cursor")
    status_parser.add_argument("--json", action="store_true")

    show_parser = sub.add_parser("show", help="print one cached transcript")
    show_parser.add_argument("call")
    show_parser.add_argument("--json", action="store_true")

    retry_parser = sub.add_parser("retry", help="retry or explicitly backfill one call")
    retry_parser.add_argument("call")
    retry_parser.add_argument("--json", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "reconcile":
            result = _reconcile_with_receipt(
                limit=args.limit, retry_failed=args.retry_failed
            )
            _emit(result, as_json=args.json)
            return 1 if result["counts"].get("failed") else 0
        if args.command == "baseline":
            _emit(baseline_current(), as_json=args.json)
            return 0
        if args.command == "status":
            _emit(
                cache_status(
                    state=args.state,
                    limit=args.limit,
                    after_cursor=args.after_cursor,
                ),
                as_json=args.json,
            )
            return 0
        if args.command == "show":
            result = show_transcript(args.call)
            _emit(result, as_json=args.json, transcript_text=True)
            return 0
        if args.command == "retry":
            result = retry_one(args.call)
            _emit(result, as_json=args.json)
            return 1 if result["state"] == "failed" else 0
        raise TranscriptionWorkerError("unknown command")
    except (TranscriptionWorkerError, source.CallRecordingsError) as exc:
        print(f"notes calls transcriptions: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
