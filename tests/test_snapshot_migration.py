from __future__ import annotations

import gzip
import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet

from envman._secure_store import (
    MAX_ENVELOPE_BYTES,
    SecureStoreError,
    encrypt_document,
    is_encrypted_document,
    decrypt_document,
)
from envman._snapshot_migration import (
    MAX_UNCOMPRESSED_TAR_BYTES,
    inspect_legacy_snapshots,
    migrate_legacy_snapshots,
)


def _archive(contents: bytes, *, name: str = "environment.conf") -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz", format=tarfile.USTAR_FORMAT) as bundle:
        member = tarfile.TarInfo(name)
        member.size = len(contents)
        member.mode = 0o600
        member.mtime = 1_700_000_000
        bundle.addfile(member, io.BytesIO(contents))
    return output.getvalue()


def _member(archive: bytes) -> bytes:
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
        items = bundle.getmembers()
        if len(items) != 1:
            raise AssertionError("expected one archive member")
        stream = bundle.extractfile(items[0])
        if stream is None:
            raise AssertionError("archive member was not readable")
        return stream.read()


class SnapshotMigrationTests(unittest.TestCase):
    def test_migration_encrypts_each_environment_snapshot_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            backup_dir = Path(temporary_directory) / "backups"
            backup_dir.mkdir(mode=0o700)
            first_plaintext = b"API_TOKEN=historical-secret\n" * 150
            second_plaintext = b"DATABASE_URL=postgres://old-secret\n"
            first = backup_dir / "environment.conf.20260101T000000.000001Z.aaa.tar.gz"
            second = backup_dir / "environment.conf.20260102T000000.000001Z.bbb.tar.gz"
            profile = backup_dir / ".profile.20260102T000000.000001Z.ccc.tar.gz"
            first.write_bytes(_archive(first_plaintext))
            second.write_bytes(_archive(second_plaintext))
            profile.write_bytes(b"profile snapshot fixture")
            for path in (first, second, profile):
                path.chmod(0o600)
            profile_before = profile.read_bytes()
            key = Fernet.generate_key()

            self.assertEqual(inspect_legacy_snapshots(backup_dir), 2)
            self.assertEqual(migrate_legacy_snapshots(backup_dir, key), 2)
            first_envelope = _member(first.read_bytes())
            second_envelope = _member(second.read_bytes())
            self.assertTrue(is_encrypted_document(first_envelope))
            self.assertTrue(is_encrypted_document(second_envelope))
            self.assertNotIn(first_plaintext, first.read_bytes())
            self.assertNotIn(second_plaintext, second.read_bytes())
            self.assertEqual(decrypt_document(first_envelope, key), first_plaintext)
            self.assertEqual(decrypt_document(second_envelope, key), second_plaintext)
            self.assertEqual(first.stat().st_mode & 0o777, 0o600)
            self.assertEqual(second.stat().st_mode & 0o777, 0o600)
            self.assertEqual(profile.read_bytes(), profile_before)
            self.assertEqual(inspect_legacy_snapshots(backup_dir), 0)

            first_after_idempotent_run = first.read_bytes()
            self.assertEqual(migrate_legacy_snapshots(backup_dir, key), 0)
            self.assertEqual(first.read_bytes(), first_after_idempotent_run)

    def test_encrypted_members_are_skipped_without_changing_the_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            backup_dir = Path(temporary_directory) / "backups"
            backup_dir.mkdir(mode=0o700)
            key = Fernet.generate_key()
            envelope = encrypt_document(b"already encrypted", key)
            path = backup_dir / "environment.conf.20260101T000000.000001Z.aaa.tar.gz"
            path.write_bytes(_archive(envelope))
            path.chmod(0o600)
            before = path.read_bytes()

            self.assertEqual(inspect_legacy_snapshots(backup_dir), 0)
            self.assertEqual(migrate_legacy_snapshots(backup_dir, key), 0)
            self.assertEqual(path.read_bytes(), before)

    def test_malformed_archive_set_fails_before_replacing_any_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            backup_dir = Path(temporary_directory) / "backups"
            backup_dir.mkdir(mode=0o700)
            valid = backup_dir / "environment.conf.a.tar.gz"
            malformed = backup_dir / "environment.conf.z.tar.gz"
            valid.write_bytes(_archive(b"SECRET=must-survive\n"))
            multiple_members = io.BytesIO()
            with tarfile.open(fileobj=multiple_members, mode="w:gz") as bundle:
                for name in ("environment.conf", "unexpected.conf"):
                    member = tarfile.TarInfo(name)
                    member.size = 1
                    bundle.addfile(member, io.BytesIO(b"x"))
            malformed.write_bytes(multiple_members.getvalue())
            valid.chmod(0o600)
            malformed.chmod(0o600)
            valid_before = valid.read_bytes()
            malformed_before = malformed.read_bytes()

            with self.assertRaises(SecureStoreError):
                inspect_legacy_snapshots(backup_dir)
            with self.assertRaises(SecureStoreError):
                migrate_legacy_snapshots(backup_dir, Fernet.generate_key())
            self.assertEqual(valid.read_bytes(), valid_before)
            self.assertEqual(malformed.read_bytes(), malformed_before)

    def test_symlink_archive_permissive_directory_and_tar_bomb_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            backup_dir = root / "backups"
            backup_dir.mkdir(mode=0o700)
            outside = root / "outside.tar.gz"
            outside.write_bytes(_archive(b"KEEP=outside\n"))
            outside.chmod(0o600)
            symlinked_archive = backup_dir / "environment.conf.link.tar.gz"
            symlinked_archive.symlink_to(outside)
            with self.assertRaises(SecureStoreError):
                inspect_legacy_snapshots(backup_dir)
            self.assertEqual(outside.read_bytes(), _archive(b"KEEP=outside\n"))

            linked_directory = root / "linked-backups"
            linked_directory.symlink_to(backup_dir, target_is_directory=True)
            with self.assertRaises(SecureStoreError):
                inspect_legacy_snapshots(linked_directory)

            symlinked_archive.unlink()
            bomb = backup_dir / "environment.conf.bomb.tar.gz"
            bomb.write_bytes(gzip.compress(b"x" * (MAX_UNCOMPRESSED_TAR_BYTES + 1)))
            bomb.chmod(0o600)
            with self.assertRaises(SecureStoreError):
                inspect_legacy_snapshots(backup_dir)
            bomb.unlink()

            permissive = root / "permissive"
            permissive.mkdir(mode=0o755)
            archive = permissive / "environment.conf.a.tar.gz"
            archive.write_bytes(_archive(b"KEEP=value\n"))
            archive.chmod(0o600)
            with self.assertRaises(SecureStoreError):
                migrate_legacy_snapshots(permissive, Fernet.generate_key())
            self.assertEqual(_member(archive.read_bytes()), b"KEEP=value\n")

    def test_member_above_secure_document_limit_is_rejected_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            backup_dir = Path(temporary_directory) / "backups"
            backup_dir.mkdir(mode=0o700)
            path = backup_dir / "environment.conf.large.tar.gz"
            path.write_bytes(_archive(b"x" * (MAX_ENVELOPE_BYTES + 1)))
            path.chmod(0o600)
            before = path.read_bytes()

            with self.assertRaises(SecureStoreError):
                migrate_legacy_snapshots(backup_dir, Fernet.generate_key())
            self.assertEqual(path.read_bytes(), before)

    def test_unencryptable_snapshot_is_found_before_any_snapshot_is_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            backup_dir = Path(temporary_directory) / "backups"
            backup_dir.mkdir(mode=0o700)
            valid = backup_dir / "environment.conf.a.tar.gz"
            too_large_for_envelope = backup_dir / "environment.conf.z.tar.gz"
            valid.write_bytes(_archive(b"FIRST=value\n"))
            too_large_for_envelope.write_bytes(
                _archive(b"x" * (7 * 1024 * 1024))
            )
            valid.chmod(0o600)
            too_large_for_envelope.chmod(0o600)
            valid_before = valid.read_bytes()
            large_before = too_large_for_envelope.read_bytes()

            with self.assertRaises(SecureStoreError):
                migrate_legacy_snapshots(backup_dir, Fernet.generate_key())
            self.assertEqual(valid.read_bytes(), valid_before)
            self.assertEqual(too_large_for_envelope.read_bytes(), large_before)


if __name__ == "__main__":
    unittest.main()
