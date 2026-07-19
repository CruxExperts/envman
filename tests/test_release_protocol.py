from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import tempfile
import unittest
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from envman import _release_protocol as release
from scripts.render_installer import render


def wheel_bytes(version: str = "0.1.0") -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(f"envman-{version}.dist-info/METADATA", f"Metadata-Version: 2.1\nName: envman\nVersion: {version}\n")
        archive.writestr("envman/__init__.py", "")
    return output.getvalue()


def asset(filename: str, body: bytes, version: str = "0.1.0") -> dict[str, object]:
    return {
        "filename": filename,
        "url": f"https://github.com/CruxExperts/envman/releases/download/v{version}/{filename}",
        "sha256": hashlib.sha256(body).hexdigest(),
        "size": len(body),
    }


def manifest_bytes(version: str = "0.1.0") -> tuple[bytes, dict[str, bytes]]:
    wheel = wheel_bytes(version)
    constraints = b"cryptography==49.0.0\ncffi==2.1.0\npycparser==3.0\n"
    payload = {
        "schema": release.MANIFEST_SCHEMA,
        "schema_version": 1,
        "version": version,
        "repository": release.REPOSITORY,
        "compatibility": {"python": ">=3.12,<3.13", "platform": "linux-x86_64", "uv": ">=0.11,<0.12"},
        "assets": {"wheel": asset(f"envman-{version}-py3-none-any.whl", wheel, version), "runtime_constraints": asset("runtime-constraints.txt", constraints, version)},
    }
    encoded = json.dumps(payload).encode()
    bodies = {payload["assets"]["wheel"]["url"]: wheel, payload["assets"]["runtime_constraints"]["url"]: constraints}
    return encoded, bodies


class ReleaseProtocolTests(unittest.TestCase):
    def test_manifest_accepts_exact_schema_and_assets(self) -> None:
        encoded, _ = manifest_bytes()
        parsed = release.parse_manifest(encoded)
        self.assertEqual(parsed.version, "0.1.0")
        self.assertEqual(parsed.constraints.filename, "runtime-constraints.txt")


    def test_installed_package_version_comes_from_distribution_metadata(self) -> None:
        from envman import cli

        self.assertEqual(cli.app_version(), "0.1.0")
    def test_manifest_rejects_non_github_asset_url(self) -> None:
        encoded, _ = manifest_bytes()
        payload = json.loads(encoded)
        payload["assets"]["wheel"]["url"] = "https://example.test/envman.whl"
        with self.assertRaises(release.ReleaseProtocolError):
            release.parse_manifest(json.dumps(payload).encode())

    def test_download_rejects_hash_mismatch(self) -> None:
        body = b"body"
        candidate = release.Asset("candidate", "https://github.com/CruxExperts/envman/releases/download/v0.1.0/candidate", "0" * 64, len(body))
        with self.assertRaises(release.ReleaseProtocolError):
            release.download_asset(candidate, transport=lambda _url, _limit: body, maximum_size=release.CONSTRAINTS_LIMIT)

    def test_wheel_metadata_must_match_manifest_version(self) -> None:
        with self.assertRaises(release.ReleaseProtocolError):
            release.validate_wheel(wheel_bytes("0.1.0"), "0.1.1")

    def test_constraints_require_exact_pins_and_cryptography(self) -> None:
        release.validate_constraints(b"cryptography==49.0.0\n")
        with self.assertRaises(release.ReleaseProtocolError):
            release.validate_constraints(b"cryptography>=49\n")

    def test_receipt_is_private_and_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = release.InstallReceipt("0.1.0", "github-release-wheel", release.REPOSITORY, release.LATEST_MANIFEST_URL, release.Asset("envman.whl", "https://github.com/CruxExperts/envman/releases/download/v0.1.0/envman.whl", "a" * 64, 1), release.Asset("runtime-constraints.txt", "https://github.com/CruxExperts/envman/releases/download/v0.1.0/runtime-constraints.txt", "b" * 64, 1), "0.1.0", "0.11.21", "2026-07-19T00:00:00Z")
            path = root / "state" / "install.json"
            release.write_receipt(receipt, path)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(release.read_receipt(path).installed_version, "0.1.0")
            path.unlink()
            path.symlink_to(root / "missing")
            with self.assertRaises(release.ReleaseProtocolError):
                release.read_receipt(path)

    def test_update_reports_current_and_refuses_downgrade(self) -> None:
        encoded, bodies = manifest_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "state"
            receipt = release.InstallReceipt("0.1.0", "github-release-wheel", release.REPOSITORY, "https://fixture.test/manifest", release.Asset("envman-0.1.0-py3-none-any.whl", "https://github.com/CruxExperts/envman/releases/download/v0.1.0/envman-0.1.0-py3-none-any.whl", hashlib.sha256(bodies["https://github.com/CruxExperts/envman/releases/download/v0.1.0/envman-0.1.0-py3-none-any.whl"]).hexdigest(), len(bodies["https://github.com/CruxExperts/envman/releases/download/v0.1.0/envman-0.1.0-py3-none-any.whl"])), release.Asset("runtime-constraints.txt", "https://github.com/CruxExperts/envman/releases/download/v0.1.0/runtime-constraints.txt", hashlib.sha256(bodies["https://github.com/CruxExperts/envman/releases/download/v0.1.0/runtime-constraints.txt"]).hexdigest(), len(bodies["https://github.com/CruxExperts/envman/releases/download/v0.1.0/runtime-constraints.txt"])), "0.1.0", "0.11.21", "2026-07-19T00:00:00Z")
            release.write_receipt(receipt, release.receipt_path(state))
            def transport(url: str, _limit: int) -> bytes:
                return encoded if url == "https://fixture.test/manifest" else bodies[url]
            result = release.update(check_only=True, transport=transport, state_root=state)
            self.assertEqual(result["status"], "current")
            older, _ = manifest_bytes("0.0.9")
            with self.assertRaises(release.ReleaseProtocolError):
                release.update(check_only=True, transport=lambda url, limit: older if url == "https://fixture.test/manifest" else transport(url, limit), state_root=state)

    def test_generated_installer_contains_exact_protocol_and_pep723_metadata(self) -> None:
        installer = render()
        protocol = (Path(__file__).parents[1] / "src" / "envman" / "_release_protocol.py").read_text(encoding="utf-8")
        self.assertIn('# requires-python = ">=3.12,<3.13"', installer)
        self.assertIn("# dependencies = []", installer)
        self.assertIn(protocol, installer)


if __name__ == "__main__":
    unittest.main()
