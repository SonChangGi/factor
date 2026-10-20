"""Time-aligned research diagnostics; no diagnostic changes a trading rule."""

from __future__ import annotations
import numpy as np
import pandas as pd


def forward_security_returns(prices, entry, exit, valuation_prices=None, corporate_actions=()):
    """A bought security's terminal value, including mandatory successor units.

    Entry always requires an executable close. A sourced non-trading end mark
    can value the position; a successor replaces the original asset, rather
    than turning an absent predecessor quote into cash or a missing return.
    """
    marks = prices if valuation_prices is None else valuation_prices.reindex_like(prices)
    result = marks.loc[exit] / prices.loc[entry] - 1
    relevant = sorted((r for r in corporate_actions if entry < pd.Timestamp(r["date"]) <= exit),
                      key=lambda r: r["date"])
    origins = {r["symbol"] for r in relevant if r["symbol"] in prices}
    for origin in origins:
        symbol, units, cash = origin, 1., 0.
        for row in relevant:
            if row["symbol"] == symbol:
                cash += units * row.get("cashPerUnit", 0.)
                units *= row["unitRatio"]
                symbol = row["targetSymbol"]
        end_value = cash if units == 0 else (
            units * marks.at[exit, symbol] + cash if symbol in marks else np.nan
        )
        result[origin] = end_value / prices.at[entry, origin] - 1
    return result


def monthly_signal_diagnostics(scores, prices, dates, direction="higher", delay=1,
                               *, valuation_prices=None, corporate_actions=()):
    ic, quintiles = [], []
    for left, right in zip(dates[:-1], dates[1:]):
        a, b = prices.index.get_loc(left) + delay, prices.index.get_loc(right) + delay
        if b >= len(prices):
            continue
        returns = forward_security_returns(prices, prices.index[a], prices.index[b],
                                           valuation_prices, corporate_actions)
        frame = (
            pd.concat([scores.loc[left].rename("score"), returns.rename("return")], axis=1)
            .replace([np.inf, -np.inf], np.nan)
            .dropna()
        )
        if len(frame) < 5:
            continue
        buy = (
            frame.score.rank(method="average").corr(frame["return"].rank(method="average"))
            if frame.score.nunique() > 1 and frame["return"].nunique() > 1
            else np.nan
        )
        ic.append(
            dict(
                date=str(left.date()),
                raw=-buy if direction == "lower" else buy,
                buy=buy,
                n=len(frame),
            )
        )
        # Average ties remain together, preserving the definition of a quantile.
        groups = np.ceil(frame.score.rank(method="average", pct=True) * 5).clip(1, 5)
        means = frame["return"].groupby(groups).mean()
        row = dict(date=str(left.date()), n=len(frame))
        row.update({f"q{i}": means.get(i, np.nan) for i in range(1, 6)})
        row["spread"] = row["q5"] - row["q1"]
        quintiles.append(row)
    return ic, quintiles


def holm_adjust(p_values):
    names = list(p_values)
    order = sorted(names, key=p_values.get)
    result, previous = {}, 0.0
    for i, name in enumerate(order):
        previous = max(previous, min(1.0, p_values[name] * (len(order) - i)))
        result[name] = previous
    return result


def synchronized_bootstrap(returns, repetitions=2000, block=20, seed=1729, benchmark="SPY"):
    """Moving blocks, shared indices across every candidate/benchmark.

    Complete common sessions are required; missing rows are never collapsed into
    adjacent dates. Intervals estimate mean excess daily return, not causal alpha.
    """
    frame = returns.copy()
    valid = frame.notna().all(axis=1)
    # Choose contiguous complete runs: bootstrap blocks cannot bridge quote gaps.
    starts = [i for i in range(max(0, len(frame) - block + 1)) if valid.iloc[i : i + block].all()]
    if not starts or benchmark not in frame or repetitions < 1:
        return {"status": "insufficient_data", "repetitions": repetitions, "blockSessions": block}
    values = frame.to_numpy(float)
    rng = np.random.default_rng(seed)
    count = max(1, int(valid.sum()))
    chunks = int(np.ceil(count / block))
    estimates = np.empty((repetitions, len(frame.columns)))
    for i in range(repetitions):
        idx = (rng.choice(starts, chunks)[:, None] + np.arange(block)).ravel()[:count]
        estimates[i] = values[idx].mean(axis=0)
    benchmark_pos = frame.columns.get_loc(benchmark)
    excess = estimates - estimates[:, benchmark_pos, None]
    observed = frame.loc[valid].mean().to_numpy(copy=True)
    observed = observed - observed[benchmark_pos]
    centered = excess - observed
    p = {
        name: float((1 + np.sum(np.abs(centered[:, j]) >= abs(observed[j]))) / (repetitions + 1))
        for j, name in enumerate(frame)
        if name != benchmark
    }
    corrected = holm_adjust(p)
    return dict(
        status="available",
        repetitions=repetitions,
        blockSessions=block,
        seed=seed,
        observations=count,
        estimand="mean_daily_return_minus_benchmark",
        benchmark=benchmark,
        results=[
            dict(
                id=name,
                estimate=observed[j],
                lower=np.quantile(excess[:, j], 0.025),
                upper=np.quantile(excess[:, j], 0.975),
                pValue=p.get(name),
                holm=corrected.get(name),
            )
            for j, name in enumerate(frame)
        ],
    )


def regime_analysis(returns, benchmark):
    trailing = benchmark.rolling(63, min_periods=63).sum().shift(1)
    volatility = benchmark.rolling(63, min_periods=63).std().shift(1)
    threshold = volatility.expanding(min_periods=126).median()
    rebound = (benchmark.rolling(126, min_periods=126).sum().shift(1) < -0.15) & (
        benchmark.rolling(21, min_periods=21).sum().shift(1) > 0
    )
    masks = {
        "up": trailing >= 0,
        "down": trailing < 0,
        "high_vol": volatility > threshold,
        "low_vol": volatility <= threshold,
        "crash_rebound": rebound,
    }
    return {
        name: {
            factor: {
                "observations": int(series[mask].count()),
                "meanDailyReturn": series[mask].mean(),
            }
            for factor, series in returns.items()
        }
        for name, mask in masks.items()
    }


def conditional_exposures(returns, controls=("SPY", "MOM12_1", "VOL252", "LOGADV63")):
    """Descriptive OLS exposure check; controls are contemporaneous fixed sleeves."""
    result = []
    for name in returns:
        use = [c for c in controls if c in returns and c != name]
        if not use:
            continue
        sample = returns[[name] + use].dropna()
        if len(sample) < 252:
            result.append(dict(id=name, status="insufficient_data"))
            continue
        y = sample[name].to_numpy()
        x = np.column_stack([np.ones(len(sample)), sample[use]])
        beta, _, rank, _ = np.linalg.lstsq(x, y, rcond=None)
        residual = y - x @ beta
        total = np.square(y - y.mean()).sum()
        result.append(
            dict(
                id=name,
                status="available",
                observations=len(sample),
                controls=use,
                exposures=dict(zip(use, beta[1:])),
                annualizedIntercept=beta[0] * 252,
                residualVolatility=np.std(residual) * np.sqrt(252),
                rSquared=1 - np.square(residual).sum() / total if total else None,
                rank=int(rank),
                interpretation="descriptive_exposure_not_causal_alpha",
            )
        )
    return result
