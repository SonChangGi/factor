"""Versioned price/volume hypotheses; eligible population precedes ranking."""

from __future__ import annotations
import numpy as np
import pandas as pd

_SPECS = [
    ("MOM12_1", "12–1 모멘텀", "return", "higher", 252, "P[m−1]/P[m−12]−1"),
    ("STREV1", "1개월 반전", "return", "lower", 21, "P[m]/P[m−1]−1"),
    ("LTREV13_60", "장기 반전", "return", "lower", 1260, "P[m−12]/P[m−60]−1"),
    (
        "SEASON5Y",
        "동일 달 계절성",
        "return",
        "higher",
        1260,
        "mean(next calendar month return in each preceding 5 years)",
    ),
    ("HIGH52", "52주 고점 근접", "trend", "higher", 252, "C/max(C,252)"),
    ("MA200GAP", "200일 평균 괴리", "trend", "higher", 200, "C/mean(C,200)−1"),
    ("BREAKOUT126", "126일 고가 돌파", "trend", "higher", 127, "C/max(H[t−126:t−1])−1"),
    ("ACCEL3_6", "수익 가속", "trend", "higher", 127, "252×(mean(logreturn,63)−mean(previous63))"),
    (
        "CONSISTENCY12_1",
        "상승일 비율",
        "quality",
        "higher",
        252,
        "positive daily returns / observations in (m−12,m−1]",
    ),
    (
        "EFFICIENCY12_1",
        "추세 효율",
        "quality",
        "higher",
        252,
        "sum(logreturn)/sum(abs(logreturn)) in (m−12,m−1]",
    ),
    (
        "RANGEPOS126",
        "가격 범위 위치",
        "quality",
        "higher",
        126,
        "(C−min(L,126))/(max(H,126)−min(L,126))",
    ),
    (
        "RAMOM12_1",
        "위험조정 모멘텀",
        "market",
        "higher",
        252,
        "MOM12_1 / annualized daily volatility in formation",
    ),
    ("BETA_SPY252", "시장 베타", "market", "lower", 253, "cov(r,SPY)/var(SPY),252"),
    (
        "IDVOL_SPY252",
        "고유 변동성",
        "market",
        "lower",
        253,
        "sqrt(252×(var(r)−cov(r,SPY)^2/var(SPY)))",
    ),
    (
        "RESMOM_SPY36M_12_1",
        "잔차 모멘텀",
        "market",
        "higher",
        756,
        "36 monthly intercept+SPY regression; sum(11 formation residuals)/std(11 residuals)",
    ),
    ("VOL252", "변동성", "risk", "lower", 253, "sqrt(252)×std(r,252)"),
    ("DOWNSIDEDEV252", "하방편차", "risk", "lower", 253, "sqrt(252×mean(min(r,0)^2,252))"),
    (
        "REL_DOWNSIDEBETA252",
        "상대 하방 베타",
        "risk",
        "higher",
        253,
        "beta where SPY below window mean − full beta; minimum21 downside observations",
    ),
    ("MAX1M", "최대 일수익", "risk", "lower", 21, "max(daily return in completed month)"),
    (
        "ES10_252",
        "하위 10% 수익",
        "risk",
        "higher",
        253,
        "mean(bottom ceil(252×0.1) daily returns)",
    ),
    ("SKEW252", "왜도", "distribution", "research", 253, "mean((r−mean(r))^3)/population_std(r)^3"),
    (
        "EXKURT252",
        "초과첨도",
        "distribution",
        "research",
        253,
        "mean((r−mean(r))^4)/population_std(r)^4−3",
    ),
    ("PARKINSON126", "고저 변동성", "range", "lower", 126, "sqrt(252×mean(log(H/L)^2)/(4log(2)))"),
    (
        "RANGECONTRACT21_126",
        "가격범위 수축",
        "range",
        "research",
        126,
        "mean(range/C,last21)/mean(range/C,previous105)−1",
    ),
    (
        "ONMOM12_1",
        "야간 수익",
        "session",
        "research",
        252,
        "sum(log(O/C_previous)) in formation; split-adjusted, dividends excluded",
    ),
    ("IDMOM12_1", "장중 수익", "session", "research", 252, "sum(log(C/O)) in formation"),
    (
        "AMIHUD252",
        "비유동성",
        "liquidity",
        "higher",
        253,
        "mean(abs(r)/(provider Close×Volume),252)",
    ),
    ("LOGADV63", "거래대금 규모", "liquidity", "lower", 63, "log(mean(dollar volume,63))"),
    (
        "DV_TREND21_126",
        "거래대금 추세",
        "liquidity",
        "higher",
        126,
        "mean(DV,last21)/mean(DV,previous105)−1",
    ),
    (
        "DV_SHOCK21_126",
        "거래대금 충격",
        "liquidity",
        "higher",
        126,
        "(mean(DV,last21)−mean(DV,previous105))/std(DV,previous105)",
    ),
    ("SIGNED_VP63", "방향 거래대금", "liquidity", "higher", 64, "sum(sign(r)×DV,63)/sum(DV,63)"),
    (
        "PV_CORR126",
        "가격·거래대금 상관",
        "liquidity",
        "research",
        127,
        "corr(r,delta(log(DV)),126)",
    ),
]


# References describe motivating measurements, not an assertion that this
# universe, formation period and long-only implementation replicate a paper.
_REFERENCES = {
    "MOM12_1": ["https://doi.org/10.1111/j.1540-6261.1993.tb04702.x"],
    "HIGH52": ["https://doi.org/10.1111/j.1540-6261.2004.00695.x"],
    "SEASON5Y": ["https://doi.org/10.1016/j.jfineco.2007.02.003"],
    "AMIHUD252": ["https://doi.org/10.1016/S1386-4181(01)00024-6"],
    "LOGADV63": ["https://doi.org/10.1016/S1386-4181(01)00024-6"],
    "PARKINSON126": ["https://doi.org/10.1086/296071"],
    "MAX1M": ["https://doi.org/10.1016/j.jfineco.2010.08.014"],
    "ONMOM12_1": ["https://personal.lse.ac.uk/polk/research/TugOfWar.pdf"],
    "IDMOM12_1": ["https://personal.lse.ac.uk/polk/research/TugOfWar.pdf"],
    "RESMOM_SPY36M_12_1": ["https://doi.org/10.1016/j.jempfin.2011.01.003"],
}


def factor_registry():
    explanations = {
        "return": (
            "수익 지속·과잉 반응·달력 반복이 상대 수익을 예측한다.",
            "위험 노출이나 일시적 사건이 관측 수익을 설명할 수 있다.",
        ),
        "trend": (
            "추세와 가격 위치에 정보 반영의 지연이 나타난다.",
            "추세 반전이나 공통 시장 노출이 설명할 수 있다.",
        ),
        "quality": (
            "안정적으로 누적된 추세가 더 지속된다.",
            "강한 가격 상승과 중복되는 측정일 수 있다.",
        ),
        "market": (
            "시장 노출을 분리한 위험·추세가 상대 성과를 설명한다.",
            "시장모형의 누락 요인과 베타 추정 오차가 설명할 수 있다.",
        ),
        "risk": (
            "위험 회피 또는 극단 수익 선호가 가격에 반영된다.",
            "낮은 위험·꼬리 노출과 시장 국면 차이가 설명할 수 있다.",
        ),
        "liquidity": (
            "거래 비용 프리미엄 또는 거래 활동의 정보가 수익을 예측한다.",
            "규모와 가격 추세, 거래 불가능성이 설명할 수 있다.",
        ),
    }
    return [
        dict(
            id=i,
            name=n,
            family=f,
            direction=d,
            selectionEligible=d != "research",
            formula=formula,
            minHistory=h,
            version="1.1.0" if i in ("CONSISTENCY12_1", "SIGNED_VP63", "MAX1M") else "1.0.0",
            **(
                {
                    "signInputContract": "provider-close-cash-source-interval-v1",
                    "signInputNotes": "동일 분할 기준 종가·배당으로 상승일을 계산한다. 원자료 정밀도 구간이 0을 포함하면 보합, 정밀도 미확인은 결측으로 처리한다.",
                }
                if i in ("CONSISTENCY12_1", "SIGNED_VP63") else {}
            ),
            **(
                {
                    "returnInputContract": "provider-close-cash-holding-return-v1",
                    "returnInputNotes": "동일 분할 기준 종가와 배당으로 (당일 종가−전일 종가+배당)/전일 종가를 계산한다.",
                }
                if i == "MAX1M" else {}
            ),
            unit={
                "AMIHUD252": "return_per_USD",
                "LOGADV63": "log_USD_per_session",
                "ACCEL3_6": "annual_log_return_difference",
                "ONMOM12_1": "cumulative_log_return",
                "IDMOM12_1": "cumulative_log_return",
            }.get(i, "dimensionless"),
            priceBasis="total_return_except_OHLC_shapes_provider_split_basis",
            hypothesis=explanations.get(
                f,
                (
                    "방향을 사전 확정하지 않은 탐색 정의.",
                    "가격·거래량 노출과 자료 기준 차이가 설명할 수 있다.",
                ),
            )[0],
            counterHypothesis=explanations.get(
                f, ("", "가격·거래량 노출과 자료 기준 차이가 설명할 수 있다.")
            )[1],
            falsification="시간순 비용 후 검증에서 방향·안정성 소실 또는 통제 노출로 설명됨",
            missingPolicy="required observations missing: unavailable; zero denominator: unavailable",
            availableAt="signal close",
            references=_REFERENCES.get(i, []),
            canonicalReplication=False,
            methodClass="paper_motivated_adaptation"
            if i in _REFERENCES
            else "project_defined_hypothesis",
            replicationNotes="기간·유니버스·매수 방향은 이 레지스트리의 사전 정의를 사용한다. 시장모형은 SPY 단일 요인이다.",
        )
        for i, n, f, d, h, formula in _SPECS
    ]


def _div(a, b):
    return a / b.replace(0, np.nan)


def _quote_interval(values, precision):
    """Bounds of the source representation, not a return-size tolerance."""
    values = np.asarray(values, dtype=float)
    kind = precision.get("kind")
    if kind == "float32":
        encoded = values.astype(np.float32)
        center = encoded.astype(float)
        lower = (np.nextafter(encoded, np.float32(-np.inf)).astype(float) + center) / 2
        upper = (np.nextafter(encoded, np.float32(np.inf)).astype(float) + center) / 2
    elif kind == "decimal":
        places = precision.get("places")
        if not isinstance(places, int) or not 0 <= places <= 15:
            raise ValueError("Decimal quote precision requires places in 0..15")
        half_tick = 0.5 * 10.0 ** -places
        lower, upper = values - half_tick, values + half_tick
    elif kind == "exact":
        lower, upper = values.copy(), values.copy()
    else:
        raise ValueError("Unknown source quote precision")
    valid = np.isfinite(values) & (values > 0)
    return np.where(valid, lower, np.nan), np.where(valid, upper, np.nan)


def consistency_return_signs(market):
    """Daily total-return signs at source precision; no adjusted-close fallback.

    Yahoo closes have binary32 encoding; dividends are supplied decimal cash
    amounts on the same split basis. Explicit custom inputs can declare exact
    split-adjusted raw closes. Unspecified external quote precision is missing.
    """
    source = market.metadata.get("consistencySignSource", {})
    provider = market.provider_close
    if provider is None:
        if source.get("basis") != "split_adjusted_raw_close" or "precision" not in source:
            return pd.DataFrame(np.nan, index=market.prices.index, columns=market.prices.columns)
        close = market.raw_close
        precision = source["precision"]
    else:
        close = provider
        precision = {"kind": "float32"}
    values = close.to_numpy()
    # Undo recorded repairs before measuring the original source's encoding.
    scale = np.ones(values.shape)
    amendments = market.metadata.get("amendments", [])
    for row in amendments:
        if row.get("kind") != "verified_missing_split_normalization":
            continue
        symbol, date, ratio = row["symbol"], pd.Timestamp(row["date"]), row["ratio"]
        if not np.isfinite(ratio) or ratio <= 0:
            raise ValueError("Invalid recorded split normalization")
        if symbol in close:
            scale[close.index < date, close.columns.get_loc(symbol)] /= ratio
    lower, upper = _quote_interval(values / scale, precision)
    lower *= scale
    upper *= scale
    for row in amendments:
        if row.get("kind") != "observed_quote":
            continue
        symbol, date = row["symbol"], pd.Timestamp(row["date"])
        if symbol not in close or date not in close.index:
            continue
        position = (close.index.get_loc(date), close.columns.get_loc(symbol))
        quoted_precision = row.get("closePrecision")
        if quoted_precision is None:
            lower[position] = upper[position] = np.nan
        else:
            # Quote amendments are in the final provider basis, applied after
            # recorded split repairs by amend_market.
            lo, hi = _quote_interval(values[position], quoted_precision)
            lower[position], upper[position] = lo, hi
    previous_lower = np.roll(lower, 1, axis=0)
    previous_upper = np.roll(upper, 1, axis=0)
    previous_lower[0] = previous_upper[0] = np.nan
    cash = market.dividends.to_numpy()
    # Enclose binary64 parsing/arithmetic of supplied decimal cash. Zero cash
    # is exact; an absent cash-action observation must remain unavailable.
    cash_lower = np.where(cash == 0, 0, np.nextafter(cash, -np.inf))
    cash_upper = np.where(cash == 0, 0, np.nextafter(cash, np.inf))
    net_lower = np.nextafter(np.nextafter(lower - previous_upper, -np.inf) + cash_lower, -np.inf)
    net_upper = np.nextafter(np.nextafter(upper - previous_lower, np.inf) + cash_upper, np.inf)
    valid = (np.isfinite(net_lower) & np.isfinite(net_upper)
             & np.isfinite(cash) & (cash >= 0))
    signs = np.where(net_lower > 0, 1.0, np.where(net_upper < 0, -1.0, 0.0))
    return pd.DataFrame(np.where(valid, signs, np.nan), index=close.index, columns=close.columns)


def source_holding_returns(market):
    """Cash-inclusive holding returns on one split basis; no Adj Close fallback."""
    close = market.provider_close
    if close is None:
        source = market.metadata.get(
            "holdingReturnSource", market.metadata.get("consistencySignSource", {})
        )
        if source.get("basis") != "split_adjusted_raw_close":
            return pd.DataFrame(np.nan, index=market.prices.index, columns=market.prices.columns)
        close = market.raw_close
    else:
        # Canonical source centers eliminate CSV binary64 serialization tails,
        # without rounding financial returns or changing declared exact inputs.
        scale = np.ones(close.shape)
        amendments = market.metadata.get("amendments", [])
        for row in amendments:
            if row.get("kind") != "verified_missing_split_normalization":
                continue
            symbol, date, ratio = row["symbol"], pd.Timestamp(row["date"]), row["ratio"]
            if not np.isfinite(ratio) or ratio <= 0:
                raise ValueError("Invalid recorded split normalization")
            if symbol in close:
                scale[close.index < date, close.columns.get_loc(symbol)] /= ratio
        centers = (close.to_numpy() / scale).astype(np.float32).astype(float) * scale
        for row in amendments:
            if row.get("kind") != "observed_quote":
                continue
            symbol, date = row["symbol"], pd.Timestamp(row["date"])
            if symbol not in close or date not in close.index:
                continue
            position = (close.index.get_loc(date), close.columns.get_loc(symbol))
            precision = row.get("closePrecision")
            if precision is None:
                centers[position] = np.nan
            else:
                value = close.iloc[position]
                _quote_interval(value, precision)  # Validate the separate source contract.
                centers[position] = (float(np.float32(value))
                                     if precision["kind"] == "float32" else value)
        close = pd.DataFrame(centers, index=close.index, columns=close.columns)
    previous = close.shift(1)
    cash = market.dividends
    valid = (np.isfinite(close) & close.gt(0) & np.isfinite(previous) & previous.gt(0)
             & np.isfinite(cash) & cash.ge(0))
    returns = (close - previous + cash).div(previous.where(previous.gt(0)))
    return returns.where(valid & np.isfinite(returns))


def _expected_shortfall(frame, window=252, tail_count=26):
    """Exact bottom-tail mean with bounded working memory and complete windows."""
    values = frame.to_numpy()
    result = np.full(values.shape, np.nan)
    if len(values) < window:
        return pd.DataFrame(result, index=frame.index, columns=frame.columns)
    for start in range(0, values.shape[1], 8):
        batch = values[:, start : start + 8]
        windows = np.lib.stride_tricks.sliding_window_view(batch, window, axis=0)
        valid = np.isfinite(windows).all(axis=-1)
        bottom = np.partition(windows, tail_count - 1, axis=-1)[..., :tail_count].mean(axis=-1)
        result[window - 1 :, start : start + 8] = np.where(valid, bottom, np.nan)
    return pd.DataFrame(result, index=frame.index, columns=frame.columns)


def _monthly(prices):
    # Period labels are mapped back to actual observation dates, never calendar
    # labels that could expose a later price to an earlier trading session.
    groups = prices.index.to_period("M")
    dates = pd.Series(prices.index, index=groups).groupby(level=0).last()
    result = prices.groupby(groups).last()
    # last() skips nulls: require the actual month-end observation instead.
    result = prices.loc[dates.values].copy()
    result.index = dates.index
    return result, dates


def iter_integrated_factors(market):
    p = market.prices
    c = market.split_close
    h = market.split_high
    lows = market.split_low
    o = market.split_open
    r = p.pct_change(fill_method=None)
    lr = np.log1p(r)
    dv = (market.raw_close * market.volumes).where(market.volumes.gt(0))
    monthly, dates = _monthly(p)
    mr = monthly.pct_change(fill_method=None)

    def expand(frame):
        frame = frame.copy()
        frame.index = pd.DatetimeIndex(dates.loc[frame.index].values)
        return frame.reindex(p.index, method="ffill")

    def formation(frame, operation):
        values = []
        for k in range(len(dates)):
            if k < 12:
                values.append(pd.Series(np.nan, index=p.columns))
                continue
            sample = frame.loc[
                (frame.index > dates.iloc[k - 12]) & (frame.index <= dates.iloc[k - 1])
            ]
            valid = sample.notna().all() & sample.count().gt(0)
            values.append(operation(sample).where(valid))
        return expand(pd.DataFrame(values, index=dates.index))

    mom = monthly.shift(1) / monthly.shift(12) - 1
    beta = None
    for id, _, _, direction, _, _ in _SPECS:
        if id == "MOM12_1":
            s = expand(mom)
        elif id == "STREV1":
            s = expand(mr)
        elif id == "LTREV13_60":
            s = expand(monthly.shift(12) / monthly.shift(60) - 1)
        elif id == "SEASON5Y":
            s = expand(sum(mr.shift(k * 12 - 1) for k in range(1, 6)) / 5)
        elif id == "HIGH52":
            s = _div(c, c.rolling(252).max())
        elif id == "MA200GAP":
            s = _div(c, c.rolling(200).mean()) - 1
        elif id == "BREAKOUT126":
            s = _div(c, h.shift(1).rolling(126).max()) - 1
        elif id == "ACCEL3_6":
            s = 252 * (lr.rolling(63).mean() - lr.shift(63).rolling(63).mean())
        elif id == "CONSISTENCY12_1":
            s = formation(consistency_return_signs(market), lambda x: x.gt(0).mean())
        elif id == "EFFICIENCY12_1":
            s = formation(lr, lambda x: _div(x.sum(), x.abs().sum()))
        elif id == "RANGEPOS126":
            s = _div(c - lows.rolling(126).min(), h.rolling(126).max() - lows.rolling(126).min())
        elif id == "RAMOM12_1":
            s = _div(expand(mom), formation(r, lambda x: x.std(ddof=1) * np.sqrt(252)))
        elif id in ("BETA_SPY252", "IDVOL_SPY252", "REL_DOWNSIDEBETA252"):
            spy = r["SPY"]
            cov = r.rolling(252).cov(spy)
            var = spy.rolling(252).var()
            beta = cov.div(var.replace(0, np.nan), axis=0)
            if id == "BETA_SPY252":
                s = beta
            elif id == "IDVOL_SPY252":
                s = np.sqrt((r.rolling(252).var() - cov * beta).clip(lower=0) * 252)
            else:
                # Window-specific downside threshold; no future observations.
                s = pd.DataFrame(np.nan, index=p.index, columns=p.columns)
                rv = r.to_numpy()
                sv = spy.to_numpy()
                for k in range(252, len(p)):
                    x = sv[k - 251 : k + 1]
                    y = rv[k - 251 : k + 1]
                    mask = x < np.mean(x)
                    if mask.sum() < 21:
                        continue
                    xx = x[mask]
                    yy = y[mask]
                    den = np.sum((xx - xx.mean()) ** 2)
                    if den > 0:
                        s.iloc[k] = (
                            np.sum((xx - xx.mean())[:, None] * (yy - yy.mean(axis=0)), axis=0) / den
                            - beta.iloc[k]
                        )
        elif id == "RESMOM_SPY36M_12_1":
            result = pd.DataFrame(np.nan, index=monthly.index, columns=p.columns)
            for k in range(36, len(monthly)):
                x = mr["SPY"].iloc[k - 35 : k + 1].to_numpy()
                y = mr.iloc[k - 35 : k + 1].to_numpy()
                valid = np.isfinite(y).all(axis=0)
                if not np.isfinite(x).all():
                    continue
                xx = np.column_stack([np.ones(36), x])
                res = y[:, valid] - xx @ np.linalg.lstsq(xx, y[:, valid], rcond=None)[0]
                formation_res = res[-12:-1]
                den = formation_res.std(axis=0, ddof=1)
                result.iloc[k, np.flatnonzero(valid)] = np.divide(
                    formation_res.sum(axis=0), den, out=np.full(len(den), np.nan), where=den > 0
                )
            s = expand(result)
        elif id == "VOL252":
            s = r.rolling(252).std() * np.sqrt(252)
        elif id == "DOWNSIDEDEV252":
            s = np.sqrt(r.clip(upper=0).pow(2).rolling(252).mean() * 252)
        elif id == "MAX1M":
            holding_returns = source_holding_returns(market)
            grouped = holding_returns.groupby(holding_returns.index.to_period("M"))
            complete = grouped.count().eq(grouped.size(), axis=0)
            s = expand(grouped.max().where(complete))
        elif id == "ES10_252":
            s = _expected_shortfall(r)
        elif id == "SKEW252":
            s = (r.rolling(252).skew() * 250 / np.sqrt(252 * 251)).where(
                r.rolling(252).std().gt(0)
            )
        elif id == "EXKURT252":
            s = ((r.rolling(252).kurt() * 250 * 249 / 251 - 6) / 253).where(
                r.rolling(252).std().gt(0)
            )
        elif id == "PARKINSON126":
            s = np.sqrt(np.log(h / lows).pow(2).rolling(126).mean() * 252 / (4 * np.log(2)))
        elif id == "RANGECONTRACT21_126":
            ranges = (h - lows) / c
            s = _div(ranges.rolling(21).mean(), ranges.shift(21).rolling(105).mean()) - 1
        elif id == "ONMOM12_1":
            s = formation(np.log(o / c.shift(1)), lambda x: x.sum())
        elif id == "IDMOM12_1":
            s = formation(np.log(c / o), lambda x: x.sum())
        elif id == "AMIHUD252":
            s = _div(r.abs(), dv).rolling(252).mean()
        elif id == "LOGADV63":
            s = np.log(dv.rolling(63).mean())
        elif id == "DV_TREND21_126":
            s = _div(dv.rolling(21).mean(), dv.shift(21).rolling(105).mean()) - 1
        elif id == "DV_SHOCK21_126":
            s = _div(
                dv.rolling(21).mean() - dv.shift(21).rolling(105).mean(),
                dv.shift(21).rolling(105).std(),
            )
        elif id == "SIGNED_VP63":
            s = _div(
                (consistency_return_signs(market) * dv).rolling(63).sum(),
                dv.rolling(63).sum(),
            )
        elif id == "PV_CORR126":
            s = r.rolling(126).corr(np.log(dv).diff())
        s = s.replace([np.inf, -np.inf], np.nan).where(market.eligibility)
        yield id, -s if direction == "lower" else s


def compute_integrated_factors(market):
    return dict(iter_integrated_factors(market))
