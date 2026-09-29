import importlib.util
import hashlib
import json
import os
import sqlite3
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "messages_cli.py"
SPEC = importlib.util.spec_from_file_location("messages_cli", MODULE_PATH)
messages_cli = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(messages_cli)


def encoded_body(text: str) -> bytes:
    raw = text.encode("utf-8")
    if len(raw) <= 0x7F:
        length = bytes([len(raw)])
    else:
        length = b"\x81" + len(raw).to_bytes(2, "little")
    return b"\x04\x0bstreamtyped" + b"x" * 90 + b"NSString\x01\x95\x84\x01+" + length + raw


class MessagesCliTests(unittest.TestCase):
    def test_decodes_short_and_long_typedstream_strings(self):
        self.assertEqual(messages_cli.decode_attributed_body(encoded_body("hello")), "hello")
        long_text = "message " * 30
        self.assertEqual(messages_cli.decode_attributed_body(encoded_body(long_text)), long_text.strip())

    def test_scan_is_incoming_metadata_only(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "chat.db"
            connection = sqlite3.connect(db_path)
            connection.executescript(
                """
                CREATE TABLE message (
                    ROWID INTEGER PRIMARY KEY, guid TEXT, text TEXT, attributedBody BLOB,
                    handle_id INTEGER, subject TEXT, service TEXT, date INTEGER,
                    is_from_me INTEGER, is_system_message INTEGER, associated_message_type INTEGER,
                    item_type INTEGER, cache_has_attachments INTEGER, is_spam INTEGER
                );
                CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT);
                CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, guid TEXT, display_name TEXT, chat_identifier TEXT);
                CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER);
                """
            )
            connection.execute("INSERT INTO handle VALUES (1, '+15551234567')")
            connection.execute("INSERT INTO chat VALUES (1, 'chat-guid', NULL, '+15551234567')")
            stamp = int((datetime(2026, 8, 18, 12, tzinfo=timezone.utc).timestamp() - messages_cli.APPLE_EPOCH_SECONDS) * 1_000_000_000)
            connection.execute(
                "INSERT INTO message VALUES (1, 'incoming-guid', NULL, ?, 1, NULL, 'SMS', ?, 0, 0, 0, 0, 0, 0)",
                (encoded_body("private body"), stamp),
            )
            connection.execute(
                "INSERT INTO message VALUES (2, 'outgoing-guid', 'sent', NULL, 1, NULL, 'SMS', ?, 1, 0, 0, 0, 0, 0)",
                (stamp,),
            )
            connection.execute("INSERT INTO chat_message_join VALUES (1, 1)")
            connection.execute("INSERT INTO chat_message_join VALUES (1, 2)")
            connection.commit()
            connection.close()

            environment = dict(os.environ)
            environment["MESSAGES_DB_PATH"] = str(db_path)
            result = subprocess.run(
                [
                    "/usr/bin/python3",
                    str(MODULE_PATH),
                    "--json",
                    "scan",
                    "--since",
                    "2026-08-18T11:00:00Z",
                    "--until",
                    "2026-08-18T13:00:00Z",
                ],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            )
            payload = json.loads(result.stdout)["data"]
            self.assertEqual(payload["count"], 1)
            self.assertEqual(payload["messages"][0]["id"], "incoming-guid")
            self.assertNotIn("text", payload["messages"][0])
            self.assertEqual(payload["messages"][0]["sender_label"], "Messages sender ending 4567")

    def test_installed_symlink_resolves_plugin_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db_path = root / "chat.db"
            connection = sqlite3.connect(db_path)
            connection.executescript(
                """
                CREATE TABLE message (ROWID INTEGER PRIMARY KEY, date INTEGER);
                CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT);
                CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, guid TEXT);
                CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER);
                """
            )
            connection.commit()
            connection.close()
            launcher = root / "messages"
            launcher.symlink_to(ROOT / "bin" / "messages")
            environment = dict(os.environ)
            environment["MESSAGES_DB_PATH"] = str(db_path)
            result = subprocess.run(
                [str(launcher), "--json", "doctor"],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            )
            payload = json.loads(result.stdout)["data"]
            self.assertTrue(payload["readable"])
            self.assertEqual(payload["access_mode"], "read_only")


class OutgoingSamplesTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "samples.db"
        self.start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.end = self.start + timedelta(days=1)
        connection = sqlite3.connect(self.path)
        connection.executescript("""
            CREATE TABLE message (
                ROWID INTEGER PRIMARY KEY, guid TEXT, text TEXT, attributedBody BLOB,
                handle_id INTEGER, subject TEXT, service TEXT, date INTEGER,
                is_from_me INTEGER, is_system_message INTEGER, associated_message_type INTEGER,
                item_type INTEGER, cache_has_attachments INTEGER, is_spam INTEGER
            );
            CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT);
            CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, guid TEXT, display_name TEXT, chat_identifier TEXT);
            CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER);
            INSERT INTO handle VALUES (1, 'person@example.com');
            INSERT INTO chat VALUES (1, 'chat-one', 'Example one', 'person@example.com');
            INSERT INTO chat VALUES (2, 'chat-two', 'Example two', 'other@example.com');
        """)
        self.connection = connection
        self.addCleanup(connection.close)

    def add(self, row_id, *, seconds=0, text="Sample writing", body=None,
            outgoing=1, system=0, reaction=0, item_type=0, chat=1, service="iMessage"):
        stamp = messages_cli.to_messages_date(self.start + timedelta(seconds=seconds), 1_000_000_000)
        self.connection.execute(
            "INSERT INTO message VALUES (?, ?, ?, ?, 1, NULL, ?, ?, ?, ?, ?, ?, 0, 0)",
            (row_id, f"sample-{row_id}", text, body, service, stamp, outgoing, system, reaction, item_type),
        )
        self.connection.execute("INSERT INTO chat_message_join VALUES (?, ?)", (chat, row_id))
        self.connection.commit()

    def read(self, *, limit=30, chat_id=None):
        connection = messages_cli.connect_read_only(self.path)
        try:
            return messages_cli.samples(connection, self.start, self.end, limit, chat_id)
        finally:
            connection.close()

    def test_samples_filter_direction_time_system_reactions_and_empty_text(self):
        self.add(1, text="Beginning of the window")
        self.add(2, seconds=2, outgoing=0, text="An incoming message")
        self.add(3, seconds=-1, text="Before the window")
        self.add(4, seconds=86400, text="At the exclusive end")
        self.add(5, seconds=3, system=1)
        self.add(6, seconds=4, reaction=2000)
        self.add(7, seconds=5, item_type=1)
        self.add(8, seconds=6, text=None, body=encoded_body("[attachment]"))
        self.add(9, seconds=7, text="  ", body=encoded_body("A typedstream sample"), service="SMS")
        payload = self.read()
        self.assertEqual([row["id"] for row in payload["messages"]], ["sample-9", "sample-1"])
        self.assertEqual(payload["messages"][0]["text"], "A typedstream sample")
        self.assertEqual(payload["messages"][0]["service"], "SMS")
        self.assertEqual(payload["messages"][0]["authorship"], "sent_from_account_not_verified_human_authorship")
        self.assertTrue(all(row["is_from_me"] for row in payload["messages"]))
        self.assertIn("does not verify human authorship", payload["authorship_caveat"])
        self.assertEqual(payload["skipped_without_text"], 1)
        with messages_cli.connect_read_only(self.path) as connection:
            incoming = messages_cli.scan(connection, self.start, self.end, 100)
        self.assertEqual([row["id"] for row in incoming["messages"]], ["sample-2"])
        self.assertNotIn("text", incoming["messages"][0])

    def test_exact_chat_scope_includes_messages_linked_to_multiple_chats(self):
        self.add(1, text="Shared fixture")
        self.connection.execute("INSERT INTO chat_message_join VALUES (2, 1)")
        self.connection.commit()
        self.add(2, seconds=1, text="Only the first chat")
        self.add(3, seconds=2, text="Only the second chat", chat=2)
        payload = self.read(chat_id="chat-two")
        self.assertEqual([row["id"] for row in payload["messages"]], ["sample-3", "sample-1"])
        self.assertTrue(all(row["chat_id"] == "chat-two" for row in payload["messages"]))
        self.assertEqual(payload, self.read(chat_id="other@example.com"))
        with self.assertRaises(messages_cli.MessagesError):
            self.read(chat_id="chat-two' OR 1=1 --")
        self.connection.execute("INSERT INTO chat VALUES (3, 'chat-three', NULL, 'other@example.com')")
        self.connection.commit()
        with self.assertRaisesRegex(messages_cli.MessagesError, "ambiguous"):
            self.read(chat_id="other@example.com")

    def test_row_limit_is_hard_bounded_and_source_is_read_only(self):
        for row_id in range(1, 5):
            self.add(row_id, seconds=row_id)
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        payload = self.read(limit=2)
        self.assertEqual([row["id"] for row in payload["messages"]], ["sample-4", "sample-3"])
        self.assertTrue(payload["truncated"])
        self.assertEqual(payload["selected_rows"], 2)
        self.assertEqual(payload["access_mode"], "read_only")
        for invalid in (0, 101):
            with self.assertRaises(messages_cli.MessagesError):
                self.read(limit=invalid)
        connection = messages_cli.connect_read_only(self.path)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("DELETE FROM message")
        finally:
            connection.close()
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)

    def test_public_cli_samples_use_source_window_and_json_envelope(self):
        self.add(1, text="A synthetic outgoing example")
        result = subprocess.run(
            [str(ROOT / "bin/messages"), "--json", "samples", "--since", "24h",
             "--until", messages_cli.isoformat(self.end), "--chat-id", "chat-one", "--limit", "1"],
            capture_output=True, text=True, check=True,
            env={**os.environ, "MESSAGES_DB_PATH": str(self.path)},
        )
        envelope = json.loads(result.stdout)
        self.assertTrue(envelope["ok"])
        self.assertEqual(envelope["data"]["count"], 1)
        self.assertEqual(envelope["data"]["window"]["since"], messages_cli.isoformat(self.start))


if __name__ == "__main__":
    unittest.main()
