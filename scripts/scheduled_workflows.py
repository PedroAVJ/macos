#!/usr/bin/env python3
"""Read Voice Memos scheduled workflows by recording-time window.

The semantic selection is stateless. The source-local transcript cache remains
durable infrastructure so a repeated window can reuse verified transcripts.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import voice_memos_transcription_worker as transcripts  # noqa: E402


WORKFLOWS = {
    "questions": "answer-captured-questions",
    "health-observations": "discuss-health-observations",
}
DEFAULT_WINDOW = dt.timedelta(hours=24)
DEFAULT_LIMIT = 100
_DURATION = re.compile(r"^(?P<amount>\d+(?:\.\d+)?)(?P<unit>[mhdw])$")


class ScheduledWorkflowError(RuntimeError):
    pass


def _workflow_name(value: str) -> str:
    if value not in WORKFLOWS:
        raise ScheduledWorkflowError(f"unsupported Voice Memos workflow {value!r}")
    return value


def _iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _absolute_time(value: str, option: str, *, allow_local_naive: bool = False) -> dt.datetime:
    raw = value.strip()
    try:
        parsed = dt.datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
    except ValueError as exc:
        raise ScheduledWorkflowError(f"{option} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        if not allow_local_naive:
            raise ScheduledWorkflowError(f"{option} must include a timezone")
        parsed = parsed.astimezone()
    return parsed.astimezone(dt.timezone.utc)


def _duration(value: str) -> dt.timedelta | None:
    match = _DURATION.fullmatch(value.strip().casefold())
    if not match:
        return None
    amount = float(match.group("amount"))
    seconds = amount * {"m": 60, "h": 3600, "d": 86400, "w": 604800}[match.group("unit")]
    return dt.timedelta(seconds=seconds) if seconds > 0 else None


def resolve_window(
    since: str | None,
    until: str | None,
    *,
    now: dt.datetime | None = None,
) -> tuple[dt.datetime, dt.datetime, bool]:
    end = _absolute_time(until, "--until") if until else (now or dt.datetime.now(dt.timezone.utc))
    end = end.astimezone(dt.timezone.utc)
    defaulted = since is None
    if since is None:
        start = end - DEFAULT_WINDOW
    else:
        relative = _duration(since)
        start = end - relative if relative else _absolute_time(since, "--since")
    if start >= end:
        raise ScheduledWorkflowError("--since must be earlier than --until")
    return start, end, defaulted


def _recorded_time(recording: dict) -> dt.datetime:
    value = recording.get("recorded_at")
    if not isinstance(value, str) or not value:
        raise ScheduledWorkflowError(
            f"Voice Memo {recording.get('uuid') or '<unknown>'} has no recording timestamp"
        )
    # Older cached Voice Memos records stored local wall time without an
    # offset. Interpret those as the current system timezone; new records may
    # include their explicit offset.
    return _absolute_time(value, "recorded_at", allow_local_naive=True)


def _validated_transcript(recording: dict) -> tuple[dict | None, dict | None, bool]:
    result = transcripts.process_recording(
        recording,
        retry_failed=True,
        include_baseline=True,
    )
    attempted = bool(result.get("attempted"))
    source_id = str(recording.get("uuid") or result.get("source_id") or "")
    if result.get("state") not in {"cached", "completed"}:
        return None, {
            "uuid": source_id,
            "recorded_at": recording.get("recorded_at"),
            "state": result.get("state") or "unavailable",
            "error": result.get("last_error"),
        }, attempted
    try:
        item = transcripts.show_transcript(source_id)
    except transcripts.TranscriptionWorkerError as exc:
        return None, {
            "uuid": source_id,
            "recorded_at": recording.get("recorded_at"),
            "state": "unavailable",
            "error": str(exc),
        }, attempted
    item.pop("text", None)
    return item, None, attempted


def scan(
    workflow: str,
    *,
    since: str | None = None,
    until: str | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> dict:
    workflow = _workflow_name(workflow)
    if not 1 <= limit <= 500:
        raise ScheduledWorkflowError("scan limit must be between 1 and 500")
    if offset < 0:
        raise ScheduledWorkflowError("scan offset must be zero or greater")
    start, end, defaulted = resolve_window(since, until)
    selected: list[tuple[dt.datetime, dict]] = []
    for recording in transcripts.source.read_recordings():
        recorded = _recorded_time(recording)
        if start <= recorded < end:
            selected.append((recorded, recording))
    selected.sort(key=lambda pair: (pair[0], str(pair[1].get("uuid") or "")))

    page = selected[offset : offset + limit]
    items: list[dict] = []
    unavailable: list[dict] = []
    attempted = 0
    for _, recording in page:
        item, failure, did_attempt = _validated_transcript(recording)
        attempted += int(did_attempt)
        if item is not None:
            items.append(item)
        if failure is not None:
            unavailable.append(failure)

    next_offset = offset + len(page)
    has_more = next_offset < len(selected)
    return {
        "source": "voice-memos",
        "workflow": workflow,
        "skill": WORKFLOWS[workflow],
        "window": {
            "field": "recorded_at",
            "since": _iso(start),
            "until": _iso(end),
            "bounds": "[since, until)",
            "defaulted_to_previous_24_hours": defaulted,
        },
        "matched_recordings": len(selected),
        "count": len(items),
        "items": items,
        "unavailable": unavailable,
        "attempted_transcriptions": attempted,
        "offset": offset,
        "next_offset": next_offset if has_more else None,
        "has_more": has_more,
        "stateless": True,
    }


def _emit(value: dict, as_json: bool) -> None:
    if as_json:
        json.dump(value, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        print(json.dumps(value, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="voice-memos",
        description="Read recordings for one Voice Memos skill in a bounded recording-time window.",
    )
    parser.add_argument("workflow", choices=tuple(WORKFLOWS))
    actions = parser.add_subparsers(dest="action", required=True)
    scan_parser = actions.add_parser("scan", help="read recordings captured in a source-time window")
    scan_parser.add_argument(
        "--since",
        help="ISO-8601 start time, or a duration such as 24h relative to --until/current time",
    )
    scan_parser.add_argument("--until", help="ISO-8601 exclusive end time; defaults to now")
    scan_parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    scan_parser.add_argument("--offset", type=int, default=0)
    scan_parser.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    try:
        value = scan(
            args.workflow,
            since=args.since,
            until=args.until,
            limit=args.limit,
            offset=args.offset,
        )
        _emit(value, args.json)
        return 0
    except (ScheduledWorkflowError, transcripts.TranscriptionWorkerError) as exc:
        print(f"voice-memos: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
