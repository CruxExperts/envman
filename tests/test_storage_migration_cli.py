"""Preview and explicit conversion of historical plaintext snapshots."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from envman._secure_store import load_or_create_file_key
from envman.cli import EnvironmentStore, StoreError, is_encrypted_document, run_cli


class StorageMigrationCliTests(unittest.TestCase):
    def test_existing_key_rejects_plaintext_until_explicit_migration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            state = home / ".local" / "state"
            with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(state)}):
                store = EnvironmentStore(home, home / ".config")
                store.target.parent.mkdir(parents=True, mode=0o700)
                store.target.write_bytes(b"ENVMAN=legacy-name\nSAMPLE_TOKEN=sample-secret\n")
                store.target.chmod(0o600)
                load_or_create_file_key(store.storage_key_path, create=True)
                with self.assertRaisesRegex(StoreError, "migrate-storage --apply"):
                    store.load()
                store.load(allow_legacy_with_key=True)
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(
                        run_cli(argparse.Namespace(command="migrate-storage", apply=True, json=True), store),
                        0,
                    )
                self.assertTrue(is_encrypted_document(store.target.read_bytes()))
                reloaded = EnvironmentStore(home, home / ".config")
                reloaded.load()
                self.assertEqual(reloaded.values["ENVMAN"], "legacy-name")
                self.assertEqual(reloaded.values["SAMPLE_TOKEN"], "sample-secret")

    def test_preview_preserves_files_and_apply_encrypts_active_and_historical(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            state = home / ".local" / "state"
            with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(state)}):
                store = EnvironmentStore(home, home / ".config")
                store.backup_dir.mkdir(parents=True, mode=0o700)
                store.target.write_bytes(b"SAMPLE_TOKEN=sample-secret\n")
                store.target.chmod(0o600)
                historical = store.backup_dir / "environment.conf.20200101T000000Z.tar.gz"
                with tarfile.open(historical, "w:gz") as archive:
                    member = tarfile.TarInfo("environment.conf")
                    content = b"SAMPLE_TOKEN=older-secret\n"
                    member.size = len(content)
                    archive.addfile(member, io.BytesIO(content))
                historical.chmod(0o600)
                store.load()

                preview_output = io.StringIO()
                with contextlib.redirect_stdout(preview_output):
                    self.assertEqual(
                        run_cli(argparse.Namespace(command="migrate-storage", apply=False, json=True), store),
                        0,
                    )
                preview = json.loads(preview_output.getvalue())
                self.assertTrue(preview["current_plaintext"])
                self.assertEqual(preview["legacy_plaintext_snapshots"], 1)
                self.assertFalse(store.storage_key_path.exists())
                self.assertIn(b"sample-secret", store.target.read_bytes())

                apply_output = io.StringIO()
                with contextlib.redirect_stdout(apply_output):
                    self.assertEqual(
                        run_cli(argparse.Namespace(command="migrate-storage", apply=True, json=True), store),
                        0,
                    )
                applied = json.loads(apply_output.getvalue())
                self.assertEqual(applied["migrated_snapshots"], 1)
                self.assertEqual(applied["legacy_plaintext_snapshots"], 0)
                self.assertTrue(is_encrypted_document(store.target.read_bytes()))
                with tarfile.open(historical, "r:gz") as archive:
                    member = archive.extractfile("environment.conf")
                    self.assertIsNotNone(member)
                    encrypted_history = member.read() if member is not None else b""
                self.assertTrue(is_encrypted_document(encrypted_history))
                self.assertNotIn(b"older-secret", historical.read_bytes())

                reloaded = EnvironmentStore(home, home / ".config")
                reloaded.load()
                self.assertEqual(reloaded.values["SAMPLE_TOKEN"], "sample-secret")


if __name__ == "__main__":
    unittest.main()
