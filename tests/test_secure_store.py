from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet

from envman._secure_store import (
    MAX_ENVELOPE_BYTES,
    SecureStoreError,
    atomic_write_private,
    decrypt_document,
    encrypt_document,
    is_encrypted_document,
    load_or_create_file_key,
    safe_read,
)


class SecureDocumentTests(unittest.TestCase):
    def test_round_trip_authenticates_the_whole_payload_without_plaintext_leakage(self) -> None:
        key = Fernet.generate_key()
        plaintext = b"a sensitive environment document"

        envelope = encrypt_document(plaintext, key)

        self.assertTrue(is_encrypted_document(envelope))
        self.assertNotIn(plaintext, envelope)
        self.assertEqual(decrypt_document(envelope, key), plaintext)
        self.assertFalse(is_encrypted_document(plaintext))

    def test_tampering_and_wrong_key_fail_with_secret_free_errors(self) -> None:
        key = Fernet.generate_key()
        other_key = Fernet.generate_key()
        plaintext = b"private marker"
        envelope = bytearray(encrypt_document(plaintext, key))
        envelope[-1] ^= 1

        for candidate_key in (key, other_key):
            with self.subTest(key=candidate_key is key):
                with self.assertRaises(SecureStoreError) as caught:
                    decrypt_document(bytes(envelope), candidate_key)
                self.assertNotIn(plaintext.decode(), str(caught.exception))
                self.assertNotIn(candidate_key.decode(), str(caught.exception))

    def test_unknown_versions_malformed_data_and_oversize_envelopes_fail_closed(self) -> None:
        key = Fernet.generate_key()
        valid = encrypt_document(b"value", key)

        for invalid in (
            b"ENVMAN\x00\x02" + valid[8:],
            b"ENVMAN\x00\x01",
            b"not an envelope",
            b"ENVMAN\x00\x01" + b"x" * MAX_ENVELOPE_BYTES,
        ):
            with self.subTest(length=len(invalid)):
                with self.assertRaises(SecureStoreError):
                    decrypt_document(invalid, key)

        with self.assertRaises(SecureStoreError):
            encrypt_document(b"x" * MAX_ENVELOPE_BYTES, key)


class SecureFileTests(unittest.TestCase):
    def test_key_is_created_private_and_existing_key_is_never_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            key_path = Path(temporary_directory) / "private" / "encryption.key"

            key = load_or_create_file_key(key_path, create=True)

            self.assertEqual(key, key_path.read_bytes())
            self.assertEqual(key_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(key_path.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(load_or_create_file_key(key_path, create=False), key)
            self.assertEqual(load_or_create_file_key(key_path, create=True), key)

    def test_missing_key_and_unsafe_key_paths_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            key_path = root / "absent" / "encryption.key"
            with self.assertRaises(SecureStoreError):
                load_or_create_file_key(key_path, create=False)

            directory = root / "private"
            directory.mkdir(mode=0o700)
            target = root / "outside.key"
            target.write_bytes(Fernet.generate_key())
            target.chmod(0o600)
            key_path = directory / "encryption.key"
            key_path.symlink_to(target)
            with self.assertRaises(SecureStoreError):
                load_or_create_file_key(key_path, create=True)

            linked_directory = root / "linked-private"
            linked_directory.symlink_to(directory, target_is_directory=True)
            with self.assertRaises(SecureStoreError):
                load_or_create_file_key(linked_directory / "new.key", create=True)

    def test_key_reader_rejects_permissive_directory_and_key_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory) / "private"
            directory.mkdir(mode=0o700)
            key_path = directory / "encryption.key"
            key_path.write_bytes(Fernet.generate_key())
            key_path.chmod(0o600)

            directory.chmod(0o755)
            with self.assertRaises(SecureStoreError):
                load_or_create_file_key(key_path, create=False)

            directory.chmod(0o700)
            key_path.chmod(0o644)
            with self.assertRaises(SecureStoreError):
                load_or_create_file_key(key_path, create=False)

    def test_safe_read_bounds_content_and_allows_legacy_mode_unless_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "legacy.json"
            path.write_bytes(b"legacy document")
            path.chmod(0o644)

            self.assertEqual(safe_read(path, 32), b"legacy document")
            with self.assertRaises(SecureStoreError):
                safe_read(path, 8)
            with self.assertRaises(SecureStoreError):
                safe_read(path, 32, expected_mode=0o600)

            path.unlink()
            path.symlink_to(Path(temporary_directory) / "missing")
            with self.assertRaises(SecureStoreError):
                safe_read(path, 32)

    def test_atomic_write_is_private_durable_and_rejects_symlinks_or_open_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory) / "private"
            directory.mkdir(mode=0o700)
            path = directory / "document.enc"
            path.write_bytes(b"old")
            path.chmod(0o600)

            atomic_write_private(path, b"new encrypted document")

            self.assertEqual(path.read_bytes(), b"new encrypted document")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertFalse(list(directory.glob(".envman-*.tmp")))

            outside = Path(temporary_directory) / "outside"
            outside.write_bytes(b"outside")
            path.unlink()
            path.symlink_to(outside)
            with self.assertRaises(SecureStoreError):
                atomic_write_private(path, b"must not replace link")
            self.assertEqual(outside.read_bytes(), b"outside")

            path.unlink()
            directory.chmod(0o755)
            with self.assertRaises(SecureStoreError):
                atomic_write_private(path, b"must not use open directory")


if __name__ == "__main__":
    unittest.main()
