import numpy as np
import pandas as pd
import pytest
from factor_lab.integrated_data import (
    IntegratedMarket,
    compute_eligibility,
    integrated_universe,
    save_integrated_market,
    load_integrated_market,
)


def test_frozen_union_explains_every_membership():
    rows = integrated_universe()["symbols"]
    assert len(rows) == 2960
    assert sum(r["momentum"] for r in rows) == 2865
    assert sum(r["best"] for r in rows) == 1766
    assert sum(r["best"] and not r["momentum"] for r in rows) == 95
    assert len({r["symbol"] for r in rows}) == 2960


def test_eligibility_uses_observed_dollar_volume_and_excludes_benchmark():
    ix = pd.bdate_range("2020-01-01", periods=260)
    p = pd.DataFrame(10.0, index=ix, columns=["A", "B", "SPY"])
    v = pd.DataFrame(600000.0, index=ix, columns=p.columns)
    v["B"] = 400000.0
    e = compute_eligibility(p, p, v)
    assert not e.iloc[250].any()
    assert e.iloc[-1].to_dict() == {"A": True, "B": False, "SPY": False}
    p.iloc[-1, 0] = np.nan
    assert not compute_eligibility(p, p, v).iloc[-1, 0]


def test_snapshot_round_trip_and_tamper_failure(tmp_path):
    p = pd.DataFrame({"A": [10.0, 11.0]}, index=pd.bdate_range("2020-01-01", periods=2))
    m = IntegratedMarket(p, p, p, p, p, p, p * 0, p * 0, p.gt(0), {"requestedSymbols": ["A"]})
    save_integrated_market(m, tmp_path)
    pd.testing.assert_frame_equal(load_integrated_market(tmp_path).prices, p, check_freq=False)
    with pytest.raises(FileExistsError):
        save_integrated_market(m, tmp_path)
    path = tmp_path / "prices.csv.gz"
    path.write_bytes(path.read_bytes() + b"x")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_integrated_market(tmp_path)


def test_partial_batch_retries_symbol_and_retains_field_pairing(tmp_path, monkeypatch):
    import yfinance as yf
    from factor_lab.integrated_data import collect_integrated_market

    calls = []

    def download(symbols, **kwargs):
        calls.append(list(symbols))
        ix = pd.bdate_range("2025-01-01", periods=4)
        values = {}
        for symbol in symbols:
            for field, value in [
                ("Adj Close", 9.0),
                ("Close", 10.0),
                ("Open", 9.5),
                ("High", 11.0),
                ("Low", 9.0),
                ("Volume", 2e6),
                ("Dividends", 0.0),
                ("Stock Splits", 0.0),
            ]:
                values[field, symbol] = np.nan if symbol == "A" and len(symbols) > 1 else value
        return pd.DataFrame(values, index=ix)

    monkeypatch.setattr(yf, "download", download)
    m = collect_integrated_market(tmp_path, start="2025-01-01", end="2025-02-01", symbols=["A"])
    assert ["A"] in calls
    assert m.metadata["failedSymbols"] == {}
    assert (m.dollar_volumes.A == 20e6).all()
    assert (m.prices.A == 9).all()
    assert len(m.metadata["receipts"]) == 2


def test_collector_does_not_admit_unverified_zero_volume_valuations(tmp_path, monkeypatch):
    import yfinance as yf
    from factor_lab.integrated_data import collect_integrated_market

    def download(symbols, **kwargs):
        ix = pd.bdate_range("2025-01-01", periods=4)
        values = {}
        for symbol in symbols:
            for field, value in [("Adj Close", 9.), ("Close", 10.), ("Open", 9.5),
                                 ("High", 11.), ("Low", 9.), ("Volume", 2e6),
                                 ("Dividends", 0.), ("Stock Splits", 0.)]:
                column = np.full(len(ix), value)
                if symbol == "A" and field == "Volume":
                    column[1] = 0.
                values[field, symbol] = column
        return pd.DataFrame(values, index=ix)

    monkeypatch.setattr(yf, "download", download)
    result = collect_integrated_market(tmp_path, start="2025-01-01", end="2025-02-01", symbols=["A"])
    assert pd.isna(result.prices.A.iloc[1])
    assert pd.isna(result.valuation_prices.A.iloc[1])
    assert result.metadata["unadmittedNonTradingMarkCount"] == 1
    cached = pd.read_csv(next((tmp_path / "downloads").glob("*.csv.gz")), header=[0, 1], index_col=0)
    assert cached["Adj Close", "A"].iloc[1] == 9.
    assert cached["Volume", "A"].iloc[1] == 0.


def test_original_accounting_matches_explicit_targets_on_same_snapshot():
    """Protect the new external-target boundary with legacy allocation/accounting."""
    from factor_lab.backtest import run_factor_backtest, _rebalance_dates
    from factor_lab.config import RunConfig, FIXED_WEIGHTING_POLICY
    from factor_lab.portfolio import construct_target_allocation
    from factor_lab.factors import compute_factor_scores

    ix = pd.bdate_range("2020-01-01", periods=370)
    t = np.arange(len(ix))[:, None]
    j = np.arange(24)[None, :]
    p = pd.DataFrame(
        30 * np.exp(0.0002 * t + 0.02 * np.sin(t / (8 + j)) + j * 0.02),
        index=ix,
        columns=[f"S{k}" for k in range(24)],
    )
    v = p * 0 + 2e6
    e = compute_eligibility(p, p, v)
    config = RunConfig(start_date="2020-01-01", end_date=str(ix[-1].date()))
    scores = compute_factor_scores(p, eligibility_mask=e)
    adv = (p * v).rolling(63, min_periods=42).mean()
    for name in ("mom_12_1", "dual_momentum", "price_efficiency"):
        panel = scores[name]
        original = run_factor_backtest(
            name,
            FIXED_WEIGHTING_POLICY,
            p,
            panel,
            config,
            eligibility_mask=e,
            trailing_dollar_volume=adv,
        )
        targets = {
            d: construct_target_allocation(
                FIXED_WEIGHTING_POLICY,
                d,
                panel.loc[d],
                p.loc[d],
                e.loc[d],
                config,
                trailing_dollar_volume=adv.loc[d],
            )
            for d in _rebalance_dates(ix, "ME")
        }
        integrated = run_factor_backtest(
            name,
            FIXED_WEIGHTING_POLICY,
            p,
            panel,
            config,
            eligibility_mask=e,
            trailing_dollar_volume=adv,
            signal_targets=targets,
        )
        for field in (
            "returns",
            "equity",
            "cash_weights",
            "turnover",
            "costs",
            "signal_dates",
            "valuation_available",
        ):
            pd.testing.assert_series_equal(getattr(original, field), getattr(integrated, field))
        pd.testing.assert_frame_equal(original.weights, integrated.weights)


def test_as_traded_reconstruction_excludes_split_day_and_preserves_dollars(tmp_path):
    from factor_lab.integrated_data import reconstruct_as_traded

    ix = pd.bdate_range("2020-01-01", periods=260)
    # Economic price is $8 before, $2 after the 4:1 event; all provider
    # historical bars use the post-split $2 basis and 400 adjusted shares.
    p = pd.DataFrame(2.0, index=ix, columns=["A"])
    v = p * 0 + 400
    splits = p * 0
    splits.iloc[-2, 0] = 4
    m = IntegratedMarket(p, p, p, p, p, v, p * 0, splits, p.notna(), {"requestedSymbols": ["A"]})
    raw = reconstruct_as_traded(m)
    assert raw.raw_close.iloc[-3, 0] == 8
    assert raw.raw_close.iloc[-2, 0] == 2
    assert raw.volumes.iloc[-3, 0] == 100
    assert raw.volumes.iloc[-2, 0] == 400
    pd.testing.assert_frame_equal(raw.raw_close * raw.volumes, p * v)
    pd.testing.assert_frame_equal(raw.split_close, p)
    save_integrated_market(raw, tmp_path)
    restored = load_integrated_market(tmp_path)
    pd.testing.assert_frame_equal(restored.split_close, p, check_freq=False)
    pd.testing.assert_frame_equal(restored.raw_close, raw.raw_close, check_freq=False)


def test_future_split_and_rescaled_provider_history_preserve_past_price_floor():
    from factor_lab.integrated_data import reconstruct_as_traded

    ix = pd.bdate_range("2020-01-01", periods=270)
    p = pd.DataFrame(8.0, index=ix, columns=["A"])
    v = p * 0 + 1_000_000
    first = IntegratedMarket(p, p, p, p, p, v, p * 0, p * 0, p.notna(), {"requestedSymbols": ["A"]})
    old = reconstruct_as_traded(first)
    # A later snapshot contains a newly observed 4:1 split, with Yahoo's
    # earlier OHLC/volume retroactively rescaled. Economic old bars stay equal.
    split = p * 0
    split.iloc[-1, 0] = 4
    provider = p / 4
    volume = v * 4
    later = IntegratedMarket(
        provider,
        provider,
        provider,
        provider,
        provider,
        volume,
        p * 0,
        split,
        p.notna(),
        {"requestedSymbols": ["A"]},
    )
    new = reconstruct_as_traded(later)
    pd.testing.assert_frame_equal(old.raw_close.iloc[:-1], new.raw_close.iloc[:-1])
    pd.testing.assert_frame_equal(old.volumes.iloc[:-1], new.volumes.iloc[:-1])
    pd.testing.assert_frame_equal(old.eligibility.iloc[:-1], new.eligibility.iloc[:-1])
    split.iloc[1, 0] = -2
    with pytest.raises(ValueError, match="Invalid split ratio"):
        reconstruct_as_traded(later)


def test_historical_collection_uses_future_actions_before_clipping(tmp_path, monkeypatch):
    import yfinance as yf
    from factor_lab.integrated_data import collect_integrated_market

    seen = []

    def download(symbols, **kwargs):
        seen.append(kwargs["end"])
        ix = pd.to_datetime(["2025-01-30", "2025-01-31", "2025-02-03"])
        values = {}
        for symbol in symbols:
            for field, value in [
                ("Adj Close", 2.0),
                ("Close", 2.0),
                ("Open", 2.0),
                ("High", 2.0),
                ("Low", 2.0),
                ("Volume", 4e6),
                ("Dividends", 0.0),
                ("Stock Splits", 0.0),
            ]:
                values[field, symbol] = [value] * 3
            if symbol == "A":
                values["Stock Splits", symbol] = [0.0, 0.0, 4.0]
        return pd.DataFrame(values, index=ix)

    monkeypatch.setattr(yf, "download", download)
    m = collect_integrated_market(tmp_path, start="2025-01-01", end="2025-02-01", symbols=["A"])
    assert all(pd.Timestamp(end) > pd.Timestamp("2025-02-03") for end in seen)
    assert m.prices.index.max() == pd.Timestamp("2025-01-31")
    assert (m.raw_close.A == 8).all()
    assert (m.volumes.A == 1e6).all()
    assert m.metadata["splitActionsAfterOutputEnd"] == [
        {"date": "2025-02-03", "symbol": "A", "ratio": 4.0}
    ]


def test_quality_quarantines_shape_inputs_preserving_close_and_sources(tmp_path):
    from factor_lab.integrated_data import apply_market_quality

    ix = pd.bdate_range("2020-01-01", periods=3)
    close = pd.DataFrame({"A": [10.0, 11.0, 12.0], "EMPTY": [np.nan] * 3}, index=ix)
    opening = close.copy()
    opening.iloc[1, 0] = 20.0
    m = IntegratedMarket(
        close,
        close,
        opening,
        close + 1,
        close - 1,
        close * 0 + 1e6,
        close * 0,
        close * 0,
        close.notna(),
        {"requestedSymbols": ["A", "EMPTY"], "snapshotId": "parent"},
    )
    original = m.prices.copy()
    m = apply_market_quality(m)
    assert len(m.metadata["quarantinedOHLC"]) == 1
    assert not m.shape_valid.iloc[1, 0]
    for field in ("split_open", "split_high", "split_low"):
        assert np.isnan(getattr(m, field).iloc[1, 0])
    assert m.raw_open.iloc[1, 0] == 20
    assert m.split_close.iloc[1, 0] == 11
    pd.testing.assert_frame_equal(m.prices, original)
    assert m.metadata["failedSymbols"] == {
        "EMPTY": "No positive-volume price observations after quality filtering"
    }
    assert m.metadata["parentSnapshotId"] == "parent"
    save_integrated_market(m, tmp_path)
    restored = load_integrated_market(tmp_path)
    pd.testing.assert_frame_equal(restored.shape_valid, m.shape_valid, check_freq=False)


def test_nonempty_truncated_batch_is_retried_as_full_paired_history(tmp_path, monkeypatch):
    import yfinance as yf
    from factor_lab.integrated_data import collect_integrated_market
    calls = []
    def download(symbols, **kwargs):
        calls.append(list(symbols))
        dates = pd.bdate_range('2025-01-01', periods=4)
        fields = {'Adj Close':9.,'Close':10.,'Open':9.5,'High':11.,'Low':9.,
                  'Volume':2e6,'Dividends':0.,'Stock Splits':0.}
        columns = {(field,symbol):[value]*4 for symbol in symbols for field,value in fields.items()}
        frame = pd.DataFrame(columns,index=dates)
        if len(symbols)>1:
            frame.loc[dates[:-1],pd.IndexSlice[:, 'A']] = np.nan
        return frame
    monkeypatch.setattr(yf,'download',download)
    reference={'A':dict(observations=4,firstObservation='2025-01-01',asOf='2025-01-06')}
    market=collect_integrated_market(tmp_path,start='2025-01-01',end='2025-02-01',symbols=['A'],reference_coverage=reference)
    assert ['A'] in calls and market.prices.A.notna().sum()==4
    assert (market.raw_close.A*market.volumes.A==20e6).all()
    assert market.metadata['inputCoverage']['A']['observations']==4
    assert market.metadata['receipts'][-1]['retryReason']['reason']=='truncated_positive_volume_history'


def test_persistent_truncated_history_blocks_snapshot_before_calculation(tmp_path,monkeypatch):
    import yfinance as yf
    from factor_lab.integrated_data import collect_integrated_market
    monkeypatch.setattr('factor_lab.integrated_data.time.sleep',lambda *a:None)
    def download(symbols,**kwargs):
        dates=pd.bdate_range('2025-01-01',periods=4)
        fields={'Adj Close':9.,'Close':10.,'Open':9.5,'High':11.,'Low':9.,'Volume':2e6,'Dividends':0.,'Stock Splits':0.}
        frame=pd.DataFrame({(field,symbol):[value]*4 for symbol in symbols for field,value in fields.items()},index=dates)
        frame.loc[dates[:-1],pd.IndexSlice[:,'A']]=np.nan
        return frame
    monkeypatch.setattr(yf,'download',download)
    with pytest.raises(ValueError,match='Truncated historical input remains'):
        collect_integrated_market(tmp_path,start='2025-01-01',end='2025-02-01',symbols=['A'],
            reference_coverage={'A':dict(observations=4,firstObservation='2025-01-01',asOf='2025-01-06')})
    assert not (tmp_path/'manifest.json').exists()
    assert (tmp_path/'history-coverage-failure.json').exists()
    assert len(list((tmp_path/'downloads').glob('single-*-coverage*.csv.gz')))==2


def test_new_session_does_not_mask_loss_of_old_observation():
    from factor_lab.integrated_data import history_coverage_issue
    dates=pd.to_datetime(['2025-01-02','2025-01-03','2025-01-06'])
    frame=pd.DataFrame({('Adj Close','A'):[10.]*3,('Volume','A'):[100.]*3},index=dates)
    expected={'A':dict(observations=3,firstObservation='2025-01-01',asOf='2025-01-03')}
    assert history_coverage_issue(frame,'A',expected)['observed']['observations']==2


def test_immutable_snapshot_rechecks_reference_prefix_not_total_count(tmp_path):
    from factor_lab.integrated_data import save_integrated_market,collect_integrated_market
    dates=pd.to_datetime(['2025-01-02','2025-01-03','2025-01-06'])
    prices=pd.DataFrame({'A':[10.]*3},index=dates)
    volumes=prices*0+100
    from factor_lab.integrated_listing import listing_context
    market=IntegratedMarket(prices,prices,prices,prices,prices,volumes,prices*0,prices*0,
        prices.notna(),dict(request=dict(start='2025-01-01',endExclusive='2025-02-01',symbols=['A'],
            listing=listing_context(['A'],'2025-01-31')),
        inputCoverage={'A':dict(observations=3,firstObservation='2025-01-02',asOf='2025-01-06')}))
    save_integrated_market(market,tmp_path)
    with pytest.raises(ValueError,match='Immutable snapshot has truncated'):
        collect_integrated_market(tmp_path,start='2025-01-01',end='2025-02-01',symbols=['A'],
            reference_coverage={'A':dict(observations=3,firstObservation='2025-01-01',asOf='2025-01-03')})
