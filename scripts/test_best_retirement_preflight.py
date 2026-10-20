"""The retirement helper only checks manifests; it cannot delete anything."""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from verify_best_retirement import check


class RetirementPreflight(unittest.TestCase):
    def fixture(self, root):
        candidate = root / "old-best.json"
        candidate.write_text('{"old":true}')
        protected = root / "workflow.yml"
        protected.write_text("preserved")
        st = candidate.stat()
        identity = {key: key for key in ("resultId", "inputHash", "codeHash")}
        manifest = {
            "schemaVersion": "best-cleanup-manifest/v1",
            "files": [
                {
                    "path": str(candidate),
                    "size": st.st_size,
                    "inode": st.st_ino,
                    "mtimeNs": st.st_mtime_ns,
                    "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
                }
            ],
        }
        validation = {
            "schemaVersion": "integration-validation/v1",
            "resultIdentity": identity,
            "checks": {k: True for k in ("data", "parity", "engine", "api", "ui", "stress")},
            "protectedHashes": {str(protected): hashlib.sha256(protected.read_bytes()).hexdigest()},
        }
        return (
            candidate,
            protected,
            manifest,
            validation,
            {"schemaVersion": "integrated-factor/v1", "resultIdentity": identity},
        )

    def test_ready_dry_run_preserves_all_files(self):
        with (
            TemporaryDirectory() as tmp,
            patch(
                "verify_best_retirement.subprocess.run",
                return_value=SimpleNamespace(returncode=1, stdout=""),
            ),
        ):
            candidate, protected, manifest, validation, result = self.fixture(Path(tmp).resolve())
            report = check(manifest, validation, result)
            self.assertTrue(report["ready"])
            self.assertFalse(report["applySupported"])
            self.assertTrue(candidate.exists())
            self.assertEqual(protected.read_text(), "preserved")

    def test_missing_gate_and_changed_candidate_are_rejected(self):
        with (
            TemporaryDirectory() as tmp,
            patch(
                "verify_best_retirement.subprocess.run",
                return_value=SimpleNamespace(returncode=1, stdout=""),
            ),
        ):
            candidate, _, manifest, validation, result = self.fixture(Path(tmp).resolve())
            validation["checks"]["stress"] = False
            candidate.write_text("changed")
            report = check(manifest, validation, result)
            self.assertFalse(report["ready"])
            self.assertTrue(any("stress" in e for e in report["failures"]))
            self.assertTrue(any("identity changed" in e for e in report["failures"]))
            self.assertEqual(candidate.read_text(), "changed")


if __name__ == "__main__":
    unittest.main()
