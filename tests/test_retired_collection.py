"""Retired collectors cannot be invoked; frozen financial proofs still validate."""
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path

import pytest

from factor_lab.cli import build_parser
from factor_lab.config import RunConfig
from factor_lab.data import load_market_data
from factor_lab.integrated_validation import validate_runtime_lock


@pytest.mark.parametrize("argv", [
    ["run", "--live"], ["integrated-collect", "--output", "unused"],
    ["scheduled-dashboard"], ["serve-local-api", "--live"],
])
def test_retired_collection_commands_fail_before_execution(argv):
    with pytest.raises(SystemExit) as error:
        build_parser().parse_args(argv)
    assert error.value.code == 2


def test_historical_live_config_cannot_trigger_new_acquisition(monkeypatch):
    import urllib.request

    def unexpected(*args, **kwargs):
        pytest.fail("Retired collector attempted a network request")

    monkeypatch.setattr(urllib.request, "urlopen", unexpected)
    with pytest.raises(ValueError, match="Legacy live collection has been removed"):
        load_market_data(RunConfig(live=True))
    assert importlib.util.find_spec("factor_lab.live_data") is None


def test_retired_workflows_and_saved_live_configuration_are_absent():
    root = Path(__file__).resolve().parents[1]
    for name in ("daily-dashboard", "daily-dashboard-watchdog", "controlled-analysis",
                 "reviewed-universe"):
        assert not (root / ".github/workflows" / f"{name}.yml").exists()
    assert not (root / ".github/factor-dashboard-config.json").exists()
    assert (root / ".github/workflows/deploy-pages.yml").is_file()


def test_offline_runtime_and_historical_runtime_each_require_their_exact_lock():
    core = {"numpy", "pandas", "exchange-calendars", "rfc8785"}
    for names in (core, core | {"yfinance", "finance-datareader"}):
        lock = "".join(f'[[package]]\nname = "{name}"\nversion = "1.2.3"\n\n'
                       for name in sorted(names)).encode()
        identity = {"runtime": {"pythonVersion": "3.11.10",
                    "dependencyLockHash": hashlib.sha256(lock).hexdigest(),
                    "packageVersions": dict.fromkeys(names, "1.2.3")}}
        validate_runtime_lock(identity, lock)
        missing = deepcopy(identity)
        missing["runtime"]["packageVersions"].pop("pandas")
        with pytest.raises(ValueError, match="Runtime package catalog"):
            validate_runtime_lock(missing, lock)
        changed = deepcopy(identity)
        changed["runtime"]["packageVersions"]["pandas"] = "1.2.4"
        with pytest.raises(ValueError, match="Runtime packages differ"):
            validate_runtime_lock(changed, lock)
