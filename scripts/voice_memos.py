#!/usr/bin/env python3
"""Read the macOS Voice Memos store.

Voice Memos keeps its index in a Core Data SQLite database, not in the audio
filenames. Reading it directly is the difference between a correct enumeration
and a plausible one:

- The store is WAL-mode and live. Opening `CloudRecordings.db` alone can miss
  recordings that are still only in the write-ahead log, and the miss is silent
  — you get an older snapshot, not an error. This module always snapshots the
  `.db`, `-wal` and `-shm` together before reading.
- Timestamps are Core Data reference dates (seconds since 2001-01-01), not Unix
  epoch. Treating one as the other is a 31-year error.
- `ZUNIQUEID` is a stable identifier that survives renames; the filename is not.

Voice Memos also embeds Apple's own on-device transcript in the audio file, as
JSON inside a `tsrp` atom under `udta`. It is free to read, but it is written
lazily — a recording that has never been opened in the app usually has none —
so treat it as an opportunistic fast path, never as a guaranteed source.

Requires Full Disk Access for the calling process to read the store.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RECORDINGS = Path.home() / (
    "Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings"
)
DB = RECORDINGS / "CloudRecordings.db"
VOICE_MEMOS_APP = Path("/System/Applications/VoiceMemos.app")
SYNC_NUDGE_DELAY_SECONDS = 1.0

# Core Data reference date (2001-01-01T00:00:00Z) expressed as a Unix timestamp.
CORE_DATA_EPOCH = 978_307_200

_TEXT_RUN = re.compile(rb"[\x20-\x7e]{4,}")

# Voice Memos seeds ZCUSTOMLABEL with an ISO timestamp when the user has not
# named a recording. A label that is *not* this shape was typed by a human, and
# is a much better signal about a recording than anything else in the store.
_AUTO_LABEL = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?$")


class VoiceMemosError(RuntimeError):
    pass


def ensure_current_store() -> None:
    """Launch Voice Memos hidden so iCloud can materialize pending recordings."""
    command = ["/usr/bin/open", "-gj", str(VOICE_MEMOS_APP)]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VoiceMemosError(
            f"could not launch Voice Memos in the background to refresh its store: {exc}"
        ) from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise VoiceMemosError(
            "could not launch Voice Memos in the background to refresh its store: "
            f"{detail}"
        )
    time.sleep(SYNC_NUDGE_DELAY_SECONDS)


def _snapshot(dest_dir: Path) -> Path:
    """Copy the live store (and its WAL sidecars) so reads see current data."""
    if not DB.exists():
        raise VoiceMemosError(
            f"Voice Memos database not found at {DB}. Open Voice Memos once, "
            "and make sure this process has Full Disk Access."
        )
    snap = dest_dir / DB.name
    shutil.copy2(DB, snap)
    for suffix in ("-wal", "-shm"):
        side = DB.with_name(DB.name + suffix)
        if side.exists():
            shutil.copy2(side, snap.with_name(snap.name + suffix))
    return snap


def read_recordings() -> list[dict]:
    """Every recording currently materialized in the store, oldest first."""
    ensure_current_store()
    with tempfile.TemporaryDirectory() as tmp:
        snap = _snapshot(Path(tmp))
        con = sqlite3.connect(f"file:{snap}?mode=ro", uri=True)
        try:
            rows = con.execute(
                """
                SELECT ZUNIQUEID, ZPATH, ZDATE, ZDURATION, ZCUSTOMLABEL
                FROM ZCLOUDRECORDING
                WHERE ZPATH IS NOT NULL
                ORDER BY ZDATE
                """
            ).fetchall()
        except sqlite3.DatabaseError as exc:  # schema drift across macOS versions
            raise VoiceMemosError(f"could not read the Voice Memos store: {exc}") from exc
        finally:
            con.close()

    out = []
    for uid, rel, zdate, duration, label in rows:
        recorded = dt.datetime.fromtimestamp(
            (zdate or 0) + CORE_DATA_EPOCH, tz=dt.timezone.utc
        ).astimezone()
        path = RECORDINGS / rel
        out.append(
            {
                "uuid": uid,
                "filename": rel,
                "path": str(path),
                "exists": path.exists(),
                "recorded_at": recorded.isoformat(timespec="seconds"),
                "date": recorded.strftime("%Y-%m-%d"),
                "time": recorded.strftime("%H:%M"),
                "duration_seconds": int(duration or 0),
                "title": label,
                "title_is_auto": bool(label is None or _AUTO_LABEL.match(str(label))),
            }
        )
    return out


def resolve(ref: str) -> dict:
    """Find a recording by UUID, filename, or filename stem."""
    ref = ref.strip()
    candidates = read_recordings()
    for r in candidates:
        if ref in (r["uuid"], r["filename"], Path(r["filename"]).stem):
            return r
    # Allow the short hex suffix Voice Memos puts in filenames, e.g. "38BEC65A".
    for r in candidates:
        if r["uuid"].startswith(ref.upper()):
            return r
    raise VoiceMemosError(f"no recording matches {ref!r}")


def apple_transcript(path: Path) -> dict | None:
    """Apple's on-device transcript, or None if the file carries none.

    Stored as JSON in a `tsrp` atom: an NSAttributedString-shaped array that
    alternates text segments with attribute dicts carrying time ranges.
    """
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise VoiceMemosError(f"could not read {path}: {exc}") from exc

    idx = data.find(b"tsrp")
    if idx < 4:
        return None

    # An MP4 atom is [4-byte big-endian size][4-byte type][body].
    size = struct.unpack(">I", data[idx - 4 : idx])[0]
    end = idx - 4 + size
    body = data[idx + 4 : end] if 4 < size <= len(data) - idx + 4 else data[idx + 4 :]

    try:
        parsed = json.loads(body.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        # Truncated or a shape we do not know; fall back to visible text runs
        # rather than claiming there is no transcript.
        runs = [m.group().decode("ascii") for m in _TEXT_RUN.finditer(body)]
        return {"text": " ".join(runs).strip(), "locale": None, "segments": [], "exact": False} if runs else None

    attributed = parsed.get("attributedString") or []
    segments, texts = [], []
    for i in range(0, len(attributed), 2):
        chunk = attributed[i]
        if not isinstance(chunk, str):
            continue
        texts.append(chunk)
        attrs = attributed[i + 1] if i + 1 < len(attributed) else {}
        span = attrs.get("timeRange") if isinstance(attrs, dict) else None
        segments.append({"text": chunk, "time_range": span})

    locale = (parsed.get("locale") or {}).get("identifier")
    return {"text": "".join(texts).strip(), "locale": locale, "segments": segments, "exact": True}


def _humanize(seconds: int) -> str:
    return f"{seconds}s" if seconds < 60 else f"{seconds // 60}m {seconds % 60:02d}s"


def cmd_list(args: argparse.Namespace) -> int:
    records = read_recordings()
    if args.since:
        records = [r for r in records if r["date"] >= args.since]
    if args.check_transcripts:
        for r in records:
            p = Path(r["path"])
            r["has_apple_transcript"] = p.exists() and b"tsrp" in p.read_bytes()

    if args.json:
        json.dump({"count": len(records), "recordings": records}, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0

    if not records:
        print("No recordings found.")
        return 0
    for r in records:
        mark = ""
        if args.check_transcripts:
            mark = "  [apple transcript]" if r["has_apple_transcript"] else "  [no transcript]"
        title = "" if r["title_is_auto"] else f"  {r['title']}"
        print(f"{r['date']} {r['time']}  {_humanize(r['duration_seconds']):>9}  {r['filename']}{mark}{title}")
    return 0


def cmd_transcript(args: argparse.Namespace) -> int:
    record = resolve(args.recording)
    result = apple_transcript(Path(record["path"]))
    if result is None:
        if args.json:
            json.dump({"recording": record, "transcript": None}, sys.stdout, indent=2, ensure_ascii=False)
            sys.stdout.write("\n")
        else:
            print(
                f"{record['filename']}: no Apple transcript embedded.\n"
                "Apple writes these lazily — open the memo in Voice Memos, or transcribe "
                "the audio yourself (e.g. `elevenlabs transcribe`)."
            )
        return 1
    if args.json:
        json.dump({"recording": record, "transcript": result}, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        print(result["text"])
    return 0


def cmd_path(args: argparse.Namespace) -> int:
    print(resolve(args.recording)["path"])
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="voice-memos", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="list recordings in the Voice Memos store")
    p_list.add_argument("--json", action="store_true", help="emit JSON")
    p_list.add_argument("--since", metavar="YYYY-MM-DD", help="only recordings on or after this date")
    p_list.add_argument(
        "--check-transcripts",
        action="store_true",
        help="also report whether each file carries an Apple transcript (reads every file)",
    )
    p_list.set_defaults(func=cmd_list)

    p_tr = sub.add_parser("transcript", help="print Apple's embedded transcript, if any")
    p_tr.add_argument("recording", help="UUID, filename, or filename stem")
    p_tr.add_argument("--json", action="store_true", help="emit JSON")
    p_tr.set_defaults(func=cmd_transcript)

    p_path = sub.add_parser("path", help="print the absolute audio path for a recording")
    p_path.add_argument("recording", help="UUID, filename, or filename stem")
    p_path.set_defaults(func=cmd_path)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except VoiceMemosError as exc:
        print(f"voice-memos: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
