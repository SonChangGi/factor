from dataclasses import replace

import numpy as np
import pandas as pd

from factor_lab.integrated_data import IntegratedMarket
from factor_lab import integrated_engine as engine
from factor_lab.portfolio import TargetAllocation
from factor_lab.config import FIXED_WEIGHTING_POLICY


def inputs():
    dates = pd.bdate_range("2020-01-01", periods=130)
    rng = np.random.default_rng(28)
    columns = [f"S{i}" for i in range(20)] + ["SPY"]
    prices = pd.DataFrame(100 * np.cumprod(
        1 + rng.normal(0.001, 0.007, (len(dates), len(columns))), axis=0),
        index=dates, columns=columns)
    volumes = prices * 0 + 1_000_000
    eligible = prices.notna()
    eligible["SPY"] = False
    market = IntegratedMarket(
        prices, prices, prices, prices, prices, volumes,
        prices * 0, prices * 0, eligible,
        {"snapshotId": "stress-efficiency", "requestedSymbols": columns[:-1]},
    )
    ranks = pd.DataFrame(np.tile(np.arange(len(columns)), (len(dates), 1)),
                         index=dates, columns=columns)
    panels = {"MOM12_1": ranks, "VOL252": -ranks}
    config = engine.IntegratedConfig(start_date="2020-01-01", evaluation_window_days=21,
                                     bootstrap_repetitions=0, top_n=10)
    return market, config, panels


def original_targets(run):
    return {
        pd.Timestamp(row["signalDate"]): TargetAllocation(
            FIXED_WEIGHTING_POLICY, pd.Timestamp(row["signalDate"]),
            rows=pd.DataFrame(row["targetHoldings"]), status="available",
        )
        for row in run["selection"]["history"] if row["status"] in ("selected", "cash")
    }


def test_monthly_signal_cache_and_skipped_diagnostics_preserve_financial_results():
    market, config, panels = inputs()
    reference = engine.run_integrated_analysis(market, config, panels)
    monthly = engine.completed_monthends(market.prices.index)
    sparse = {key: value.reindex(monthly) for key, value in panels.items()}
    fast = engine.run_integrated_analysis(market, config, sparse, research_diagnostics=False)
    assert reference["selection"] == fast["selection"]
    assert reference["comparisons"] == fast["comparisons"]
    for before, after in zip(reference["factors"], fast["factors"]):
        for key in ("nav", "drawdown", "metrics", "history", "holdings", "cashWeight"):
            assert before[key] == after[key]
    assert reference["resultIdentity"] == fast["resultIdentity"]
    assert any(row["holdings"] for row in fast["selection"]["history"])


def test_all_stress_outputs_match_the_previous_full_research_path(monkeypatch):
    market, config, panels = inputs()
    base = engine.run_integrated_analysis(market, config, panels)
    targets = original_targets(base)
    original = engine.run_integrated_analysis

    def with_full_research(*args, **kwargs):
        kwargs["research_diagnostics"] = True
        return original(*args, **kwargs)

    monkeypatch.setattr(engine, "run_integrated_analysis", with_full_research)
    reference = engine.run_stress_suite(market, config, panels, frozen_targets=targets,
                                       source_result_id="original")
    monkeypatch.setattr(engine, "run_integrated_analysis", original)
    monthly = engine.completed_monthends(market.prices.index)
    sparse = {key: value.reindex(monthly) for key, value in panels.items()}
    events = []
    fast = engine.run_stress_suite(market, config, sparse, frozen_targets=targets,
                                  source_result_id="original", progress_callback=events.append)
    assert reference == fast
    assert len({row["metrics"]["cagr"] for row in fast}) > 1
    assert len([e for e in events if e["stage"] == "stress" and e["status"] == "started"]) == 7
    assert len([e for e in events if e["stage"] == "factor"]) == 6 * len(panels)
    assert {e["scenarioId"] for e in events if e["stage"] == "factor"} == {
        "cost20", "cost40", "delay2", "top10", "top30", "equal"}
    assert events[-1] == {"stage": "stress", "id": "fixed_choice_delay2", "status": "completed",
                          "completed": 7, "total": 7}


def test_normal_full_run_builds_factor_panels_and_research_only_once(monkeypatch):
    import factor_lab.integrated_factors as factors
    import factor_lab.integrated_research as research

    market, config, panels = inputs()
    counts = {"panels": 0, "research": 0, "ic": 0}
    definitions = [d for d in factors.factor_registry() if d["id"] in panels]
    monkeypatch.setattr(factors, "factor_registry", lambda: definitions)

    def calculated(market):
        counts["panels"] += 1
        yield from panels.items()

    original_research = engine.build_research
    original_ic = research.monthly_signal_diagnostics

    def build(*args, **kwargs):
        counts["research"] += 1
        return original_research(*args, **kwargs)

    def ic(*args, **kwargs):
        counts["ic"] += 1
        return original_ic(*args, **kwargs)

    monkeypatch.setattr(factors, "iter_integrated_factors", calculated)
    monkeypatch.setattr(engine, "build_research", build)
    monkeypatch.setattr(research, "monthly_signal_diagnostics", ic)
    # The engine imports this function at module scope.
    monkeypatch.setattr(engine, "monthly_signal_diagnostics", ic)
    result = engine.run_integrated_analysis(market, replace(config, run_stress=True))
    assert len(result["research"]["stress"]) == 7
    assert counts == {"panels": 1, "research": 1, "ic": 2}
