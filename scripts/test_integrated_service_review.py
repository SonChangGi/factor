"""Independent integration regressions; run with python -m unittest discover -s scripts -p test_integrated_service_review.py."""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import json
import threading
import unittest
from unittest.mock import Mock, patch
from momentum_factor_lab import integrated_service as service


def result_fixture():
    return {
        "schemaVersion": "integrated-factor/v1",
        "selection": {"history": []},
        "factors": [{"id": "MOM12_1"}],
        "registry": [{"id": "MOM12_1"}],
        "resultIdentity": {"resultId": "source", "inputHash": "snapshot"},
        "data": {},
    }


class ServiceReview(unittest.TestCase):
    def test_generated_site_resolves_its_asset_paths(self):
        import re

        with TemporaryDirectory() as tmp:
            service.build_site(tmp, result_fixture())
            page = (Path(tmp) / "index.html").read_text()
            for relative in re.findall(r'(?:href|src)="(assets/[^"?]+)', page):
                self.assertTrue((Path(tmp) / relative).is_file(), relative)

    def test_explicit_false_clears_previous_common_universe_setting(self):
        with (
            TemporaryDirectory() as tmp,
            patch.object(service, "data_inventory", return_value=[]),
            patch(
                "momentum_factor_lab.integrated_engine.run_integrated_analysis",
                return_value=result_fixture(),
            ) as run,
        ):
            service.execute_run(
                SimpleNamespace(metadata={}),
                {"common_universe": True, "comparison_factors": ["MOM12_1"]},
                tmp,
                comparison_factors=["MOM12_1"],
                common_universe=False,
            )
            self.assertFalse(run.call_args.args[1].common_universe)

    def test_existing_result_is_not_silently_replaced(self):
        with (
            TemporaryDirectory() as tmp,
            patch(
                "momentum_factor_lab.integrated_engine.run_integrated_analysis",
                return_value=result_fixture(),
            ),
        ):
            target = Path(tmp) / "result.json"
            original = '{"preserve":"existing validated result"}'
            target.write_text(original)
            with self.assertRaises((ValueError, FileExistsError)):
                service.execute_run(SimpleNamespace(metadata={}), {}, tmp)
            self.assertEqual(target.read_text(), original)

    def manager(self, tmp):
        manager = service.ResearchRuns.__new__(service.ResearchRuns)
        manager.market = SimpleNamespace(metadata={"snapshotId": "s"})
        manager.directory = Path(tmp)
        manager.executor = Mock()
        manager.lock = threading.Lock()
        return manager

    def test_malformed_comparison_rejected_before_job_created(self):
        for comparison in ("MOM12_1", {"id": "MOM12_1"}, ["UNKNOWN"]):
            with self.subTest(comparison=comparison), TemporaryDirectory() as tmp:
                manager = self.manager(tmp)
                with self.assertRaises((ValueError, TypeError)):
                    manager.submit(
                        {"settings": {}, "comparisonFactors": comparison, "commonUniverse": True}
                    )
                self.assertFalse(list(Path(tmp).glob("*/status.json")))
                manager.executor.submit.assert_not_called()

    def test_async_failure_leaves_published_payload_intact(self):
        with TemporaryDirectory() as tmp:
            manager = self.manager(tmp)
            baseline = Path(tmp) / "last-good.json"
            baseline.write_text('{"sentinel":true}')
            status = {
                "runId": "1" * 32,
                "status": "queued",
                "request": {},
                "createdAt": "2026-10-19T00:00:00Z",
            }
            with patch.object(service, "execute_run", side_effect=ValueError("missing price")):
                manager._run(status)
            self.assertEqual(
                json.loads((Path(tmp) / status["runId"] / "status.json").read_text())["status"],
                "failed",
            )
            self.assertEqual(baseline.read_text(), '{"sentinel":true}')
            self.assertFalse((Path(tmp) / status["runId"] / "result.json").exists())

    def test_legacy_best_fields_rejected(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                self.manager(tmp).submit({"factor": "Momentum_252", "market_cap_min": 500000000})


if __name__ == "__main__":
    unittest.main()
