#!/usr/bin/env python3
"""Read-only macOS Messages metadata and exact message content."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


APPLE_EPOCH_SECONDS = 978_307_200
DEFAULT_WINDOW = timedelta(hours=24)
DEFAULT_LIMIT = 500
DEFAULT_SAMPLE_LIMIT = 30
MAX_SAMPLE_LIMIT = 100
AUTHORSHIP_CAVEAT = (
    "is_from_me identifies messages sent from this account; it does not verify "
    "human authorship or exclude assistant-authored, copied, or dictated text."
)
PHONEISH = re.compile(r"^[+()\-\s\d.]{3,}$")
DURATION = re.compile(r"^(\d+)([mhdw])$")
TYPEDSTREAM_PREFIXES = (b"\x01\x95\x84\x01+", b"\x01\x94\x84\x01+")


class MessagesError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_time(value: str, *, now: datetime, allow_duration: bool = False) -> datetime:
    match = DURATION.fullmatch(value.strip().lower()) if allow_duration else None
    if match:
        count = int(match.group(1))
        unit = match.group(2)
        seconds = count * {"m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]
        return now - timedelta(seconds=seconds)
    candidate = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise MessagesError(f"Invalid timestamp: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def resolve_window(since: str | None, until: str | None, *, now: datetime | None = None) -> tuple[datetime, datetime]:
    end_now = now or utc_now()
    end = parse_time(until, now=end_now) if until else end_now
    start = parse_time(since, now=end, allow_duration=True) if since else end - DEFAULT_WINDOW
    if start >= end:
        raise MessagesError("The source window must have since earlier than until")
    return start, end


def default_db_path() -> Path:
    override = os.environ.get("MESSAGES_DB_PATH")
    if override:
        return Path(override).expanduser()
    return Path.home() / "Library" / "Messages" / "chat.db"


def connect_read_only(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise MessagesError(f"Messages database not found: {path}")
    uri = f"file:{path.resolve()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("SELECT 1 FROM message LIMIT 1")
        return connection
    except sqlite3.Error as exc:
        raise MessagesError(f"Cannot read Messages database: {exc}") from exc


def date_scale(connection: sqlite3.Connection) -> int:
    raw = connection.execute("SELECT MAX(ABS(date)) FROM message").fetchone()[0] or 0
    return 1_000_000_000 if raw > 1_000_000_000_000 else 1


def to_messages_date(value: datetime, scale: int) -> int:
    return int((value.timestamp() - APPLE_EPOCH_SECONDS) * scale)


def from_messages_date(value: int, scale: int) -> datetime:
    return datetime.fromtimestamp((value / scale) + APPLE_EPOCH_SECONDS, tz=timezone.utc)


def masked_label(chat_name: str | None, sender: str | None, service: str | None) -> str:
    if chat_name and chat_name.strip():
        return chat_name.strip()
    if sender and sender.strip():
        clean = sender.strip()
        if PHONEISH.fullmatch(clean):
            digits = "".join(character for character in clean if character.isdigit())
            return f"Messages sender ending {digits[-4:]}" if len(digits) >= 4 else "Messages sender"
        if "@" in clean:
            return "iMessage sender"
        return clean
    return f"Unknown {service or 'Messages'} sender"


def _typedstream_length(blob: bytes, offset: int) -> tuple[int, int]:
    if offset >= len(blob):
        raise MessagesError("Typedstream body ended before its string length")
    marker = blob[offset]
    if marker <= 0x7F:
        return marker, offset + 1
    byte_count = {0x81: 2, 0x82: 4, 0x83: 8}.get(marker)
    if not byte_count or offset + 1 + byte_count > len(blob):
        raise MessagesError("Unsupported typedstream string length")
    length = int.from_bytes(blob[offset + 1 : offset + 1 + byte_count], "little", signed=False)
    return length, offset + 1 + byte_count


def decode_attributed_body(blob: bytes | None) -> str | None:
    if not blob:
        return None
    string_marker = blob.find(b"NSString")
    if string_marker < 0:
        return None
    search_start = string_marker + len(b"NSString")
    content_length_offset: int | None = None
    for prefix in TYPEDSTREAM_PREFIXES:
        prefix_offset = blob.find(prefix, search_start, min(len(blob), search_start + 24))
        if prefix_offset >= 0:
            content_length_offset = prefix_offset + len(prefix)
            break
    if content_length_offset is None:
        return None
    try:
        length, content_offset = _typedstream_length(blob, content_length_offset)
    except MessagesError:
        return None
    if content_offset + length > len(blob):
        return None
    decoded = blob[content_offset : content_offset + length].decode("utf-8", errors="replace")
    return decoded.replace("\ufffc", "[attachment]").strip() or None


MESSAGE_SELECT = """
SELECT
    m.ROWID AS row_id,
    m.guid AS message_id,
    m.date AS message_date,
    m.service AS service,
    m.subject AS subject,
    m.text AS legacy_text,
    m.attributedBody AS attributed_body,
    m.cache_has_attachments AS has_attachments,
    m.is_spam AS apple_spam_flag,
    m.is_from_me AS is_from_me,
    h.id AS sender,
    c.ROWID AS chat_row_id,
    c.guid AS chat_guid,
    c.display_name AS chat_name,
    c.chat_identifier AS chat_identifier
FROM message AS m
LEFT JOIN handle AS h ON h.ROWID = m.handle_id
"""

BASE_SELECT = MESSAGE_SELECT + """
LEFT JOIN (
    SELECT message_id, MIN(chat_id) AS chat_id
    FROM chat_message_join
    GROUP BY message_id
) AS cm ON cm.message_id = m.ROWID
LEFT JOIN chat AS c ON c.ROWID = cm.chat_id
"""


NORMAL_MESSAGE_FILTER = """
COALESCE(m.is_from_me, 0) = 0
AND COALESCE(m.is_system_message, 0) = 0
AND COALESCE(m.associated_message_type, 0) = 0
AND COALESCE(m.item_type, 0) = 0
"""


def metadata_for(row: sqlite3.Row, scale: int) -> dict[str, Any]:
    return {
        "id": row["message_id"],
        "row_id": row["row_id"],
        "received_at": isoformat(from_messages_date(row["message_date"], scale)),
        "service": row["service"] or "Messages",
        "sender_label": masked_label(row["chat_name"], row["sender"], row["service"]),
        "chat_id": row["chat_guid"] or row["chat_identifier"],
        "has_text": bool(row["legacy_text"] or row["attributed_body"]),
        "has_attachments": bool(row["has_attachments"]),
        "apple_spam_flag": bool(row["apple_spam_flag"]),
        "is_from_me": bool(row["is_from_me"]),
    }


def exact_message(row: sqlite3.Row, scale: int) -> dict[str, Any]:
    result = metadata_for(row, scale)
    result.update(
        {
            "sender": row["sender"],
            "chat_name": row["chat_name"],
            "subject": row["subject"],
            "text": row["legacy_text"] or decode_attributed_body(row["attributed_body"]),
        }
    )
    return result


def scan(connection: sqlite3.Connection, start: datetime, end: datetime, limit: int) -> dict[str, Any]:
    scale = date_scale(connection)
    rows = connection.execute(
        BASE_SELECT
        + " WHERE "
        + NORMAL_MESSAGE_FILTER
        + " AND m.date >= ? AND m.date < ? ORDER BY m.date ASC, m.ROWID ASC LIMIT ?",
        (to_messages_date(start, scale), to_messages_date(end, scale), limit + 1),
    ).fetchall()
    truncated = len(rows) > limit
    rows = rows[:limit]
    return {
        "source": "messages",
        "stateless": True,
        "count": len(rows),
        "truncated": truncated,
        "messages": [metadata_for(row, scale) for row in rows],
        "window": {
            "field": "message.date",
            "bounds": "[since, until)",
            "since": isoformat(start),
            "until": isoformat(end),
        },
    }


def samples(
    connection: sqlite3.Connection,
    start: datetime,
    end: datetime,
    limit: int = DEFAULT_SAMPLE_LIMIT,
    chat_id: str | None = None,
) -> dict[str, Any]:
    """Return a bounded outgoing writing corpus without changing Messages."""
    if not 1 <= limit <= MAX_SAMPLE_LIMIT:
        raise MessagesError(f"--limit must be between 1 and {MAX_SAMPLE_LIMIT}")
    if start >= end:
        raise MessagesError("The source window must have since earlier than until")
    scale = date_scale(connection)
    parameters: list[Any] = []
    selection = BASE_SELECT
    if chat_id is not None:
        chats = connection.execute(
            "SELECT ROWID FROM chat WHERE guid = ? OR chat_identifier = ? LIMIT 2",
            (chat_id, chat_id),
        ).fetchall()
        if not chats:
            raise MessagesError("The exact chat ID was not found")
        if len(chats) != 1:
            raise MessagesError("The chat identifier is ambiguous; use an exact chat GUID")
        # Scope the join itself so a message linked to several chats is reported
        # under the requested chat, even when it is not the smallest chat row ID.
        selection = MESSAGE_SELECT + """
JOIN (
    SELECT DISTINCT message_id, chat_id FROM chat_message_join WHERE chat_id = ?
) AS cm ON cm.message_id = m.ROWID
JOIN chat AS c ON c.ROWID = cm.chat_id
"""
        parameters.append(chats[0][0])
    parameters.extend((to_messages_date(start, scale), to_messages_date(end, scale), limit + 1))
    rows = connection.execute(
        selection
        + """ WHERE COALESCE(m.is_from_me, 0) = 1
AND COALESCE(m.is_system_message, 0) = 0
AND COALESCE(m.associated_message_type, 0) = 0
AND COALESCE(m.item_type, 0) = 0
AND (LENGTH(TRIM(COALESCE(m.text, ''))) > 0 OR LENGTH(m.attributedBody) > 0)
AND m.date >= ? AND m.date < ?
ORDER BY m.date DESC, m.ROWID DESC LIMIT ?""",
        parameters,
    ).fetchall()
    selected = rows[:limit]
    messages = []
    for row in selected:
        text = row["legacy_text"]
        if not text or not text.strip():
            text = decode_attributed_body(row["attributed_body"])
        if not text or not text.strip() or not text.replace("[attachment]", "").strip():
            continue
        messages.append({
            "id": row["message_id"],
            "row_id": row["row_id"],
            "sent_at": isoformat(from_messages_date(row["message_date"], scale)),
            "service": row["service"] or "Messages",
            "is_from_me": True,
            "authorship": "sent_from_account_not_verified_human_authorship",
            "chat_id": row["chat_guid"] or row["chat_identifier"],
            "chat_row_id": row["chat_row_id"],
            "chat_name": row["chat_name"],
            "text": text,
            "has_attachments": bool(row["has_attachments"]),
        })
    return {
        "source": "messages",
        "access_mode": "read_only",
        "stateless": True,
        "authorship_caveat": AUTHORSHIP_CAVEAT,
        "count": len(messages),
        "selected_rows": len(selected),
        "skipped_without_text": len(selected) - len(messages),
        "limit": limit,
        "truncated": len(rows) > limit,
        "messages": messages,
        "window": {
            "field": "message.date",
            "bounds": "[since, until)",
            "since": isoformat(start),
            "until": isoformat(end),
        },
    }


def find_message(connection: sqlite3.Connection, message_id: str) -> sqlite3.Row:
    row = connection.execute(BASE_SELECT + " WHERE m.guid = ? LIMIT 1", (message_id,)).fetchone()
    if row is None and message_id.isdigit():
        row = connection.execute(BASE_SELECT + " WHERE m.ROWID = ? LIMIT 1", (int(message_id),)).fetchone()
    if row is None:
        raise MessagesError(f"Message not found: {message_id}")
    return row


def read_message(connection: sqlite3.Connection, message_id: str) -> dict[str, Any]:
    scale = date_scale(connection)
    return exact_message(find_message(connection, message_id), scale)


def context(connection: sqlite3.Connection, message_id: str, before: int, after: int) -> dict[str, Any]:
    scale = date_scale(connection)
    target = find_message(connection, message_id)
    chat_row_id = target["chat_row_id"]
    if chat_row_id is None:
        return {"target_id": target["message_id"], "messages": [exact_message(target, scale)]}
    before_rows = connection.execute(
        BASE_SELECT
        + " JOIN chat_message_join AS target_cm ON target_cm.message_id = m.ROWID "
        + "WHERE target_cm.chat_id = ? AND (m.date < ? OR (m.date = ? AND m.ROWID < ?)) "
        + "ORDER BY m.date DESC, m.ROWID DESC LIMIT ?",
        (chat_row_id, target["message_date"], target["message_date"], target["row_id"], before),
    ).fetchall()
    after_rows = connection.execute(
        BASE_SELECT
        + " JOIN chat_message_join AS target_cm ON target_cm.message_id = m.ROWID "
        + "WHERE target_cm.chat_id = ? AND (m.date > ? OR (m.date = ? AND m.ROWID > ?)) "
        + "ORDER BY m.date ASC, m.ROWID ASC LIMIT ?",
        (chat_row_id, target["message_date"], target["message_date"], target["row_id"], after),
    ).fetchall()
    ordered = list(reversed(before_rows)) + [target] + list(after_rows)
    return {"target_id": target["message_id"], "messages": [exact_message(row, scale) for row in ordered]}


def doctor(path: Path) -> dict[str, Any]:
    connection = connect_read_only(path)
    try:
        required_tables = {"message", "handle", "chat", "chat_message_join"}
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        missing = sorted(required_tables - tables)
        return {
            "db_path": str(path),
            "db_exists": path.exists(),
            "readable": not missing,
            "access_mode": "read_only",
            "missing_tables": missing,
        }
    finally:
        connection.close()


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Read macOS Messages without changing source state.")
    root.add_argument("--json", action="store_true", help="Emit a stable JSON envelope.")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Verify read-only access to the Messages database.")

    scan_parser = commands.add_parser("scan", help="List incoming message metadata in a bounded source-time window.")
    scan_parser.add_argument("--since", help="ISO-8601 timestamp or duration such as 24h or 7d.")
    scan_parser.add_argument("--until", help="Exclusive ISO-8601 end timestamp.")
    scan_parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)

    samples_parser = commands.add_parser("samples", help="Read bounded outgoing text samples for authorized writing analysis.")
    samples_parser.add_argument("--since", help="ISO-8601 timestamp or duration; default window is 24 hours.")
    samples_parser.add_argument("--until", help="Exclusive ISO-8601 end timestamp.")
    samples_parser.add_argument("--chat-id", help="Exact chat GUID or unambiguous chat identifier; never a display-name match.")
    samples_parser.add_argument("--limit", type=int, default=DEFAULT_SAMPLE_LIMIT, help="Maximum candidate rows, from 1 to 100; default 30.")

    read_parser = commands.add_parser("read", help="Read one exact message by GUID or local row ID.")
    read_parser.add_argument("message_id")

    context_parser = commands.add_parser("context", help="Read bounded context around one exact message.")
    context_parser.add_argument("message_id")
    context_parser.add_argument("--before", type=int, default=3)
    context_parser.add_argument("--after", type=int, default=3)
    return root


def emit(payload: dict[str, Any], as_json: bool) -> None:
    envelope = {"ok": True, "data": payload}
    print(json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    path = default_db_path()
    try:
        if args.command == "doctor":
            emit(doctor(path), args.json)
            return 0
        connection = connect_read_only(path)
        try:
            if args.command == "scan":
                if args.limit < 1 or args.limit > 5000:
                    raise MessagesError("--limit must be between 1 and 5000")
                start, end = resolve_window(args.since, args.until)
                emit(scan(connection, start, end, args.limit), args.json)
            elif args.command == "read":
                emit(read_message(connection, args.message_id), args.json)
            elif args.command == "samples":
                start, end = resolve_window(args.since, args.until)
                emit(samples(connection, start, end, args.limit, args.chat_id), args.json)
            else:
                if args.before < 0 or args.after < 0 or args.before > 20 or args.after > 20:
                    raise MessagesError("Context bounds must be between 0 and 20")
                emit(context(connection, args.message_id, args.before, args.after), args.json)
            return 0
        finally:
            connection.close()
    except (MessagesError, sqlite3.Error) as exc:
        error = {"ok": False, "error": str(exc)}
        print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
