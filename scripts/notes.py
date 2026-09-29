#!/usr/bin/env python3
"""Read Apple call recordings through the Notes plugin's calls interface.

Apple's built-in phone/FaceTime call recording files each call as a note in
Notes, with the audio in the Notes group container. Nothing about that store
is guessable from the filesystem, and every wrong guess fails quietly:

- **One call is two attachment rows.** The row that carries the title
  ("Call with <contact>") reports `ZDURATION = 0.0`. The real duration lives
  on a *child* attachment (`ZPARENTATTACHMENT` -> the titled row) whose own
  media is an internal `moments_*.MOV`. Reading duration off the obvious row
  gives zero for every call.
- **The two rows bracket the call.** The parent's `ZCREATIONDATE` is when the
  call started, the child's is when it ended, and end - start matches the
  child's duration. That is the only place the call's wall-clock window exists.
- **The audio directory on disk is not a listing of calls.** Media folders
  outlast the notes that referenced them, so `find`-ing `Call with *.m4a`
  returns recordings that no longer belong to any call, interleaved with the
  live ones and indistinguishable by name, size, or mtime. The database is the
  only authority on which file is the call.
- **Timestamps are Core Data reference dates**, seconds since 2001-01-01. Read
  as Unix epoch they are wrong by 31 years. File mtime is a CloudKit sync
  artifact, not the call time.
- **The store is live and WAL-mode.** Reading `NoteStore.sqlite` without its
  `-wal` sidecar returns an older snapshot with recent calls simply absent.

Apple's own call transcript, where the feature is available, is written into
the note body -- a gzipped protobuf in `ZICNOTEDATA.ZDATA`, not an atom in the
audio file the way Voice Memos does it. This module decodes that body and
returns whatever text sits alongside the attachment placeholder.

Requires Full Disk Access for the calling process to read the Notes container.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

CONTAINER = Path.home() / "Library/Group Containers/group.com.apple.notes"
DB = CONTAINER / "NoteStore.sqlite"
ACCOUNTS = CONTAINER / "Accounts"
# Core Data reference date (2001-01-01T00:00:00Z) as a Unix timestamp.
CORE_DATA_EPOCH = 978_307_200

# The titled half of a call recording attachment pair. Its child carries the
# duration; see the module docstring.
CALL_UTI = "com.apple.m4a-audio"

# Notes marks an inline attachment in the note body with U+FFFC OBJECT
# REPLACEMENT CHARACTER. Everything else in the body is real text.
ATTACHMENT_PLACEHOLDER = "￼"

_CALL_TITLE = re.compile(r"^Call with (.+)$")


class CallRecordingsError(RuntimeError):
    pass


# --- store access ------------------------------------------------------------


def _snapshot(dest_dir: Path) -> Path:
    """Copy the live store (and its WAL sidecars) so reads see current data."""
    if not DB.exists():
        raise CallRecordingsError(
            f"Notes database not found at {DB}. Open Notes once, and make sure "
            "this process has Full Disk Access."
        )
    snap = dest_dir / DB.name
    shutil.copy2(DB, snap)
    for suffix in ("-wal", "-shm"):
        side = DB.with_name(DB.name + suffix)
        if side.exists():
            shutil.copy2(side, snap.with_name(snap.name + suffix))
    return snap


def _media_path(identifier: str, filename: str) -> Path | None:
    """Resolve a media row to the file on disk.

    Layout is Accounts/<account>/Media/<media identifier>/<generation>/<name>.
    The generation directory is opaque, so glob it rather than reconstruct it.
    """
    if not identifier or not filename:
        return None
    for candidate in ACCOUNTS.glob(f"*/Media/{identifier}/*/{filename}"):
        return candidate
    return None


def _stamp(value: float | None) -> dt.datetime | None:
    if value is None:
        return None
    return dt.datetime.fromtimestamp(value + CORE_DATA_EPOCH)


def read_calls() -> list[dict]:
    """Every call recording in the store, oldest first."""
    with tempfile.TemporaryDirectory() as tmp:
        snap = _snapshot(Path(tmp))
        con = sqlite3.connect(f"file:{snap}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            parents = con.execute(
                """
                SELECT a.Z_PK, a.ZIDENTIFIER, a.ZTITLE, a.ZCREATIONDATE,
                       a.ZNOTE, m.ZIDENTIFIER AS media_id, m.ZFILENAME AS filename
                FROM ZICCLOUDSYNCINGOBJECT a
                LEFT JOIN ZICCLOUDSYNCINGOBJECT m ON m.Z_PK = a.ZMEDIA
                WHERE a.ZTYPEUTI = ?
                  AND a.ZPARENTATTACHMENT IS NULL
                  AND a.ZTITLE IS NOT NULL
                ORDER BY a.ZCREATIONDATE
                """,
                (CALL_UTI,),
            ).fetchall()

            children = {}
            for row in con.execute(
                """
                SELECT c.ZPARENTATTACHMENT AS parent, c.ZDURATION, c.ZCREATIONDATE,
                       m.ZIDENTIFIER AS media_id, m.ZFILENAME AS filename
                FROM ZICCLOUDSYNCINGOBJECT c
                LEFT JOIN ZICCLOUDSYNCINGOBJECT m ON m.Z_PK = c.ZMEDIA
                WHERE c.ZPARENTATTACHMENT IS NOT NULL
                """
            ):
                children[row["parent"]] = row

            bodies = {
                r["ZNOTE"]: r["ZDATA"]
                for r in con.execute("SELECT ZNOTE, ZDATA FROM ZICNOTEDATA")
            }
        except sqlite3.DatabaseError as exc:  # schema drift across macOS versions
            raise CallRecordingsError(f"could not read the Notes store: {exc}") from exc
        finally:
            con.close()

    out = []
    for p in parents:
        child = children.get(p["Z_PK"])
        started = _stamp(p["ZCREATIONDATE"])
        ended = _stamp(child["ZCREATIONDATE"]) if child else None

        # The titled row's own ZDURATION is 0.0 for every call; the child holds
        # the real value. Fall back to the bracket only if the child is gone.
        duration = child["ZDURATION"] if child and child["ZDURATION"] else None
        if not duration and started and ended:
            duration = (ended - started).total_seconds()

        audio = _media_path(p["media_id"], p["filename"])
        moments = _media_path(child["media_id"], child["filename"]) if child else None
        title = p["ZTITLE"] or ""
        contact = _CALL_TITLE.match(title)

        out.append(
            {
                "id": p["ZIDENTIFIER"],
                "title": title,
                "contact": contact.group(1) if contact else None,
                "started_at": started.isoformat(timespec="seconds") if started else None,
                "date": started.strftime("%Y-%m-%d") if started else None,
                "time": started.strftime("%H:%M") if started else None,
                "ended_at": ended.isoformat(timespec="seconds") if ended else None,
                "duration_seconds": int(duration) if duration else 0,
                "path": str(audio) if audio else None,
                "exists": audio is not None,
                # Apple's internal capture of the same call, in a MOV container.
                # The .m4a is the canonical recording; this is exposed only so a
                # caller can tell the two apart instead of stumbling on it.
                "moments_path": str(moments) if moments else None,
                "has_apple_transcript": bool(_body_text(bodies.get(p["ZNOTE"]), title)),
                "note_pk": p["ZNOTE"],
            }
        )
    return out


def resolve(ref: str) -> dict:
    """Find a call by attachment UUID, UUID prefix, or contact name."""
    ref = ref.strip()
    calls = read_calls()
    for c in calls:
        if ref == c["id"]:
            return c
    matches = [c for c in calls if c["id"].upper().startswith(ref.upper())]
    if not matches:
        needle = ref.casefold()
        matches = [c for c in calls if needle in (c["contact"] or "").casefold()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise CallRecordingsError(f"no call recording matches {ref!r}")
    listing = ", ".join(f"{c['id'][:8]} ({c['date']})" for c in matches)
    raise CallRecordingsError(f"{ref!r} matches {len(matches)} calls: {listing}")


# --- note body ---------------------------------------------------------------


def _varint(buf: bytes, i: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        byte = buf[i]
        i += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, i
        shift += 7


def _fields(buf: bytes):
    """Yield (field number, payload) for length-delimited protobuf fields."""
    i = 0
    while i < len(buf):
        try:
            key, i = _varint(buf, i)
            wire = key & 7
            if wire == 0:
                _, i = _varint(buf, i)
                continue
            if wire == 1:
                i += 8
                continue
            if wire == 5:
                i += 4
                continue
            if wire != 2:
                return
            length, i = _varint(buf, i)
            yield key >> 3, buf[i : i + length]
            i += length
        except IndexError:
            return


def _note_text(blob: bytes | None) -> str | None:
    """Decode ZICNOTEDATA.ZDATA to the note's plain text.

    NoteStoreProto.document (2) -> Document.note (3) -> Note.note_text (2).
    """
    if not blob:
        return None
    try:
        raw = gzip.decompress(blob)
    except (OSError, EOFError):
        return None
    for fn, document in _fields(raw):
        if fn != 2:
            continue
        for fn2, note in _fields(document):
            if fn2 != 3:
                continue
            for fn3, text in _fields(note):
                if fn3 == 2:
                    return text.decode("utf-8", errors="replace")
    return None


def _body_text(blob: bytes | None, title: str) -> str:
    """The note's text with the title line and attachment placeholders removed.

    A call note with no transcript is exactly its title plus one placeholder,
    so what survives this is Apple's transcript when the feature produced one.
    """
    text = _note_text(blob)
    if not text:
        return ""
    lines = text.split("\n")
    if lines and lines[0].strip() == title.strip():
        lines = lines[1:]
    kept = [line.replace(ATTACHMENT_PLACEHOLDER, "").strip() for line in lines]
    return "\n".join(line for line in kept if line).strip()


def apple_transcript(call: dict) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        snap = _snapshot(Path(tmp))
        con = sqlite3.connect(f"file:{snap}?mode=ro", uri=True)
        try:
            row = con.execute(
                "SELECT ZDATA FROM ZICNOTEDATA WHERE ZNOTE = ?", (call["note_pk"],)
            ).fetchone()
        finally:
            con.close()
    return _body_text(row[0] if row else None, call["title"])


# --- commands ----------------------------------------------------------------


def _humanize(seconds: int) -> str:
    return f"{seconds}s" if seconds < 60 else f"{seconds // 60}m {seconds % 60:02d}s"


def cmd_list(args: argparse.Namespace) -> int:
    calls = read_calls()
    if args.since:
        calls = [c for c in calls if c["date"] and c["date"] >= args.since]

    if args.json:
        json.dump({"count": len(calls), "calls": calls}, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0

    if not calls:
        print("No call recordings found.")
        return 0
    for c in calls:
        marks = "" if c["exists"] else "  [audio missing]"
        if c["has_apple_transcript"]:
            marks += "  [apple transcript]"
        print(
            f"{c['date']} {c['time']}  {_humanize(c['duration_seconds']):>9}  "
            f"{c['id'][:8]}  {c['contact'] or c['title']}{marks}"
        )
    return 0


def cmd_path(args: argparse.Namespace) -> int:
    call = resolve(args.call)
    if not call["path"]:
        raise CallRecordingsError(
            f"{call['title']} ({call['date']}) has no audio file on disk — the note "
            "exists but its media was never downloaded from iCloud. Open the note "
            "in Notes to fetch it."
        )
    print(call["path"])
    return 0


def cmd_transcript(args: argparse.Namespace) -> int:
    call = resolve(args.call)
    text = apple_transcript(call)
    if args.json:
        json.dump(
            {"call": call, "transcript": text or None},
            sys.stdout,
            indent=2,
            ensure_ascii=False,
        )
        sys.stdout.write("\n")
        return 0 if text else 1
    if not text:
        print(
            f"{call['title']} ({call['date']}): no Apple transcript in the note.\n"
            "Call transcription is region- and language-gated, so most calls carry "
            "none. Transcribe the audio instead (e.g. `elevenlabs transcribe`).",
            file=sys.stderr,
        )
        return 1
    print(text)
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Report store readability and audio on disk that belongs to no call."""
    report: dict = {"database": str(DB), "readable": False}
    try:
        calls = read_calls()
    except CallRecordingsError as exc:
        report["error"] = str(exc)
        if args.json:
            json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
            sys.stdout.write("\n")
        else:
            print(f"notes calls: {exc}", file=sys.stderr)
        return 2

    report["readable"] = True
    report["calls"] = len(calls)
    report["missing_audio"] = [c["id"] for c in calls if not c["exists"]]

    referenced = {c["path"] for c in calls if c["path"]}
    referenced |= {c["moments_path"] for c in calls if c["moments_path"]}
    on_disk = {str(p) for p in ACCOUNTS.glob("*/Media/*/*/*") if p.is_file()}
    report["unreferenced_media"] = sorted(on_disk - referenced)

    if args.json:
        json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0

    print(f"Notes store: readable ({len(calls)} call recordings)")
    if report["missing_audio"]:
        print(f"Calls whose audio is not downloaded: {len(report['missing_audio'])}")
    orphans = report["unreferenced_media"]
    if orphans:
        print(
            f"\nMedia files on disk belonging to no current call: {len(orphans)}\n"
            "These are left behind by deleted or superseded recordings. Do not "
            "treat them as copies of a live call — the database is authoritative."
        )
        for path in orphans:
            print(f"  {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="notes calls", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="list call recordings in the Notes store")
    p_list.add_argument("--json", action="store_true", help="emit JSON")
    p_list.add_argument("--since", metavar="YYYY-MM-DD", help="only calls on or after this date")
    p_list.set_defaults(func=cmd_list)

    p_path = sub.add_parser("path", help="print the absolute audio path for a call")
    p_path.add_argument("call", help="attachment UUID, UUID prefix, or contact name")
    p_path.set_defaults(func=cmd_path)

    p_tr = sub.add_parser("transcript", help="print Apple's transcript from the note, if any")
    p_tr.add_argument("call", help="attachment UUID, UUID prefix, or contact name")
    p_tr.add_argument("--json", action="store_true", help="emit JSON")
    p_tr.set_defaults(func=cmd_transcript)

    p_doc = sub.add_parser("doctor", help="check store access and report unreferenced audio")
    p_doc.add_argument("--json", action="store_true", help="emit JSON")
    p_doc.set_defaults(func=cmd_doctor)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CallRecordingsError as exc:
        print(f"notes calls: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
