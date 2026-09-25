"""The retained decryptor must work without the Envman tool environment."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cryptography.fernet import Fernet

from envman._retained_loader import install_retained_runtime
from envman._secure_store import atomic_write_private, encrypt_document, load_or_create_file_key
from envman.cli import EnvironmentStore


class RetainedLoaderTests(unittest.TestCase):
    def test_posix_loader_preserves_managed_names_that_match_its_scratch_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            config = home / ".config"
            state = home / ".local" / "state"
            environment = {
                "HOME": str(home),
                "XDG_CONFIG_HOME": str(config),
                "XDG_STATE_HOME": str(state),
                "PATH": "/usr/bin:/bin",
            }
            with mock.patch.dict(os.environ, environment):
                store = EnvironmentStore(home, config)
                store.values = {
                    "_envman_loaded": "retained",
                    "_envman_environment_values": "also-retained",
                    "_envman_config_home": "still-retained",
                    "aaa": "later",
                }
                store.save()

            result = subprocess.run(
                [
                    "/bin/sh",
                    "-c",
                    f'. "{store.loader}"; printf "%s|%s|%s|%s" '
                    '"$_envman_loaded" "$_envman_environment_values" '
                    '"$_envman_config_home" "$aaa"',
                ],
                env=environment,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, b"retained|also-retained|still-retained|later")

            profile_result = subprocess.run(
                ["/bin/sh", "-c", '. "$HOME/.profile"; printf "%s|%s" "$_envman_config_home" "$aaa"'],
                env=environment,
                capture_output=True,
                check=False,
            )
            self.assertEqual(profile_result.returncode, 0, profile_result.stderr)
            self.assertEqual(profile_result.stdout, b"still-retained|later")

    def test_bash_readonly_assignment_does_not_prevent_later_variables(self) -> None:
        bash = shutil.which("bash")
        if bash is None:
            self.skipTest("bash is unavailable")
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            config = home / ".config"
            state = home / ".local" / "state"
            environment = {
                "HOME": str(home),
                "XDG_CONFIG_HOME": str(config),
                "XDG_STATE_HOME": str(state),
                "PATH": "/usr/bin:/bin",
            }
            with mock.patch.dict(os.environ, environment):
                store = EnvironmentStore(home, config)
                store.values = {"UID": "12345", "aaa": "later"}
                store.save()

            result = subprocess.run(
                [bash, "-c", f'source "{store.loader}"; printf "%s" "$aaa"'],
                env=environment,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, b"later")
            self.assertIn(b"skipped invalid environment assignment", result.stderr)

    def test_fish_loader_preserves_literal_values_and_reports_unlock_failure(self) -> None:
        fish = shutil.which("fish")
        if fish is None:
            self.skipTest("fish is unavailable")
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home with ' quote"
            home.mkdir()
            config = home / ".config"
            state = home / ".local" / "state"
            marker = home / "unwanted-marker"
            value = f" left $(touch {marker}) $HOME 'quote' = right "
            environment = {
                "HOME": str(home),
                "XDG_CONFIG_HOME": str(config),
                "XDG_STATE_HOME": str(state),
                "PATH": "/usr/bin:/bin",
            }
            with mock.patch.dict(os.environ, environment):
                store = EnvironmentStore(home, config)
                store.values = {"LITERAL": value}
                store.save()

            loaded = subprocess.run(
                [fish, "-c", f'source "{store.fish_loader}"; printf "%s" "$LITERAL"'],
                env=environment,
                capture_output=True,
                check=False,
            )
            self.assertEqual(loaded.returncode, 0, loaded.stderr)
            self.assertEqual(loaded.stdout.decode("utf-8"), value)
            self.assertFalse(marker.exists())

            store.storage_key_path.write_bytes(Fernet.generate_key())
            failed = subprocess.run(
                [fish, "-c", f'source "{store.fish_loader}"; exit $status'],
                env=environment,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertEqual(failed.stdout, b"")
            self.assertNotIn(value.encode("utf-8"), failed.stderr)

            preserved = subprocess.run(
                [
                    "/bin/sh",
                    "-c",
                    f'. "{store.loader}"; status=$?; printf "%s|%s|%s" "$status" "$_envman_loaded" "${{LITERAL-unset}}"',
                ],
                env={**environment, "_envman_loaded": "prior"},
                capture_output=True,
                check=False,
            )
            self.assertEqual(preserved.returncode, 0, preserved.stderr)
            self.assertEqual(preserved.stdout, b"1|prior|unset")

    def test_posix_loader_preserves_literal_values_and_reports_unlock_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home with ' quote"
            home.mkdir()
            config = home / ".config"
            state = home / ".local" / "state"
            marker = home / "unwanted-marker"
            value = f" left $(touch {marker}) $HOME 'quote' = right "
            environment = {
                "HOME": str(home),
                "XDG_CONFIG_HOME": str(config),
                "XDG_STATE_HOME": str(state),
                "PATH": "/usr/bin:/bin",
            }
            with mock.patch.dict(os.environ, environment):
                store = EnvironmentStore(home, config)
                store.values = {"LITERAL": value}
                store.save()

            command = f'. "{store.loader}"; exit $?'
            child = subprocess.run(
                ["/bin/sh", "-c", f'. "{store.loader}"; printf "%s" "$LITERAL"'],
                env=environment,
                capture_output=True,
                check=False,
            )
            self.assertEqual(child.returncode, 0, child.stderr)
            self.assertEqual(child.stdout.decode("utf-8"), value)
            self.assertFalse(marker.exists())

            store.storage_key_path.write_bytes(Fernet.generate_key())
            failed = subprocess.run(
                ["/bin/sh", "-c", command],
                env=environment,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertEqual(failed.stdout, b"")
            self.assertNotIn(value.encode("utf-8"), failed.stderr)

    def test_standalone_runtime_loads_legacy_and_encrypted_values_and_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            config = home / ".config"
            utility = config / "envman"
            state = home / ".local" / "state"
            utility.mkdir(parents=True, mode=0o700)
            source = utility / "environment.conf"
            loader = install_retained_runtime(utility)
            assignments = b"ENVMAN=legitimate variable\nCOMMENTED=  space $PATH $(id) = value  \nEMPTY=\n# retained comment\n"
            child_env = {
                "HOME": str(home),
                "XDG_CONFIG_HOME": str(config),
                "XDG_STATE_HOME": str(state),
                "PATH": os.environ.get("PATH", ""),
            }

            def run_loader() -> subprocess.CompletedProcess[bytes]:
                return subprocess.run(
                    [sys._base_executable, "-I", "-S", str(loader)],
                    env=child_env,
                    cwd=home,
                    capture_output=True,
                    check=False,
                )

            atomic_write_private(source, assignments)
            legacy = run_loader()
            self.assertEqual(legacy.returncode, 0, legacy.stderr)
            self.assertEqual(legacy.stdout, b"ENVMAN=legitimate variable\nCOMMENTED=  space $PATH $(id) = value  \nEMPTY=\n")

            key_path = state / "envman" / "storage.key"
            key = load_or_create_file_key(key_path, create=True)
            downgrade = run_loader()
            self.assertNotEqual(downgrade.returncode, 0)
            self.assertEqual(downgrade.stdout, b"")
            encrypted = encrypt_document(assignments, key)
            atomic_write_private(source, encrypted)
            loaded = run_loader()
            self.assertEqual(loaded.returncode, 0, loaded.stderr)
            self.assertEqual(loaded.stdout, legacy.stdout)
            self.assertNotIn(b"space $PATH", source.read_bytes())

            key_path.write_bytes(Fernet.generate_key())
            wrong_key = run_loader()
            self.assertNotEqual(wrong_key.returncode, 0)
            self.assertEqual(wrong_key.stdout, b"")
            self.assertNotIn(b"space $PATH", wrong_key.stderr)


if __name__ == "__main__":
    unittest.main()
