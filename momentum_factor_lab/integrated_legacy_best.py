"""Factor scoring using only data available through each signal date.

The default library is intentionally broad enough to behave like a small
free-data factor zoo.  It is **not** a claim that every academic anomaly can be
replicated without licensed point-in-time accounting data.  Most generated
variants use only historical OHLCV; fundamentals are used only when the caller
provides point-in-time rows with ``available_at``.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

def group_prices(prices):
    grouped = defaultdict(list)
    for row in prices:
        grouped[str(row["ticker"])].append(row)
    for rows in grouped.values():
        rows.sort(key=lambda row: row["date"])
    return dict(grouped)


LEGACY_SOURCE_SHA256 = "41c700828b14ddeb6a076c37c02e7b8d3889fef674eb93467a21fa56cdc147df"
LEGACY_SOURCE_PATH = "best-factor/src/best_factor/factors.py"



@dataclass(frozen=True)
class FactorDefinition:
    name: str
    description: str
    requires_fundamentals: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    category: str = "other"
    kind: str = "legacy"
    params: tuple[tuple[str, object], ...] = ()


@dataclass(frozen=True)
class _History:
    rows: tuple[dict[str, object], ...]
    closes: tuple[tuple[object, float], ...]
    volumes: tuple[tuple[object, float, float], ...]


CORE_FACTOR_NAMES = (
    "momentum_12_1",
    "momentum_6m",
    "low_volatility",
    "short_reversal",
    "risk_adjusted_momentum",
    "liquidity",
    "value_pe",
    "quality_roe",
    "composite_defensive",
)


FACTOR_CATEGORY_DESCRIPTIONS = {
    "momentum": "Price momentum and acceleration signals using only historical adjusted closes.",
    "reversal": "Short-horizon contrarian signals that prefer recent underperformance.",
    "risk": "Realized volatility, downside/upside dispersion, intraday range, and tail-risk controls.",
    "risk_adjusted_momentum": "Momentum scaled by realized volatility to penalize unstable trends.",
    "liquidity": "Dollar-volume, liquidity trend, and Amihud-style tradability proxies.",
    "trend": "Moving-average, range-position, breakout, and drawdown-to-high trend signals.",
    "trend_quality": "Smoothness and consistency of price trends, not just endpoint return.",
    "distribution": "Higher-moment return-shape signals such as skewness and kurtosis.",
    "tail": "Lower-tail loss signals that penalize severe recent losses.",
    "accumulation": "Price/volume confirmation signals intended to proxy accumulation pressure.",
    "intraday": "Open/close decomposition signals using free OHLC fields when available.",
    "value": "Optional point-in-time valuation ratios supplied by the caller.",
    "quality": "Optional point-in-time profitability, balance-sheet, and growth fields supplied by the caller.",
    "growth": "Optional point-in-time fundamental growth fields supplied by the caller.",
    "composite": "Transparent blends of multiple eligible base factors.",
}


def _p(**kwargs: object) -> tuple[tuple[str, object], ...]:
    return tuple(sorted(kwargs.items()))


def _def(
    name: str,
    description: str,
    *,
    kind: str,
    category: str,
    params: tuple[tuple[str, object], ...] = (),
    requires_fundamentals: tuple[str, ...] = (),
    dependencies: tuple[str, ...] = (),
) -> FactorDefinition:
    return FactorDefinition(
        name=name,
        description=description,
        kind=kind,
        category=category,
        params=params,
        requires_fundamentals=requires_fundamentals,
        dependencies=dependencies,
    )


def _build_default_factors() -> list[FactorDefinition]:
    factors: list[FactorDefinition] = [
        _def("momentum_12_1", "12-1 month price momentum", kind="momentum", category="momentum", params=_p(lookback=252, skip=21)),
        _def("momentum_6m", "6 month price momentum skipping the latest month", kind="momentum", category="momentum", params=_p(lookback=126, skip=21)),
        _def("low_volatility", "Negative realized volatility over 6 months", kind="volatility", category="risk", params=_p(window=126, measure="total")),
        _def("short_reversal", "Negative 1 month return", kind="reversal", category="reversal", params=_p(lookback=21)),
        _def("risk_adjusted_momentum", "6 month momentum divided by 6 month volatility", kind="risk_adjusted_momentum", category="risk_adjusted_momentum", params=_p(lookback=126, skip=21, vol_window=126)),
        _def("liquidity", "Average dollar volume over 3 months", kind="liquidity", category="liquidity", params=_p(window=63)),
        _def("value_pe", "Lower trailing PE is better when point-in-time fundamentals are supplied", kind="fundamental", category="value", params=_p(field="pe_ratio", direction="negative"), requires_fundamentals=("pe_ratio",)),
        _def("quality_roe", "Higher return on equity is better when point-in-time fundamentals are supplied", kind="fundamental", category="quality", params=_p(field="return_on_equity", direction="positive"), requires_fundamentals=("return_on_equity",)),
        _def("composite_defensive", "Average rank blend of momentum, low volatility and liquidity", kind="composite", category="composite", dependencies=("momentum_6m", "low_volatility", "liquidity")),
    ]

    # Momentum and skip-month variants.  These are transparent, deterministic
    # variants rather than separate claims of novel academic anomalies.
    for lookback in (21, 42, 63, 84, 105, 126, 168, 189, 210, 252, 315, 378, 504, 756):
        for skip in (0, 5, 10, 21, 42, 63):
            if skip >= lookback:
                continue
            factors.append(_def(
                f"mom_{lookback}d_skip_{skip}d",
                f"{lookback}-trading-day momentum skipping {skip} trading days",
                kind="momentum",
                category="momentum",
                params=_p(lookback=lookback, skip=skip),
            ))

    for lookback in (3, 5, 10, 21, 42, 63):
        factors.append(_def(
            f"reversal_{lookback}d",
            f"Negative {lookback}-trading-day return",
            kind="reversal",
            category="reversal",
            params=_p(lookback=lookback),
        ))

    for window in (10, 21, 42, 63, 84, 126, 189, 252):
        for measure in ("total", "downside", "upside", "range"):
            factors.append(_def(
                f"vol_{measure}_{window}d",
                f"Negative {measure} risk over {window} trading days",
                kind="volatility",
                category="risk",
                params=_p(window=window, measure=measure),
            ))

    for window in (21, 42, 63, 126, 252):
        factors.append(_def(
            f"skew_{window}d",
            f"Return skewness over {window} trading days",
            kind="return_skew",
            category="distribution",
            params=_p(window=window),
        ))
        factors.append(_def(
            f"kurtosis_low_{window}d",
            f"Negative excess kurtosis over {window} trading days; lower fat-tail shape is better",
            kind="return_kurtosis",
            category="distribution",
            params=_p(window=window),
        ))
        factors.append(_def(
            f"tail_loss_{window}d",
            f"Average worst-decile return over {window} trading days; less severe tail loss is better",
            kind="tail_loss",
            category="tail",
            params=_p(window=window),
        ))
        factors.append(_def(
            f"trend_efficiency_{window}d",
            f"Signed trend efficiency over {window} trading days: endpoint return versus path noise",
            kind="trend_efficiency",
            category="trend_quality",
            params=_p(window=window),
        ))
        factors.append(_def(
            f"return_consistency_{window}d",
            f"Share of positive daily returns over {window} trading days",
            kind="return_consistency",
            category="trend_quality",
            params=_p(window=window),
        ))

    for lookback in (63, 84, 126, 168, 252, 378, 504):
        for skip in (0, 21, 42):
            if skip >= lookback:
                continue
            for vol_window in (21, 63, 126):
                factors.append(_def(
                    f"ramom_{lookback}d_skip_{skip}d_vol_{vol_window}d",
                    f"{lookback}-day momentum divided by {vol_window}-day volatility, skipping {skip} days",
                    kind="risk_adjusted_momentum",
                    category="risk_adjusted_momentum",
                    params=_p(lookback=lookback, skip=skip, vol_window=vol_window),
                ))

    for window in (10, 21, 42, 63, 126, 252):
        factors.append(_def(
            f"dvol_avg_{window}d",
            f"Average dollar volume over {window} trading days",
            kind="liquidity",
            category="liquidity",
            params=_p(window=window),
        ))
        factors.append(_def(
            f"amihud_illiq_{window}d",
            f"Negative Amihud-style illiquidity over {window} trading days",
            kind="illiquidity",
            category="liquidity",
            params=_p(window=window),
        ))

    for short, long in ((10, 63), (21, 63), (21, 126), (42, 126), (63, 252)):
        factors.append(_def(
            f"dvol_trend_{short}d_{long}d",
            f"Dollar-volume trend: {short}-day average versus {long}-day average",
            kind="volume_trend",
            category="liquidity",
            params=_p(short=short, long=long),
        ))
        factors.append(_def(
            f"dvol_shock_{short}d_{long}d",
            f"Dollar-volume shock z-score: {short}-day average versus pre-window {long}-day baseline",
            kind="volume_shock",
            category="liquidity",
            params=_p(short=short, long=long),
        ))

    for window in (21, 42, 63, 126, 252):
        factors.append(_def(
            f"price_volume_corr_{window}d",
            f"Correlation between returns and dollar-volume changes over {window} trading days",
            kind="price_volume_corr",
            category="accumulation",
            params=_p(window=window),
        ))

    for window in (10, 20, 30, 50, 100, 150, 200):
        factors.append(_def(
            f"ma_gap_{window}d",
            f"Price gap versus {window}-day moving average",
            kind="moving_average_gap",
            category="trend",
            params=_p(window=window),
        ))

    for short in (5, 10, 20, 50):
        for long in (50, 100, 150, 200):
            if short < long:
                factors.append(_def(
                    f"ma_cross_{short}d_{long}d",
                    f"{short}-day moving average versus {long}-day moving average",
                    kind="moving_average_cross",
                    category="trend",
                    params=_p(short=short, long=long),
                ))

    for window in (21, 42, 63, 126, 252):
        factors.append(_def(
            f"range_pos_{window}d",
            f"Current close percentile within {window}-day high-low range",
            kind="range_position",
            category="trend",
            params=_p(window=window),
        ))
        factors.append(_def(
            f"breakout_{window}d",
            f"Current close versus the prior {window}-day high",
            kind="breakout_strength",
            category="trend",
            params=_p(window=window),
        ))

    for short, long in ((5, 21), (10, 42), (21, 63), (42, 126), (63, 252)):
        factors.append(_def(
            f"range_contraction_{short}d_{long}d",
            f"Recent high-low range contraction: lower {short}-day range versus {long}-day baseline is better",
            kind="range_contraction",
            category="risk",
            params=_p(short=short, long=long),
        ))

    for window in (5, 21, 42, 63, 126):
        factors.append(_def(
            f"overnight_return_{window}d",
            f"Average open versus prior close return over {window} trading days",
            kind="overnight_return",
            category="intraday",
            params=_p(window=window),
        ))
        factors.append(_def(
            f"intraday_return_{window}d",
            f"Average close versus open return over {window} trading days",
            kind="intraday_return",
            category="intraday",
            params=_p(window=window),
        ))
        factors.append(_def(
            f"drawdown_high_{window}d",
            f"Closeness to {window}-day high",
            kind="drawdown_high",
            category="trend",
            params=_p(window=window),
        ))

    for short, long in ((21, 63), (21, 126), (42, 126), (63, 252), (126, 504)):
        for skip in (0, 21):
            factors.append(_def(
                f"accel_{short}d_{long}d_skip_{skip}d",
                f"Momentum acceleration: {short}-day return minus {long}-day return, skipping {skip} days",
                kind="acceleration",
                category="momentum",
                params=_p(short=short, long=long, skip=skip),
            ))

    optional_fundamentals = [
        ("value_pb", "Lower price-to-book is better when point-in-time fundamentals are supplied", "value", "price_to_book", "negative"),
        ("value_ps", "Lower price-to-sales is better when point-in-time fundamentals are supplied", "value", "price_to_sales", "negative"),
        ("value_fcf_yield", "Higher free-cash-flow yield is better when point-in-time fundamentals are supplied", "value", "free_cash_flow_yield", "positive"),
        ("quality_margin", "Higher profit margin is better when point-in-time fundamentals are supplied", "quality", "profit_margin", "positive"),
        ("quality_debt_to_equity", "Lower debt-to-equity is better when point-in-time fundamentals are supplied", "quality", "debt_to_equity", "negative"),
        ("growth_revenue", "Higher revenue growth is better when point-in-time fundamentals are supplied", "growth", "revenue_growth", "positive"),
    ]
    for name, description, category, field, direction in optional_fundamentals:
        factors.append(_def(
            name,
            description,
            kind="fundamental",
            category=category,
            params=_p(field=field, direction=direction),
            requires_fundamentals=(field,),
        ))

    composite_specs = [
        ("blend_mom126_lowvol63_liq63", ("mom_126d_skip_21d", "vol_total_63d", "dvol_avg_63d")),
        ("blend_mom252_lowvol126_liq126", ("mom_252d_skip_21d", "vol_total_126d", "dvol_avg_126d")),
        ("blend_ramom126_trend50_liq63", ("ramom_126d_skip_21d_vol_63d", "ma_gap_50d", "dvol_avg_63d")),
        ("blend_ramom252_trend200_liq126", ("ramom_252d_skip_21d_vol_126d", "ma_gap_200d", "dvol_avg_126d")),
        ("blend_reversal21_lowvol63_liq63", ("reversal_21d", "vol_total_63d", "dvol_avg_63d")),
        ("blend_range63_mom126_lowvol63", ("range_pos_63d", "mom_126d_skip_21d", "vol_total_63d")),
        ("blend_drawdown126_mom252_lowvol126", ("drawdown_high_126d", "mom_252d_skip_21d", "vol_total_126d")),
        ("blend_accel21_126_ramom126_liq63", ("accel_21d_126d_skip_0d", "ramom_126d_skip_21d_vol_63d", "dvol_avg_63d")),
        ("blend_mom63_vol21_dvol21", ("mom_63d_skip_0d", "vol_total_21d", "dvol_avg_21d")),
        ("blend_mom504_lowvol252_liq252", ("mom_504d_skip_21d", "vol_total_252d", "dvol_avg_252d")),
    ]
    for name, deps in composite_specs:
        factors.append(_def(
            name,
            f"Average normalized blend of {', '.join(deps)}",
            kind="composite",
            category="composite",
            dependencies=deps,
        ))

    unique: dict[str, FactorDefinition] = {}
    for factor in factors:
        unique.setdefault(factor.name, factor)
    return list(unique.values())


DEFAULT_FACTORS = _build_default_factors()
FACTOR_REGISTRY = {f.name: f for f in DEFAULT_FACTORS}
FACTOR_PRESETS = {
    "core": CORE_FACTOR_NAMES,
    "zoo": tuple(f.name for f in DEFAULT_FACTORS),
}


def core_factor_names() -> list[str]:
    return list(CORE_FACTOR_NAMES)


def factor_names_for_preset(preset: str) -> list[str]:
    try:
        return list(FACTOR_PRESETS[preset])
    except KeyError as exc:
        raise ValueError(f"unknown factor preset: {preset}") from exc


def factor_category_counts(factor_names: Iterable[str] | None = None) -> dict[str, int]:
    names = validate_factor_names(factor_names or [f.name for f in DEFAULT_FACTORS])
    counts = Counter(FACTOR_REGISTRY[name].category for name in names)
    return dict(sorted(counts.items()))


def factor_kind_counts(factor_names: Iterable[str] | None = None) -> dict[str, int]:
    names = validate_factor_names(factor_names or [f.name for f in DEFAULT_FACTORS])
    counts = Counter(FACTOR_REGISTRY[name].kind for name in names)
    return dict(sorted(counts.items()))


def factor_catalog(factor_names: Iterable[str] | None = None) -> list[dict[str, object]]:
    """Return public, path-free factor metadata for dashboard explanations."""
    names = validate_factor_names(factor_names or [f.name for f in DEFAULT_FACTORS])
    catalog: list[dict[str, object]] = []
    for name in names:
        factor = FACTOR_REGISTRY[name]
        catalog.append(
            {
                "name": factor.name,
                "description": factor.description,
                "category": factor.category,
                "category_description": FACTOR_CATEGORY_DESCRIPTIONS.get(factor.category, "Other factor family."),
                "kind": factor.kind,
                "params": dict(factor.params),
                "dependencies": list(factor.dependencies),
                "requires_fundamentals": list(factor.requires_fundamentals),
            }
        )
    return catalog


def factor_family_summary(factor_names: Iterable[str] | None = None) -> list[dict[str, object]]:
    """Summarize tested factor families so the UI can explain zoo breadth."""
    names = validate_factor_names(factor_names or [f.name for f in DEFAULT_FACTORS])
    grouped: dict[str, list[FactorDefinition]] = defaultdict(list)
    for name in names:
        grouped[FACTOR_REGISTRY[name].category].append(FACTOR_REGISTRY[name])
    summary: list[dict[str, object]] = []
    for category in sorted(grouped):
        factors = sorted(grouped[category], key=lambda f: f.name)
        kind_counts = Counter(f.kind for f in factors)
        summary.append(
            {
                "category": category,
                "description": FACTOR_CATEGORY_DESCRIPTIONS.get(category, "Other factor family."),
                "count": len(factors),
                "kind_counts": dict(sorted(kind_counts.items())),
                "examples": [factor.name for factor in factors[:6]],
                "requires_fundamentals_count": sum(1 for factor in factors if factor.requires_fundamentals),
            }
        )
    return summary


def validate_factor_names(factor_names: Iterable[str]) -> list[str]:
    requested = list(dict.fromkeys(factor_names))
    unknown = [name for name in requested if name not in FACTOR_REGISTRY]
    if unknown:
        raise ValueError(f"unknown factor(s): {', '.join(unknown)}")
    return requested


def expand_factor_dependencies(factor_names: Iterable[str]) -> list[str]:
    requested = validate_factor_names(factor_names)
    expanded: list[str] = []

    def add_with_deps(name: str) -> None:
        for dep in FACTOR_REGISTRY[name].dependencies:
            add_with_deps(dep)
        if name not in expanded:
            expanded.append(name)

    for name in requested:
        add_with_deps(name)
    return expanded


def compute_factor_scores(
    prices: list[dict[str, object]],
    signal_dates: list[object],
    fundamentals: dict[str, list[dict[str, object]]] | None = None,
    factor_names: Iterable[str] | None = None,
    emit_factor_names: Iterable[str] | None = None,
) -> list[dict[str, object]]:
    scored: list[dict[str, object]] = []
    for _, _, rows in iter_factor_score_batches(prices, signal_dates, fundamentals, factor_names, emit_factor_names):
        scored.extend(rows)
    return scored


def iter_factor_score_batches(
    prices: list[dict[str, object]],
    signal_dates: list[object],
    fundamentals: dict[str, list[dict[str, object]]] | None = None,
    factor_names: Iterable[str] | None = None,
    emit_factor_names: Iterable[str] | None = None,
) -> Iterable[tuple[object, str, list[dict[str, object]]]]:
    """Yield ranked score rows one signal-date/factor batch at a time.

    This keeps large live runs from retaining every raw factor-score row in
    memory before portfolio construction.  ``compute_factor_scores`` remains
    the materializing compatibility wrapper for small/offline runs and raw CSV
    archives.
    """
    grouped = group_prices(prices)
    fundamentals = fundamentals or {}
    selected = expand_factor_dependencies(factor_names or [f.name for f in DEFAULT_FACTORS])
    emit = set(emit_factor_names or selected)
    definitions = [FACTOR_REGISTRY[name] for name in selected]

    for signal_date in signal_dates:
        histories = {ticker: _history_through(rows, signal_date) for ticker, rows in grouped.items()}
        pit_fundamentals = {ticker: _fundamentals_asof(fundamentals.get(ticker, []), signal_date) for ticker in grouped}
        raw_by_factor: dict[str, list[dict[str, object]]] = defaultdict(list)
        for factor in definitions:
            if factor.kind == "composite":
                continue
            for ticker, history in histories.items():
                score, reason = _score_factor(factor, history, pit_fundamentals.get(ticker))
                raw_by_factor[factor.name].append(_score_row(factor.name, ticker, signal_date, score, reason))

        for factor in definitions:
            if factor.kind != "composite":
                continue
            normalized: dict[str, list[float]] = defaultdict(list)
            for name in factor.dependencies:
                rows = raw_by_factor.get(name, [])
                scores = [float(r["score"]) for r in rows if r["eligible"]]
                by_ticker = {str(r["ticker"]): float(r["score"]) for r in rows if r["eligible"]}
                for ticker, value in by_ticker.items():
                    normalized[ticker].append(_normalize_value(value, scores))
            for ticker in grouped:
                vals = normalized.get(ticker, [])
                if len(vals) == len(factor.dependencies):
                    raw_by_factor[factor.name].append(_score_row(factor.name, ticker, signal_date, sum(vals) / len(vals), ""))
                else:
                    raw_by_factor[factor.name].append(_score_row(factor.name, ticker, signal_date, math.nan, "insufficient_history"))

        for factor_name in sorted(raw_by_factor):
            if factor_name not in emit:
                continue
            rows = raw_by_factor[factor_name]
            eligible_rows = sorted([r for r in rows if r["eligible"]], key=lambda r: (-float(r["score"]), str(r["ticker"])))
            rank_by_ticker = {str(r["ticker"]): idx + 1 for idx, r in enumerate(eligible_rows)}
            ranked_rows = []
            for row in sorted(rows, key=lambda r: str(r["ticker"])):
                ranked = dict(row)
                ranked["rank"] = rank_by_ticker.get(str(row["ticker"]), "")
                ranked_rows.append(ranked)
            yield signal_date, factor_name, ranked_rows


def build_score_index(scores: Iterable[dict[str, object]]) -> dict[tuple[str, object], list[dict[str, object]]]:
    index: dict[tuple[str, object], list[dict[str, object]]] = defaultdict(list)
    for row in scores:
        index[(str(row["factor"]), row["signal_date"])].append(row)
    return dict(index)


def rows_for_factor_date(scores: Iterable[dict[str, object]] | Mapping[tuple[str, object], list[dict[str, object]]], factor: str, signal_date: object) -> list[dict[str, object]]:
    if isinstance(scores, Mapping):
        return list(scores.get((factor, signal_date), []))
    return [r for r in scores if r["factor"] == factor and r["signal_date"] == signal_date]


def factor_names(scores: Iterable[dict[str, object]]) -> list[str]:
    return sorted({str(r["factor"]) for r in scores})


def serialize_factor_scores(scores: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    output = []
    for row in scores:
        signal = row.get("signal_date")
        output.append(
            {
                **row,
                "signal_date": signal.isoformat() if hasattr(signal, "isoformat") else signal,
                "eligible": str(bool(row.get("eligible"))).lower(),
            }
        )
    return output


def _history_through(rows: list[dict[str, object]], signal_date: object) -> _History:
    eligible = tuple(r for r in rows if r["date"] <= signal_date)
    closes = tuple((r["date"], float(r["adj_close"])) for r in eligible)
    volumes = tuple((r["date"], float(r.get("volume", 0) or 0), float(r["adj_close"])) for r in eligible)
    return _History(rows=eligible, closes=closes, volumes=volumes)


def _fundamentals_asof(records: list[dict[str, object]], signal_date: object) -> dict[str, float] | None:
    eligible = [r for r in records if r.get("available_at") is not None and r["available_at"] <= signal_date]
    if not eligible:
        return None
    latest = max(eligible, key=lambda r: (r["available_at"], r.get("as_of_date") or r["available_at"]))
    return {k: float(v) for k, v in latest.items() if isinstance(v, (int, float)) and math.isfinite(float(v))}


def _score_factor(factor: FactorDefinition, history: _History, fundamentals: dict[str, float] | None) -> tuple[float, str]:
    params = dict(factor.params)
    closes = history.closes
    rows = history.rows
    volumes = history.volumes
    kind = factor.kind
    if kind == "momentum":
        return _momentum(closes, lookback=int(params["lookback"]), skip=int(params.get("skip", 0)))
    if kind == "reversal":
        return _reversal(closes, lookback=int(params["lookback"]))
    if kind == "volatility":
        return _volatility(rows, closes, window=int(params["window"]), measure=str(params.get("measure", "total")))
    if kind == "return_skew":
        return _return_skew(closes, window=int(params["window"]))
    if kind == "return_kurtosis":
        return _return_kurtosis(closes, window=int(params["window"]))
    if kind == "tail_loss":
        return _tail_loss(closes, window=int(params["window"]))
    if kind == "trend_efficiency":
        return _trend_efficiency(closes, window=int(params["window"]))
    if kind == "return_consistency":
        return _return_consistency(closes, window=int(params["window"]))
    if kind == "risk_adjusted_momentum":
        return _risk_adjusted_momentum(closes, lookback=int(params["lookback"]), skip=int(params.get("skip", 0)), vol_window=int(params["vol_window"]))
    if kind == "liquidity":
        return _liquidity(volumes, window=int(params["window"]))
    if kind == "illiquidity":
        return _illiquidity(closes, volumes, window=int(params["window"]))
    if kind == "volume_trend":
        return _volume_trend(volumes, short=int(params["short"]), long=int(params["long"]))
    if kind == "volume_shock":
        return _volume_shock(volumes, short=int(params["short"]), long=int(params["long"]))
    if kind == "price_volume_corr":
        return _price_volume_corr(closes, volumes, window=int(params["window"]))
    if kind == "moving_average_gap":
        return _moving_average_gap(closes, window=int(params["window"]))
    if kind == "moving_average_cross":
        return _moving_average_cross(closes, short=int(params["short"]), long=int(params["long"]))
    if kind == "range_position":
        return _range_position(rows, window=int(params["window"]))
    if kind == "drawdown_high":
        return _drawdown_high(closes, window=int(params["window"]))
    if kind == "breakout_strength":
        return _breakout_strength(rows, window=int(params["window"]))
    if kind == "range_contraction":
        return _range_contraction(rows, short=int(params["short"]), long=int(params["long"]))
    if kind == "overnight_return":
        return _overnight_return(rows, window=int(params["window"]))
    if kind == "intraday_return":
        return _intraday_return(rows, window=int(params["window"]))
    if kind == "acceleration":
        return _acceleration(closes, short=int(params["short"]), long=int(params["long"]), skip=int(params.get("skip", 0)))
    if kind == "fundamental":
        return _fundamental_score(params, fundamentals)
    return math.nan, "provider_error"


def _fundamental_score(params: dict[str, object], fundamentals: dict[str, float] | None) -> tuple[float, str]:
    field = str(params["field"])
    if not fundamentals or math.isnan(float(fundamentals.get(field, math.nan))):
        return math.nan, "missing_fundamentals"
    value = float(fundamentals[field])
    if str(params.get("direction")) == "negative":
        if value <= 0:
            return math.nan, "missing_fundamentals"
        return -value, ""
    return value, ""


def _momentum(closes: Sequence[tuple[object, float]], lookback: int, skip: int) -> tuple[float, str]:
    if len(closes) <= lookback:
        return math.nan, "insufficient_history"
    end_index = len(closes) - 1 - skip
    start_index = len(closes) - 1 - lookback
    if end_index <= start_index or start_index < 0:
        return math.nan, "insufficient_history"
    start = closes[start_index][1]
    end = closes[end_index][1]
    if start <= 0:
        return math.nan, "insufficient_history"
    return end / start - 1.0, ""


def _reversal(closes: Sequence[tuple[object, float]], lookback: int) -> tuple[float, str]:
    value, reason = _momentum(closes, lookback=lookback, skip=0)
    if reason:
        return value, reason
    return -value, ""


def _volatility(rows: Sequence[dict[str, object]], closes: Sequence[tuple[object, float]], window: int, measure: str) -> tuple[float, str]:
    if measure == "range":
        if len(rows) < window:
            return math.nan, "insufficient_history"
        ranges = []
        for row in rows[-window:]:
            close = float(row.get("adj_close", row.get("close", math.nan)))
            high = float(row.get("high", close))
            low = float(row.get("low", close))
            if close > 0 and high >= low:
                ranges.append((high - low) / close)
        if len(ranges) < window:
            return math.nan, "insufficient_history"
        return -sum(ranges) / len(ranges), ""
    returns = _window_returns(closes, window)
    if len(returns) < window:
        return math.nan, "insufficient_history"
    if measure == "downside":
        downside = [min(0.0, r) for r in returns]
        return -_population_stdev(downside), ""
    if measure == "upside":
        upside = [max(0.0, r) for r in returns]
        return -_population_stdev(upside), ""
    return -_population_stdev(returns), ""


def _return_skew(closes: Sequence[tuple[object, float]], window: int) -> tuple[float, str]:
    returns = _window_returns(closes, window)
    if len(returns) < window:
        return math.nan, "insufficient_history"
    stdev = _population_stdev(returns)
    if stdev <= 0:
        return math.nan, "insufficient_history"
    mean = sum(returns) / len(returns)
    third_moment = sum((ret - mean) ** 3 for ret in returns) / len(returns)
    return third_moment / (stdev ** 3), ""


def _return_kurtosis(closes: Sequence[tuple[object, float]], window: int) -> tuple[float, str]:
    returns = _window_returns(closes, window)
    if len(returns) < window:
        return math.nan, "insufficient_history"
    stdev = _population_stdev(returns)
    if stdev <= 0:
        return math.nan, "insufficient_history"
    mean = sum(returns) / len(returns)
    fourth_moment = sum((ret - mean) ** 4 for ret in returns) / len(returns)
    excess = fourth_moment / (stdev ** 4) - 3.0
    return -excess, ""


def _tail_loss(closes: Sequence[tuple[object, float]], window: int) -> tuple[float, str]:
    returns = _window_returns(closes, window)
    if len(returns) < window:
        return math.nan, "insufficient_history"
    tail_count = max(1, math.ceil(len(returns) * 0.10))
    worst = sorted(returns)[:tail_count]
    return sum(worst) / len(worst), ""


def _trend_efficiency(closes: Sequence[tuple[object, float]], window: int) -> tuple[float, str]:
    if len(closes) < window + 1:
        return math.nan, "insufficient_history"
    window_closes = closes[-(window + 1):]
    start = window_closes[0][1]
    end = window_closes[-1][1]
    if start <= 0:
        return math.nan, "insufficient_history"
    returns = _returns(window_closes)
    path_noise = sum(abs(ret) for ret in returns)
    if path_noise <= 0:
        return 0.0, ""
    return (end / start - 1.0) / path_noise, ""


def _return_consistency(closes: Sequence[tuple[object, float]], window: int) -> tuple[float, str]:
    returns = _window_returns(closes, window)
    if len(returns) < window:
        return math.nan, "insufficient_history"
    return sum(1 for ret in returns if ret > 0) / len(returns), ""


def _risk_adjusted_momentum(closes: Sequence[tuple[object, float]], lookback: int, skip: int, vol_window: int) -> tuple[float, str]:
    mom, reason = _momentum(closes, lookback=lookback, skip=skip)
    if reason:
        return mom, reason
    returns = _window_returns(closes, vol_window)
    if len(returns) < vol_window:
        return math.nan, "insufficient_history"
    vol = _population_stdev(returns)
    if vol <= 0:
        return math.nan, "insufficient_history"
    return mom / vol, ""


def _liquidity(volumes: Sequence[tuple[object, float, float]], window: int) -> tuple[float, str]:
    if len(volumes) < window:
        return math.nan, "insufficient_history"
    dollar = [volume * close for _, volume, close in volumes[-window:]]
    return sum(dollar) / len(dollar), ""


def _illiquidity(closes: Sequence[tuple[object, float]], volumes: Sequence[tuple[object, float, float]], window: int) -> tuple[float, str]:
    returns = _window_returns(closes, window)
    if len(returns) < window or len(volumes) < window:
        return math.nan, "insufficient_history"
    dollars = [volume * close for _, volume, close in volumes[-window:]]
    values = [abs(ret) / dollar for ret, dollar in zip(returns, dollars) if dollar > 0]
    if len(values) < window:
        return math.nan, "insufficient_volume"
    return -sum(values) / len(values) * 1_000_000.0, ""


def _volume_trend(volumes: Sequence[tuple[object, float, float]], short: int, long: int) -> tuple[float, str]:
    if len(volumes) < long:
        return math.nan, "insufficient_history"
    short_vals = [volume * close for _, volume, close in volumes[-short:]]
    long_vals = [volume * close for _, volume, close in volumes[-long:]]
    long_avg = sum(long_vals) / len(long_vals)
    if long_avg <= 0:
        return math.nan, "insufficient_volume"
    return (sum(short_vals) / len(short_vals)) / long_avg - 1.0, ""


def _volume_shock(volumes: Sequence[tuple[object, float, float]], short: int, long: int) -> tuple[float, str]:
    if len(volumes) < long or short >= long:
        return math.nan, "insufficient_history"
    dollar = [volume * close for _, volume, close in volumes[-long:]]
    if any(value <= 0 for value in dollar):
        return math.nan, "insufficient_volume"
    baseline = dollar[:-short]
    if not baseline:
        return math.nan, "insufficient_history"
    short_avg = sum(dollar[-short:]) / short
    baseline_avg = sum(baseline) / len(baseline)
    baseline_std = _population_stdev(baseline)
    if baseline_std <= 0:
        if baseline_avg <= 0:
            return math.nan, "insufficient_volume"
        return short_avg / baseline_avg - 1.0, ""
    return (short_avg - baseline_avg) / baseline_std, ""


def _price_volume_corr(closes: Sequence[tuple[object, float]], volumes: Sequence[tuple[object, float, float]], window: int) -> tuple[float, str]:
    returns = _window_returns(closes, window)
    if len(returns) < window or len(volumes) < window + 1:
        return math.nan, "insufficient_history"
    dollar = [volume * close for _, volume, close in volumes[-(window + 1):]]
    changes = []
    for prev, current in zip(dollar, dollar[1:]):
        if prev <= 0:
            return math.nan, "insufficient_volume"
        changes.append(current / prev - 1.0)
    if len(changes) != len(returns):
        return math.nan, "insufficient_history"
    return _correlation(returns, changes)


def _moving_average_gap(closes: Sequence[tuple[object, float]], window: int) -> tuple[float, str]:
    if len(closes) < window:
        return math.nan, "insufficient_history"
    values = [close for _, close in closes[-window:]]
    avg = sum(values) / len(values)
    if avg <= 0:
        return math.nan, "insufficient_history"
    return closes[-1][1] / avg - 1.0, ""


def _moving_average_cross(closes: Sequence[tuple[object, float]], short: int, long: int) -> tuple[float, str]:
    if len(closes) < long:
        return math.nan, "insufficient_history"
    short_avg = sum(close for _, close in closes[-short:]) / short
    long_avg = sum(close for _, close in closes[-long:]) / long
    if long_avg <= 0:
        return math.nan, "insufficient_history"
    return short_avg / long_avg - 1.0, ""


def _range_position(rows: Sequence[dict[str, object]], window: int) -> tuple[float, str]:
    if len(rows) < window:
        return math.nan, "insufficient_history"
    window_rows = rows[-window:]
    lows = [float(row.get("low", row.get("adj_close", math.nan))) for row in window_rows]
    highs = [float(row.get("high", row.get("adj_close", math.nan))) for row in window_rows]
    close = float(window_rows[-1].get("adj_close", window_rows[-1].get("close", math.nan)))
    lo = min(lows)
    hi = max(highs)
    if not math.isfinite(close) or hi <= lo:
        return math.nan, "insufficient_history"
    return (close - lo) / (hi - lo), ""


def _drawdown_high(closes: Sequence[tuple[object, float]], window: int) -> tuple[float, str]:
    if len(closes) < window:
        return math.nan, "insufficient_history"
    values = [close for _, close in closes[-window:]]
    high = max(values)
    if high <= 0:
        return math.nan, "insufficient_history"
    return closes[-1][1] / high - 1.0, ""


def _breakout_strength(rows: Sequence[dict[str, object]], window: int) -> tuple[float, str]:
    if len(rows) < window + 1:
        return math.nan, "insufficient_history"
    prior = rows[-(window + 1):-1]
    highs = [float(row.get("high", row.get("adj_close", math.nan))) for row in prior]
    close = float(rows[-1].get("adj_close", rows[-1].get("close", math.nan)))
    if not math.isfinite(close) or not highs:
        return math.nan, "insufficient_history"
    prior_high = max(highs)
    if prior_high <= 0:
        return math.nan, "insufficient_history"
    return close / prior_high - 1.0, ""


def _range_contraction(rows: Sequence[dict[str, object]], short: int, long: int) -> tuple[float, str]:
    if len(rows) < long:
        return math.nan, "insufficient_history"
    short_avg, short_reason = _average_range(rows[-short:])
    long_avg, long_reason = _average_range(rows[-long:])
    if short_reason or long_reason:
        return math.nan, short_reason or long_reason
    if long_avg <= 0:
        return math.nan, "insufficient_history"
    return -(short_avg / long_avg - 1.0), ""


def _overnight_return(rows: Sequence[dict[str, object]], window: int) -> tuple[float, str]:
    if len(rows) < window + 1:
        return math.nan, "insufficient_history"
    returns = []
    for prev, current in zip(rows[-(window + 1):-1], rows[-window:]):
        prev_close = float(prev.get("close", prev.get("adj_close", math.nan)))
        current_open = float(current.get("open", current.get("close", math.nan)))
        if prev_close > 0 and math.isfinite(current_open):
            returns.append(current_open / prev_close - 1.0)
    if len(returns) < window:
        return math.nan, "insufficient_history"
    return sum(returns) / len(returns), ""


def _intraday_return(rows: Sequence[dict[str, object]], window: int) -> tuple[float, str]:
    if len(rows) < window:
        return math.nan, "insufficient_history"
    returns = []
    for row in rows[-window:]:
        open_ = float(row.get("open", row.get("close", math.nan)))
        close = float(row.get("close", row.get("adj_close", math.nan)))
        if open_ > 0 and math.isfinite(close):
            returns.append(close / open_ - 1.0)
    if len(returns) < window:
        return math.nan, "insufficient_history"
    return sum(returns) / len(returns), ""


def _acceleration(closes: Sequence[tuple[object, float]], short: int, long: int, skip: int) -> tuple[float, str]:
    short_mom, short_reason = _momentum(closes, lookback=short, skip=skip)
    long_mom, long_reason = _momentum(closes, lookback=long, skip=skip)
    if short_reason or long_reason:
        return math.nan, "insufficient_history"
    return short_mom - long_mom, ""


def _window_returns(closes: Sequence[tuple[object, float]], window: int) -> list[float]:
    if len(closes) < window + 1:
        return []
    return _returns(closes[-(window + 1):])


def _returns(closes: Sequence[tuple[object, float]]) -> list[float]:
    out = []
    for (_, prev), (_, current) in zip(closes, closes[1:]):
        if prev > 0:
            out.append(current / prev - 1.0)
    return out


def _population_stdev(values: list[float]) -> float:
    """Fast population standard deviation for hot factor-zoo paths."""
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return math.sqrt(max(0.0, variance))


def _average_range(rows: Sequence[dict[str, object]]) -> tuple[float, str]:
    ranges = []
    for row in rows:
        close = float(row.get("adj_close", row.get("close", math.nan)))
        high = float(row.get("high", close))
        low = float(row.get("low", close))
        if close > 0 and high >= low:
            ranges.append((high - low) / close)
    if len(ranges) != len(rows):
        return math.nan, "insufficient_history"
    return sum(ranges) / len(ranges), ""


def _correlation(xs: list[float], ys: list[float]) -> tuple[float, str]:
    if len(xs) != len(ys) or not xs:
        return math.nan, "insufficient_history"
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x <= 0 or var_y <= 0:
        return math.nan, "insufficient_history"
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    return cov / math.sqrt(var_x * var_y), ""


def _score_row(factor: str, ticker: str, signal_date: object, score: float, reason: str) -> dict[str, object]:
    eligible = not reason and not math.isnan(score) and math.isfinite(score)
    return {
        "factor": factor,
        "ticker": ticker,
        "signal_date": signal_date,
        "score": score if eligible else math.nan,
        "rank": "",
        "eligible": eligible,
        "skip_reason": "" if eligible else reason or "provider_error",
    }


def _normalize_value(value: float, values: list[float]) -> float:
    finite = [v for v in values if math.isfinite(v)]
    if not finite or not math.isfinite(value):
        return 0.0
    lo = min(finite)
    hi = max(finite)
    if hi == lo:
        return 0.5
    return (value - lo) / (hi - lo)
