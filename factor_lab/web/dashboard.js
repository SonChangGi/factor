const MANUAL_UPDATE_WORKFLOW_URL = 'https://github.com/SonChangGi/factor/actions/workflows/daily-dashboard.yml';
const MANUAL_UPDATE_COMMAND = 'gh workflow run daily-dashboard.yml --repo SonChangGi/factor --ref main';

const MANIFEST_URL = 'data/grid/v1/manifest.json';
const AUTOMATION_STATUS_URL = 'data/automation-status.json';
const AUTOMATION_STATUS_CONTRACT = 'momentum-dashboard-automation-status';
const MANIFEST_SCHEMA_VERSION = 1;
const MANIFEST_CONTRACT = 'momentum-static-result-grid';
const MANIFEST_GRID_VERSION = 'v1';
const RESULT_SCHEMA_VERSION = 5;
const RESULT_IDENTITY_VERSION = 'momentum-result-identity-v1';
const CANONICAL_JSON_VERSION = 'rfc8785-jcs-v1';
const RESEARCH_INPUTS_VERSION = 'research-inputs-v2';
const LEGACY_RESEARCH_INPUTS_VERSION = 'research-inputs-v1';
const ABSOLUTE_GUARDRAIL_VERSION = 'absolute-factor-v2';
const LOCAL_API_BASE_URL = 'http://127.0.0.1:8765';
const LOCAL_API_POLL_INTERVAL_MS = 1000;
const CONTROL_PROJECT_ID = 'momentum';
const CONTROL_INPUT_SCHEMA_VERSION = 'momentum/v3';
const CONTROL_CONFIG_HASH_ALGORITHM = 'momentum-research-inputs-rfc8785-v1';
const CONTROL_ARTIFACT_CONTRACT_VERSION = 'momentum/schema-v5-control-result-v1';
const CONTROL_API_POLL_INTERVAL_MS = 5000;
// Four hours covers a 180-minute analysis plus queue, setup, publication,
// Pages propagation, callback, and status-read latency.
const CONTROL_API_MAX_POLLS = 2880;
const CONTROL_RUN_STATUSES = Object.freeze([
  'queued',
  'dispatched',
  'running',
  'validating',
  'published',
  'failed',
  'cancelled',
]);
const EXPECTED_INDEPENDENT_FACTOR_COUNT = 61;
const EXPECTED_POLICY_COUNT = 1;
const EXPECTED_ALIAS_FACTOR_COUNT = 3;
const PERFORMANCE_CONTRACT_VERSION = 'python-period-performance-v1';
const PERFORMANCE_PERIOD_CONTRACT = Object.freeze([
  Object.freeze({ key: '1W', label: '최근 1주', returnCount: 5 }),
  Object.freeze({ key: '1M', label: '최근 1개월', returnCount: 21 }),
  Object.freeze({ key: '3M', label: '최근 3개월', returnCount: 63 }),
  Object.freeze({ key: '6M', label: '최근 6개월', returnCount: 126 }),
  Object.freeze({ key: '1Y', label: '최근 1년', returnCount: 252 }),
  Object.freeze({ key: 'YTD', label: '연초 이후', returnCount: null }),
  Object.freeze({ key: 'FULL', label: '전체 공통 평가기간', returnCount: null }),
]);
const PERFORMANCE_METRIC_KEYS = Object.freeze([
  'cumulativeReturn',
  'sharpe',
  'annualizedVolatility',
  'maxDrawdown',
  'sortino',
  'calmar',
  'cvar5',
  'winRate',
]);
const SELECTED_HOLDING_HISTORY_CONTRACT_VERSION = 1;
const SELECTED_HOLDING_HISTORY_SESSION_COUNT = 21;
const SELECTED_HOLDING_HISTORY_WEIGHT_TIMING = 'last_complete_close_after_execution_processing';
const FACTOR_HOLDING_HISTORY_SIDECAR_CONTRACT = 'momentum-factor-holding-history-sidecar';
const FACTOR_HOLDING_HISTORY_SIDECAR_CONTRACT_VERSION = 2;
const FACTOR_HOLDING_HISTORY_SIDECAR_DIRECTORY = 'factor-holding-history';
const MAX_FACTOR_HOLDING_HISTORY_SIDECAR_BYTES = 5_000_000;
const HOLDING_EXECUTION_STATUSES = Object.freeze([
  'none',
  'executed',
  'executed_partial_unpriceable_targets',
  'blocked_missing_held_quote',
  'blocked_all_targets_unpriceable',
]);
const LIVE_INPUT_HASH_FIELDS_V2 = Object.freeze([
  'prices',
  'volumes',
  'dollarVolumes',
  'rawCloses',
  'requestedSymbols',
  'returnedSymbols',
  'universeRecords',
  'priceSources',
  'dataSources',
]);
const LIVE_INPUT_HASH_FIELDS_V3 = Object.freeze([...LIVE_INPUT_HASH_FIELDS_V2, 'comparisonPrices']);
const LIVE_INPUT_HASH_FIELDS = Object.freeze([
  ...LIVE_INPUT_HASH_FIELDS_V3,
  'marketCaps',
  'marketCapSources',
]);
const PRESET_ID_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const LOCAL_API_REQUIRED = [
  '이 입력 조합은 정적 grid에 사전 계산되지 않았습니다.',
  '새 결과는 연결된 Python API에서 계산해야 합니다.',
].join(' ');

const INPUT_FIELDS = Object.freeze([
  { key: 'rebalance_frequency', id: 'input-rebalance-frequency', kind: 'string' },
  { key: 'evaluation_window_days', id: 'input-evaluation-window-days', kind: 'integer' },
  { key: 'top_n', id: 'input-top-n', kind: 'integer' },
  { key: 'max_weight', id: 'input-max-weight', kind: 'percent' },
  { key: 'transaction_cost_bps', id: 'input-transaction-cost', kind: 'number' },
  { key: 'slippage_bps', id: 'input-slippage', kind: 'number' },
  { key: 'min_price', id: 'input-min-price', kind: 'number' },
  { key: 'min_history_days', id: 'input-min-history', kind: 'integer' },
  { key: 'min_avg_dollar_volume', id: 'input-min-dollar-volume', kind: 'number' },
  { key: 'min_avg_volume', id: 'input-min-volume', kind: 'number' },
  { key: 'liquidity_lookback_days', id: 'input-liquidity-lookback', kind: 'integer' },
  { key: 'min_liquidity_observations', id: 'input-liquidity-observations', kind: 'integer' },
  { key: 'max_price_missing_ratio', id: 'input-price-missing', kind: 'percent' },
  { key: 'max_volume_missing_ratio', id: 'input-volume-missing', kind: 'percent' },
  { key: 'max_extreme_daily_return', id: 'input-extreme-return', kind: 'percent' },
  { key: 'selection_min_sharpe', id: 'input-selection-min-sharpe', kind: 'number' },
  { key: 'selection_max_drawdown', id: 'input-selection-max-drawdown', kind: 'percent' },
  { key: 'selection_max_annualized_cost_drag', id: 'input-selection-max-cost-drag', kind: 'percent' },
  { key: 'selection_min_effective_names', id: 'input-selection-min-effective-names', kind: 'number' },
  { key: 'selection_max_target_hhi', id: 'input-selection-max-target-hhi', kind: 'percent' },
  { key: 'selection_max_target_weight', id: 'input-selection-max-target-weight', kind: 'percent' },
  { key: 'selection_max_abs_security_day_contribution', id: 'input-selection-max-day-contribution', kind: 'percent' },
  { key: 'selection_max_security_absolute_contribution_share', id: 'input-selection-max-contribution-share', kind: 'percent' },
  { key: 'selection_max_leave_one_security_cagr_delta', id: 'input-selection-max-leave-one-delta', kind: 'percent' },
  { key: 'selection_extreme_event_action', id: 'input-selection-extreme-action', kind: 'string' },
  { key: 'selection_extreme_event_penalty_points', id: 'input-selection-penalty-points', kind: 'number' },
]);

const RESEARCH_INPUT_PARITY = Object.freeze({
  rebalanceFrequency: 'rebalance_frequency',
  evaluationWindowDays: 'evaluation_window_days',
  topN: 'top_n',
  maxWeight: 'max_weight',
  transactionCostBps: 'transaction_cost_bps',
  slippageBps: 'slippage_bps',
  minHistoryDays: 'min_history_days',
  minPrice: 'min_price',
  minAvgDollarVolume: 'min_avg_dollar_volume',
  minAvgVolume: 'min_avg_volume',
  liquidityLookbackDays: 'liquidity_lookback_days',
  minLiquidityObservations: 'min_liquidity_observations',
  maxPriceMissingRatio: 'max_price_missing_ratio',
  maxVolumeMissingRatio: 'max_volume_missing_ratio',
  maxExtremeDailyReturn: 'max_extreme_daily_return',
  selectionMinSharpe: 'selection_min_sharpe',
  selectionMaxDrawdown: 'selection_max_drawdown',
  selectionMaxAnnualizedCostDrag: 'selection_max_annualized_cost_drag',
  selectionMinEffectiveNames: 'selection_min_effective_names',
  selectionMaxTargetHhi: 'selection_max_target_hhi',
  selectionMaxTargetWeight: 'selection_max_target_weight',
  selectionMaxAbsSecurityDayContribution: 'selection_max_abs_security_day_contribution',
  selectionMaxSecurityAbsoluteContributionShare: 'selection_max_security_absolute_contribution_share',
  selectionMaxLeaveOneSecurityCagrDelta: 'selection_max_leave_one_security_cagr_delta',
  selectionExtremeEventAction: 'selection_extreme_event_action',
  selectionExtremeEventPenaltyPoints: 'selection_extreme_event_penalty_points',
});
const CONTROL_INPUT_KEYS = Object.freeze(Object.keys(RESEARCH_INPUT_PARITY).sort());

const THEME_STORAGE_KEY = 'quant-research-theme';
const LEGACY_THEME_STORAGE_KEYS = Object.freeze([
  'quant-dashboard-theme',
  'quant-calm-theme',
  'dram-price-theme',
  'etf-tracking-theme',
  'momentum-factor-theme',
  'sox-theme',
]);

/*
 * Chart semantics map to CSS palette tokens instead of inline colors so the
 * same meaning survives both the original light theme and its dark variant.
 * Policy identity uses four approved roots; status and benchmark classes add
 * open fills, stroke patterns, and direct labels instead of relying on hue.
 */
const CHART_PALETTE_CLASS_MAP = Object.freeze({
  bars: Object.freeze({
    focal: 'chart-bar-focal',
    best: 'chart-bar-best',
    context: 'chart-bar-context',
    support: 'chart-bar-support',
    neutralOpen: 'chart-bar-neutral-open',
    component: 'chart-bar-component',
  }),
  benchmarks: Object.freeze({
    SPY: 'benchmark-spy',
    '^IXIC': 'benchmark-ixic',
    QQQ: 'benchmark-qqq',
    default: 'benchmark',
  }),
  policies: Object.freeze({
    score_liquidity_rank: 'policy-score-liquidity-rank',
  }),
  statuses: Object.freeze({
    eligible: 'status-eligible',
    data_excluded: 'status-data-excluded',
    extreme_event_excluded: 'status-extreme-event-excluded',
    default: 'status-unavailable',
  }),
});

function storedTheme() {
  try {
    const canonical = window.localStorage?.getItem(THEME_STORAGE_KEY);
    if (canonical === 'light' || canonical === 'dark') {
      LEGACY_THEME_STORAGE_KEYS.forEach((key) => window.localStorage?.removeItem(key));
      return canonical;
    }
    const migrated = LEGACY_THEME_STORAGE_KEYS
      .map((key) => window.localStorage?.getItem(key))
      .find((value) => value === 'light' || value === 'dark') || null;
    if (migrated) window.localStorage?.setItem(THEME_STORAGE_KEY, migrated);
    LEGACY_THEME_STORAGE_KEYS.forEach((key) => window.localStorage?.removeItem(key));
    return migrated;
  } catch (error) {
    return null;
  }
}

function saveTheme(theme) {
  try {
    window.localStorage?.setItem(THEME_STORAGE_KEY, theme);
  } catch (error) {
    // Theme persistence is optional; the page still works without localStorage.
  }
}

function themeRoot() {
  return document.documentElement || document.querySelector?.('html') || null;
}

function currentTheme() {
  const root = themeRoot();
  return root?.dataset?.theme || root?.getAttribute?.('data-theme') || 'light';
}

function applyTheme(theme) {
  const normalized = theme === 'dark' ? 'dark' : 'light';
  const root = themeRoot();
  if (root?.dataset) {
    root.dataset.theme = normalized;
  } else if (root?.setAttribute) {
    root.setAttribute('data-theme', normalized);
  }
  if (root?.style) root.style.colorScheme = normalized;
  const button = document.querySelector('#theme-toggle');
  if (!button) return;
  const isDark = normalized === 'dark';
  button.setAttribute('aria-pressed', String(isDark));
  button.setAttribute('aria-label', isDark ? '라이트 모드로 전환' : '다크 모드로 전환');
  const label = typeof button.querySelector === 'function' ? button.querySelector('.theme-toggle-text') : null;
  if (label) label.textContent = isDark ? '라이트 모드' : '다크 모드';
}

function bindThemeToggle() {
  storedTheme();
  applyTheme(currentTheme());
  const button = document.querySelector('#theme-toggle');
  if (!button || typeof button.addEventListener !== 'function') return;
  button.addEventListener('click', () => {
    const nextTheme = currentTheme() === 'dark' ? 'light' : 'dark';
    applyTheme(nextTheme);
    saveTheme(nextTheme);
  });
}

const FACTOR_METHOD_OVERRIDES = {
  "mom_12_1": {
    "category": "traditional",
    "formula": "P[t-21] / P[t-273] - 1",
    "description": "Traditional 12-1 cross-sectional total return momentum.",
    "validation": "Manual shifted-return and no-lookahead tests."
  },
  "mom_9_1": {
    "category": "traditional",
    "formula": "P[t-21] / P[t-210] - 1",
    "description": "Nine-month skipped return momentum.",
    "validation": "Manual shifted-return and no-lookahead tests."
  },
  "mom_6_1": {
    "category": "traditional",
    "formula": "P[t-21] / P[t-147] - 1",
    "description": "Traditional 6-1 cross-sectional total return momentum.",
    "validation": "Manual shifted-return and no-lookahead tests."
  },
  "mom_12_2": {
    "category": "traditional",
    "formula": "P[t-42] / P[t-294] - 1",
    "description": "Twelve-month momentum with a two-month skip to reduce reversal contamination.",
    "validation": "Independent raw-shift golden tests."
  },
  "mom_3_1": {
    "category": "traditional",
    "formula": "P[t-21] / P[t-84] - 1",
    "description": "Traditional 3-1 skipped return momentum.",
    "validation": "Independent shifted-return and no-lookahead tests."
  },
  "mom_10d": {
    "category": "recent",
    "formula": "P[t] / P[t-10] - 1",
    "description": "Ten-trading-day short-horizon momentum with high-turnover warning.",
    "validation": "Literal golden-vector simple-return tests and turnover warning audit."
  },
  "mom_6m_unskipped": {
    "category": "recent",
    "formula": "P[t] / P[t-126] - 1",
    "description": "Six-month recent momentum without a skip window.",
    "validation": "Independent raw-shift golden tests."
  },
  "mom_3m": {
    "category": "recent",
    "formula": "P[t] / P[t-63] - 1",
    "description": "Three-month recent momentum without skip month.",
    "validation": "Simple-return fixture tests."
  },
  "mom_2m": {
    "category": "recent",
    "formula": "P[t] / P[t-42] - 1",
    "description": "Two-month short-horizon momentum for fast leadership changes.",
    "validation": "Independent raw-shift golden tests."
  },
  "mom_2_1": {
    "category": "recent",
    "formula": "P[t-21] / P[t-63] - 1",
    "description": "Two-month momentum that skips the most recent month.",
    "validation": "Independent raw-shift golden tests."
  },
  "mom_6m": {
    "category": "recent",
    "formula": "P[t-10] / P[t-136] - 1",
    "description": "Six-month momentum ending ten trading days before the signal date to avoid very recent reversal noise.",
    "validation": "Independent shifted-return and no-lookahead tests; intentionally distinct from mom_6m_unskipped."
  },
  "mom_12m": {
    "category": "recent",
    "formula": "P[t] / P[t-252] - 1",
    "description": "Twelve-month simple momentum without skip month.",
    "validation": "Independent simple-return and no-lookahead tests."
  },
  "mom_1m": {
    "category": "recent",
    "formula": "P[t] / P[t-21] - 1",
    "description": "One-month short-horizon momentum.",
    "validation": "Simple-return fixture tests."
  },
  "multi_horizon": {
    "category": "composite",
    "formula": "0.15*1m + 0.25*3m(skip5) + 0.30*6m(skip10) + 0.30*12m(skip21)",
    "description": "Weighted 1/3/6/12-month multi-horizon momentum composite.",
    "validation": "Component helper tests plus output audit."
  },
  "vol_adjusted": {
    "category": "risk_adjusted",
    "formula": "6m(skip10) / annualized_vol_63d",
    "description": "Six-month momentum scaled by recent annualized volatility.",
    "validation": "Division-by-zero and finite coverage audit."
  },
  "risk_adjusted": {
    "category": "risk_adjusted",
    "formula": "annualized_mean_return_126d / annualized_vol_126d",
    "description": "Rolling Sharpe-like annualized return divided by volatility.",
    "validation": "Rolling mean/vol helper tests."
  },
  "downside_risk_adjusted": {
    "category": "risk_adjusted",
    "formula": "6m(skip10) / annualized_downside_vol_126d",
    "description": "Momentum scaled by downside volatility only.",
    "validation": "Downside fixture tests and finite audit."
  },
  "dual_momentum": {
    "category": "trend",
    "formula": "6m relative momentum penalized when price < MA200",
    "description": "Relative momentum penalized when absolute trend is below the 200-day average.",
    "validation": "Trend penalty and no-lookahead audit."
  },
  "ma_trend": {
    "category": "trend",
    "formula": "P/MA200 - 1 + 0.5*(MA50/MA200 - 1)",
    "description": "Trend persistence from price/MA200 and MA50/MA200 structure.",
    "validation": "Moving-average fixture tests."
  },
  "time_series_trend": {
    "category": "trend",
    "formula": "I(P>MA20)+I(MA20>MA100)+I(MA100>MA200)",
    "description": "Discrete time-series trend stack across short/intermediate/long averages.",
    "validation": "Bounded 0..3 output audit."
  },
  "drawdown_aware": {
    "category": "drawdown",
    "formula": "6m(skip10) + P/rolling_high_126 - 1",
    "description": "Six-month momentum penalized by recent drawdown from rolling high.",
    "validation": "Drawdown sign and no-lookahead audit."
  },
  "high_52w": {
    "category": "drawdown",
    "formula": "P / rolling_high_252 - 1",
    "description": "Closeness to 52-week high; less negative is stronger.",
    "validation": "Manual rolling-high fixture tests."
  },
  "high_26w": {
    "category": "drawdown",
    "formula": "P / rolling_high_126 - 1",
    "description": "Closeness to a 26-week high for intermediate breakout confirmation.",
    "validation": "Independent rolling-high golden tests."
  },
  "breakout_63d": {
    "category": "breakout",
    "formula": "P/rolling_high_63 - 1 + 0.5*1m",
    "description": "Recent breakout pressure with one-month confirmation.",
    "validation": "Rolling-high plus 1m fixture tests."
  },
  "breakout_126d": {
    "category": "breakout",
    "formula": "P/rolling_high_126 - 1 + 0.5*3m",
    "description": "Intermediate breakout pressure with three-month confirmation.",
    "validation": "Independent rolling-high golden tests."
  },
  "reversal_adjusted": {
    "category": "reversal",
    "formula": "12-1 momentum - 0.35*1m momentum",
    "description": "12-1 momentum adjusted for short-term reversal risk.",
    "validation": "Component helper tests plus no-lookahead audit."
  },
  "acceleration": {
    "category": "acceleration",
    "formula": "3m momentum - 0.5*6-1 momentum",
    "description": "Momentum acceleration toward recent leadership.",
    "validation": "Manual acceleration fixture tests."
  },
  "short_acceleration": {
    "category": "acceleration",
    "formula": "1m momentum - 0.5*3m momentum",
    "description": "Short-horizon acceleration signal for very recent leadership surges.",
    "validation": "Independent raw-shift golden tests."
  },
  "decay_adjusted": {
    "category": "acceleration",
    "formula": "6m(skip10) - 0.25*abs(1m momentum)",
    "description": "Six-month momentum penalized when very recent moves look overextended.",
    "validation": "Independent raw-shift golden tests."
  },
  "consistency": {
    "category": "quality",
    "formula": "6m(skip10) * rolling_positive_return_ratio_126d",
    "description": "Rewards momentum earned consistently across days.",
    "validation": "Positive-ratio fixture tests."
  },
  "persistent_12_1": {
    "category": "quality",
    "formula": "12m(skip21) * positive_daily_return_ratio_252d(skip21)",
    "description": "Long-horizon skipped momentum scaled by the share of positive daily returns in the skipped formation window.",
    "validation": "Positive-ratio and no-lookahead tests."
  },
  "low_vol_momentum": {
    "category": "risk_adjusted",
    "formula": "6m(skip10) - annualized_vol_63d",
    "description": "Momentum penalized by high recent volatility.",
    "validation": "Low-vol ranking fixture tests."
  },
  "stability_adjusted": {
    "category": "risk_adjusted",
    "formula": "6m(skip10) / (1 + annualized_vol_126d)",
    "description": "Six-month momentum damped by one-year realized volatility from price returns.",
    "validation": "Independent volatility golden tests."
  },
  "relative_strength_6m": {
    "category": "cross_sectional",
    "formula": "cross-sectional percentile_rank(6m(skip10))",
    "description": "Six-month relative-strength percentile within the eligible universe.",
    "validation": "Cross-sectional rank audit."
  },
  "trend_quality": {
    "category": "quality",
    "formula": "P/MA126 - 1 + rolling_mean_return_126/rolling_vol_126",
    "description": "Combines trend slope with smoothness of returns.",
    "validation": "Rolling helper and finite audit."
  },
  "gap_resistant": {
    "category": "robust",
    "formula": "compound clipped daily returns over 126d",
    "description": "Momentum using clipped daily returns to reduce single-gap dominance.",
    "validation": "Clipped-return fixture tests."
  },
  "winsorized_skip": {
    "category": "robust",
    "formula": "compound clipped daily returns over 126d after 10d skip",
    "description": "Skipped six-month momentum using winsorized daily returns to reduce gap dominance.",
    "validation": "Independent clipped-return golden tests."
  },
  "price_efficiency": {
    "category": "quality",
    "formula": "6m(skip10) * |P/P[t-126]-1| / sum_126(|daily_return|)",
    "description": "Rewards six-month momentum that traveled a direct, low-chop price path.",
    "validation": "Path-efficiency fixture tests and division-by-zero audit."
  },
  "range_position": {
    "category": "range",
    "formula": "6m(skip10) + (P-low_126)/(high_126-low_126) - 0.5",
    "description": "Combines six-month momentum with where price sits inside its trailing range.",
    "validation": "Rolling-range fixture tests and flat-range audit."
  },
  "range_position_252d": {
    "category": "range",
    "formula": "12m(skip21) + (P-low_252)/(high_252-low_252) - 0.5",
    "description": "Combines long-horizon skipped momentum with position inside a 52-week range.",
    "validation": "Independent rolling-range golden tests."
  },
  "median_return_3m": {
    "category": "robust",
    "formula": "median(daily_return, 63d) * 63",
    "description": "Three-month median daily return momentum to reduce outlier sensitivity.",
    "validation": "Median-return golden-vector and outlier-gap tests."
  },
  "median_return_6m": {
    "category": "robust",
    "formula": "median(daily_return, 126d) * 126",
    "description": "Six-month median daily return momentum to reduce outlier sensitivity.",
    "validation": "Median-return golden-vector and no-lookahead tests."
  },
  "winsorized_3m": {
    "category": "robust",
    "formula": "compound clipped [-8%, +8%] daily returns over 63d",
    "description": "Three-month winsorized compounded momentum.",
    "validation": "Winsorized golden-vector and outlier-gap tests."
  },
  "winsorized_12m": {
    "category": "robust",
    "formula": "compound clipped [-8%, +8%] daily returns over 252d",
    "description": "Twelve-month winsorized compounded momentum.",
    "validation": "Winsorized no-lookahead and edge-case tests."
  },
  "vol_adjusted_3m": {
    "category": "risk_adjusted",
    "formula": "3m simple momentum / annualized_vol_63d",
    "description": "Three-month momentum scaled by recent annualized volatility.",
    "validation": "Division-by-zero and finite coverage audit."
  },
  "vol_adjusted_12m": {
    "category": "risk_adjusted",
    "formula": "12-1 momentum / annualized_vol_126d",
    "description": "Twelve-minus-one momentum scaled by intermediate volatility.",
    "validation": "Division-by-zero and no-lookahead audit."
  },
  "downside_adjusted_12m": {
    "category": "risk_adjusted",
    "formula": "12-1 momentum / annualized_downside_vol_252d",
    "description": "Twelve-minus-one momentum scaled by downside volatility.",
    "validation": "Downside risk edge-case tests."
  },
  "ma_slope_50": {
    "category": "trend",
    "formula": "MA50[t] / MA50[t-21] - 1",
    "description": "One-month slope of the 50-day moving average.",
    "validation": "Moving-average slope fixture tests."
  },
  "price_vs_ma200": {
    "category": "trend",
    "formula": "P / MA200 - 1",
    "description": "Distance of price above/below the 200-day moving average.",
    "validation": "Moving-average fixture tests."
  },
  "ma_stack_quality": {
    "category": "trend",
    "formula": "I(P>MA20)+I(MA20>MA50)+I(MA50>MA100)+I(MA100>MA200)",
    "description": "Four-step moving-average stack quality score.",
    "validation": "Bounded 0..4 output and no-lookahead audit."
  },
  "breakout_20d": {
    "category": "breakout",
    "formula": "P/rolling_high_20 - 1 + 0.5*10d",
    "description": "Short breakout proximity with ten-day confirmation.",
    "validation": "Rolling-high golden-vector tests."
  },
  "accel_1m_vs_3m": {
    "category": "acceleration",
    "formula": "1m momentum - 3m momentum",
    "description": "Acceleration from three-month to one-month leadership.",
    "validation": "Manual acceleration fixture tests."
  },
  "accel_3m_vs_6m": {
    "category": "acceleration",
    "formula": "3m momentum - 6m momentum",
    "description": "Acceleration from six-month to three-month leadership.",
    "validation": "Manual acceleration fixture tests."
  },
  "accel_6m_vs_12m": {
    "category": "acceleration",
    "formula": "6m momentum - 12m momentum",
    "description": "Acceleration from twelve-month to six-month leadership.",
    "validation": "Manual acceleration fixture tests."
  },
  "ulcer_adjusted": {
    "category": "drawdown",
    "formula": "6m(skip10) / sqrt(mean(drawdown_126^2, 126d))",
    "description": "Momentum scaled by Ulcer-style drawdown severity.",
    "validation": "Drawdown denominator and finite audit."
  },
  "smooth_return_6m": {
    "category": "quality",
    "formula": "6m simple momentum - rolling_std_daily_return_126d",
    "description": "Six-month return momentum penalized by daily return roughness.",
    "validation": "Smoothness edge-case tests."
  },
  "residual_12_1": {
    "category": "cross_sectional",
    "formula": "sum_252(return shifted21) - beta_252_to_equal_weight_market * sum_252(market_return shifted21)",
    "description": "Twelve-minus-one beta-neutral residual momentum versus the equal-weight candidate-universe proxy.",
    "validation": "Rolling beta residual formula, rank-distinctness, and no-lookahead tests."
  },
  "excess_ir_6m": {
    "category": "cross_sectional",
    "formula": "annualized_mean(excess_return_126d) / annualized_tracking_error_126d",
    "description": "Six-month information-ratio style momentum versus the equal-weight candidate universe.",
    "validation": "Tracking-error denominator and no-lookahead tests."
  },
  "up_down_capture_6m": {
    "category": "asymmetry",
    "formula": "mean(return | market_up,126d) - abs(mean(return | market_down,126d))",
    "description": "Rewards stocks that participate on up-market days without giving back as much on down-market days.",
    "validation": "Market-up/down conditioning and finite-coverage tests."
  },
  "tail_resilient_6m": {
    "category": "tail_risk",
    "formula": "6m(skip10) + q05(daily_return,126d)",
    "description": "Six-month skipped momentum penalized by poor left-tail daily returns.",
    "validation": "Rolling quantile edge-case and no-lookahead tests."
  },
  "jump_excluded_6m": {
    "category": "robust",
    "formula": "sum_126(daily_return shifted10) - max_126(daily_return shifted10)",
    "description": "Formation-window momentum that removes the single largest daily jump to reduce one-day gap dominance.",
    "validation": "Independent shifted-return and outlier-resistance tests."
  },
  "high_persistence_6m": {
    "category": "quality",
    "formula": "mean_63(I(P >= 0.98*rolling_high_126))",
    "description": "Fraction of recent days spent near a six-month high, capturing persistent leadership rather than one-day proximity.",
    "validation": "Rolling-high persistence and no-lookahead tests."
  }
};

const DASHBOARD_INPUT_DEFAULTS = {
  window: '1Y',
  lookbackMonths: 12,
  topN: 20,
  maxWeightPercent: 50,
  rebalanceFrequency: 'ME',
  transactionCostBps: 5,
  slippageBps: 5,
};

const state = {
  data: null,
  activeRunIndex: 0,
  hasUserSelectedFactor: false,
  payload: null,
  manifest: null,
  manifestUrl: null,
  entry: null,
  baseEntry: null,
  summary: null,
  loadToken: 0,
  browserControlsBound: false,
  dashboardControlsBound: false,
  resultSource: null,
  automation: { phase: 'loading', status: null, reference: null },
  controlApiBase: null,
  controlCapabilities: null,
  controlApiError: null,
  pendingControlRun: null,
  backtestChart: {
    pinnedSeriesKey: null,
    previewSeriesKey: null,
    pinnedDate: null,
    previewDate: null,
    signature: null,
  },
};

const isRecord = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const cloneJson = (value) => JSON.parse(JSON.stringify(value));
const finite = (value) => value !== null
  && value !== undefined
  && value !== ''
  && typeof value !== 'boolean'
  && Number.isFinite(Number(value));
const integer = (value) => finite(value) && Number.isInteger(Number(value));
const validSha256 = (value) => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);

function canonicalValue(value) {
  if (Array.isArray(value)) return value.map(canonicalValue);
  if (!isRecord(value)) return value;
  return Object.keys(value).sort().reduce((result, key) => {
    result[key] = canonicalValue(value[key]);
    return result;
  }, {});
}

function canonicalString(value) {
  return JSON.stringify(canonicalValue(value));
}

function sameJson(left, right) {
  return canonicalString(left) === canonicalString(right);
}

function requireCondition(condition, message) {
  if (!condition) throw new Error(message);
}

function closeNumber(left, right, tolerance = 1e-9) {
  if (!finite(left) || !finite(right)) return false;
  const scale = Math.max(1, Math.abs(Number(left)), Math.abs(Number(right)));
  return Math.abs(Number(left) - Number(right)) <= tolerance * scale;
}

const strictJsonNumber = (value) => typeof value === 'number' && Number.isFinite(value);
const nonnegativeInteger = (value) => (
  strictJsonNumber(value) && Number.isInteger(value) && value >= 0
);
const requiredText = (value) => typeof value === 'string' && value.trim().length > 0;

function exactRecordKeys(value, expectedKeys) {
  return isRecord(value)
    && sameJson(Object.keys(value).sort(), [...expectedKeys].sort());
}

function compareWeightSymbolOrder(left, right) {
  const weightDifference = Number(right.weight) - Number(left.weight);
  return weightDifference || String(left.symbol).localeCompare(String(right.symbol));
}

function validateIdentity(identity, resultKey, label, options = {}) {
  requireCondition(isRecord(identity), `${label} resultIdentity가 없습니다.`);
  requireCondition(
    identity.identityVersion === RESULT_IDENTITY_VERSION,
    `${label} identityVersion이 지원되지 않습니다.`,
  );
  requireCondition(
    identity.keyParts?.identityVersion === RESULT_IDENTITY_VERSION,
    `${label} keyParts identityVersion이 지원되지 않습니다.`,
  );
  requireCondition(
    identity.keyParts?.canonicalJsonVersion === CANONICAL_JSON_VERSION,
    `${label} canonical JSON version이 지원되지 않습니다.`,
  );
  requireCondition(
    identity.resultKey === resultKey && validSha256(identity.resultKey),
    `${label} resultKey가 일치하지 않습니다.`,
  );
  requireCondition(isRecord(identity.keyParts), `${label} keyParts가 없습니다.`);
  requireCondition(
    isRecord(identity.keyParts.normalizedInputs),
    `${label} normalizedInputs가 없습니다.`,
  );
  const canonicalTransport = identity.canonicalKeyPartsJson;
  if (options.requireCanonicalTransport !== false) {
    requireCondition(
      typeof canonicalTransport === 'string' && canonicalTransport,
      `${label} canonicalKeyPartsJson이 없습니다.`,
    );
  }
  if (canonicalTransport === undefined && options.requireCanonicalTransport === false) return;
  let canonicalKeyParts;
  try {
    canonicalKeyParts = JSON.parse(canonicalTransport);
  } catch (_error) {
    throw new Error(`${label} canonicalKeyPartsJson이 유효한 JSON이 아닙니다.`);
  }
  requireCondition(
    sameJson(canonicalKeyParts, identity.keyParts),
    `${label} canonicalKeyPartsJson이 keyParts와 다릅니다.`,
  );
  requireCondition(
    canonicalString(identity.keyParts) === canonicalTransport,
    `${label} canonicalKeyPartsJson이 RFC 8785 JCS encoding이 아닙니다.`,
  );
}

function validateManifest(manifest) {
  requireCondition(isRecord(manifest), '정적 grid manifest가 JSON 객체가 아닙니다.');
  requireCondition(
    manifest.schemaVersion === MANIFEST_SCHEMA_VERSION,
    '지원하지 않는 manifest schema입니다.',
  );
  requireCondition(manifest.contract === MANIFEST_CONTRACT, 'manifest contract가 일치하지 않습니다.');
  requireCondition(
    manifest.gridVersion === MANIFEST_GRID_VERSION,
    'manifest gridVersion이 일치하지 않습니다.',
  );
  requireCondition(manifest.bounded === true, '정적 grid가 bounded 계약을 선언하지 않았습니다.');
  requireCondition(
    integer(manifest.maxEntries)
      && Number(manifest.maxEntries) >= 1
      && Number(manifest.maxEntries) <= 64,
    'manifest maxEntries가 잘못되었습니다.',
  );
  requireCondition(
    Array.isArray(manifest.entries) && manifest.entries.length > 0,
    'manifest entry가 없습니다.',
  );
  requireCondition(
    manifest.entryCount === manifest.entries.length
      && manifest.entries.length <= manifest.maxEntries,
    'manifest entry 수가 일관되지 않습니다.',
  );
  requireCondition(validSha256(manifest.defaultResultKey), 'manifest defaultResultKey가 잘못되었습니다.');

  const resultKeys = new Set();
  const inputTuples = new Set();
  const presetIds = new Set();
  let declaredPresetCount = 0;
  manifest.entries.forEach((entry, index) => {
    const label = `manifest.entries[${index}]`;
    requireCondition(
      isRecord(entry) && validSha256(entry.resultKey),
      `${label} resultKey가 잘못되었습니다.`,
    );
    requireCondition(!resultKeys.has(entry.resultKey), 'manifest에 중복 resultKey가 있습니다.');
    resultKeys.add(entry.resultKey);
    requireCondition(isRecord(entry.normalizedInputs), `${label} normalizedInputs가 없습니다.`);
    validateIdentity(entry.identity, entry.resultKey, label);
    requireCondition(
      sameJson(entry.normalizedInputs, entry.identity.keyParts.normalizedInputs),
      `${label} normalizedInputs가 identity와 다릅니다.`,
    );
    const inputTuple = canonicalString(entry.normalizedInputs);
    requireCondition(!inputTuples.has(inputTuple), 'manifest에 중복 입력 tuple이 있습니다.');
    inputTuples.add(inputTuple);
    if (Object.prototype.hasOwnProperty.call(entry, 'presetId')) {
      requireCondition(
        typeof entry.presetId === 'string' && PRESET_ID_PATTERN.test(entry.presetId),
        `${label} presetId가 잘못되었습니다.`,
      );
      requireCondition(!presetIds.has(entry.presetId), 'manifest에 중복 presetId가 있습니다.');
      presetIds.add(entry.presetId);
      declaredPresetCount += 1;
    }
    requireCondition(
      entry.detail?.path === `results/${entry.resultKey}.json`,
      `${label} detail path가 잘못되었습니다.`,
    );
    requireCondition(
      entry.summary?.path === `summaries/${entry.resultKey}.json`,
      `${label} summary path가 잘못되었습니다.`,
    );
    requireCondition(
      validSha256(entry.detail?.sha256)
        && integer(entry.detail?.bytes)
        && Number(entry.detail.bytes) > 0,
      `${label} detail reference가 잘못되었습니다.`,
    );
    requireCondition(
      validSha256(entry.summary?.sha256)
        && integer(entry.summary?.bytes)
        && Number(entry.summary.bytes) > 0,
      `${label} summary reference가 잘못되었습니다.`,
    );
  });
  requireCondition(
    declaredPresetCount === 0 || declaredPresetCount === manifest.entries.length,
    'manifest presetId는 모든 entry에 있거나 모두 없어야 합니다.',
  );
  requireCondition(resultKeys.has(manifest.defaultResultKey), 'manifest 기본 entry가 없습니다.');
  return manifest;
}

function resolveExactEntry(manifest, normalizedInputs) {
  const requested = canonicalString(normalizedInputs);
  return manifest.entries.find((entry) => canonicalString(entry.normalizedInputs) === requested) || null;
}

function entryByResultKey(manifest, resultKey) {
  return manifest.entries.find((entry) => entry.resultKey === resultKey) || null;
}

function entryByPresetId(manifest, presetId) {
  return manifest.entries.find((entry) => entry.presetId === presetId) || null;
}

function parseInputValue(field, raw) {
  const text = String(raw ?? '').trim();
  if (field.kind === 'string') {
    if (!text) throw new Error(`${field.key}가 비어 있습니다.`);
    return text;
  }
  if (!text || !Number.isFinite(Number(text))) {
    throw new Error(`${field.key}가 유효한 숫자가 아닙니다.`);
  }
  const value = Number(text);
  if (field.kind === 'integer' && !Number.isInteger(value)) {
    throw new Error(`${field.key}는 정수여야 합니다.`);
  }
  return field.kind === 'percent' ? value / 100 : value;
}

function serializeInputValue(field, value) {
  if (field.kind === 'percent') {
    const scaled = Number(value) * 100;
    return Number.isFinite(scaled) ? String(Number(scaled.toFixed(10))) : String(value);
  }
  return String(value);
}

function applyResearchInputDependencies(normalizedInputs) {
  if (integer(normalizedInputs.evaluation_window_days)) {
    const evaluationWindowDays = Number(normalizedInputs.evaluation_window_days);
    const minimumObservations = Math.min(
      evaluationWindowDays,
      Math.max(252, evaluationWindowDays - 252),
    );
    normalizedInputs.min_evaluation_observations = minimumObservations;
    normalizedInputs.min_daily_risk_observations = minimumObservations;
  }
  return normalizedInputs;
}

function researchInputsFromNormalizedInputs(normalizedInputs) {
  const result = { version: RESEARCH_INPUTS_VERSION };
  Object.entries(RESEARCH_INPUT_PARITY).forEach(([publicKey, normalizedKey]) => {
    requireCondition(
      Object.prototype.hasOwnProperty.call(normalizedInputs, normalizedKey),
      `로컬 API 입력에 ${normalizedKey}가 없습니다.`,
    );
    result[publicKey] = normalizedInputs[normalizedKey];
  });
  requireCondition(
    integer(normalizedInputs.evaluation_window_days)
      && Number(normalizedInputs.evaluation_window_days) >= 21
      && Number(normalizedInputs.evaluation_window_days) <= 2520,
    'evaluation_window_days는 21–2520 정수여야 합니다.',
  );
  return result;
}

function validateResearchInputsPayload(researchInputs, normalizedInputs) {
  requireCondition(isRecord(researchInputs), 'researchInputs가 객체가 아닙니다.');
  requireCondition(
    researchInputs.version === RESEARCH_INPUTS_VERSION
      || researchInputs.version === LEGACY_RESEARCH_INPUTS_VERSION,
    'researchInputs 버전 계약이 아닙니다.',
  );
  Object.entries(RESEARCH_INPUT_PARITY).forEach(([publicKey, normalizedKey]) => {
    requireCondition(
      Object.prototype.hasOwnProperty.call(researchInputs, publicKey)
        && Object.prototype.hasOwnProperty.call(normalizedInputs, normalizedKey)
        && sameJson(researchInputs[publicKey], normalizedInputs[normalizedKey]),
      `researchInputs.${publicKey}가 요청 입력과 다릅니다.`,
    );
  });
  if (researchInputs.version === LEGACY_RESEARCH_INPUTS_VERSION) {
    requireCondition(
      integer(researchInputs.evaluationYears)
        && Number(researchInputs.evaluationYears) * 252
          === Number(researchInputs.evaluationWindowDays),
      'legacy researchInputs 평가 기간 의미가 평가 창과 다릅니다.',
    );
  } else {
    requireCondition(
      !Object.prototype.hasOwnProperty.call(researchInputs, 'evaluationYears'),
      'research-inputs-v2에는 evaluationYears가 없어야 합니다.',
    );
  }
  return cloneJson(researchInputs);
}

function controlRunInputsFromNormalizedInputs(normalizedInputs) {
  const researchInputs = researchInputsFromNormalizedInputs(normalizedInputs);
  delete researchInputs.version;
  requireCondition(
    Object.keys(researchInputs).length === 26,
    '원격 분석 요청은 정확히 26개 ResearchInputs여야 합니다.',
  );
  return researchInputs;
}

function localApiRequestFromStaticState(manifest, requestedInputs) {
  const baseEntry = entryByResultKey(manifest, manifest.defaultResultKey);
  requireCondition(baseEntry, 'manifest 기본 최신 entry가 없습니다.');
  const normalizedInputs = cloneJson(baseEntry.normalizedInputs);
  INPUT_FIELDS.forEach((field) => {
    requireCondition(
      Object.prototype.hasOwnProperty.call(requestedInputs, field.key),
      `요청 URL에 공개 입력 ${field.key}가 없습니다.`,
    );
    normalizedInputs[field.key] = requestedInputs[field.key];
  });
  applyResearchInputDependencies(normalizedInputs);
  return { baseEntry, requestedInputs: normalizedInputs };
}

function requestFromSearch(manifest, search) {
  const params = new URLSearchParams(String(search || '').replace(/^\?/, ''));
  const requestedResultKey = params.get('result') || manifest.defaultResultKey;
  const requestedPresetId = params.get('preset');
  if (!validSha256(requestedResultKey)) {
    return {
      baseEntry: null,
      requestedInputs: null,
      entry: null,
      error: `resultKey가 잘못되었습니다. ${LOCAL_API_REQUIRED}`,
    };
  }
  if (requestedPresetId !== null && !PRESET_ID_PATTERN.test(requestedPresetId)) {
    return {
      baseEntry: null,
      requestedInputs: null,
      entry: null,
      error: `presetId가 잘못되었습니다. ${LOCAL_API_REQUIRED}`,
    };
  }
  let baseEntry = entryByResultKey(manifest, requestedResultKey);
  let recoveredFromRotatedResult = false;
  if (!baseEntry && requestedPresetId !== null) {
    baseEntry = entryByPresetId(manifest, requestedPresetId);
    recoveredFromRotatedResult = baseEntry !== null;
  }
  if (!baseEntry) {
    baseEntry = entryByResultKey(manifest, manifest.defaultResultKey);
    recoveredFromRotatedResult = baseEntry !== null;
  }
  if (!baseEntry) {
    return { baseEntry: null, requestedInputs: null, entry: null, error: LOCAL_API_REQUIRED };
  }
  const requestedInputs = cloneJson(baseEntry.normalizedInputs);
  try {
    INPUT_FIELDS.forEach((field) => {
      if (params.has(field.key)) {
        requestedInputs[field.key] = parseInputValue(field, params.get(field.key));
      }
    });
    if (params.has('evaluationYears')) {
      const evaluationYears = Number(params.get('evaluationYears'));
      if (!Number.isInteger(evaluationYears) || evaluationYears < 1 || evaluationYears > 10) {
        throw new Error('evaluationYears는 1–10 정수여야 합니다.');
      }
      const impliedWindow = evaluationYears * 252;
      if (
        params.has('evaluation_window_days')
        && Number(requestedInputs.evaluation_window_days) !== impliedWindow
      ) {
        throw new Error('evaluationYears와 evaluation_window_days가 다릅니다.');
      }
      requestedInputs.evaluation_window_days = impliedWindow;
    }
    if (params.has('evaluation_window_days') || params.has('evaluationYears')) {
      applyResearchInputDependencies(requestedInputs);
    }
  } catch (error) {
    return {
      baseEntry,
      requestedInputs,
      entry: null,
      error: `${error.message} ${LOCAL_API_REQUIRED}`,
      recoveredFromRotatedResult,
    };
  }
  const entry = resolveExactEntry(manifest, requestedInputs);
  return {
    baseEntry,
    requestedInputs,
    entry,
    error: entry ? null : LOCAL_API_REQUIRED,
    recoveredFromRotatedResult,
  };
}

function searchForRequest(resultKey, normalizedInputs, presetId = null) {
  const params = new URLSearchParams();
  params.set('result', resultKey);
  if (presetId !== null) params.set('preset', presetId);
  INPUT_FIELDS.forEach((field) => {
    if (Object.prototype.hasOwnProperty.call(normalizedInputs, field.key)) {
      params.set(field.key, serializeInputValue(field, normalizedInputs[field.key]));
    }
  });
  return `?${params.toString()}`;
}

function pairKey(row) {
  return `${row.factor}::${row.policy_id}`;
}

function rowReasonCodes(row) {
  return [...new Set([
    ...(Array.isArray(row.guardrail_breaches) ? row.guardrail_breaches : []),
    ...(Array.isArray(row.contribution_guardrail_breaches)
      ? row.contribution_guardrail_breaches
      : []),
    ...(Array.isArray(row.exclusion_reason_codes) ? row.exclusion_reason_codes : []),
  ].filter(
    (value) => typeof value === 'string' && value.trim(),
  ).map((value) => value.trim()))];
}

function validateTargetAllocation(payload) {
  const target = payload.bestFactorPortfolio;
  const config = payload.config;
  requireCondition(isRecord(target) && isRecord(config), 'bestFactorPortfolio/config가 없습니다.');
  const maxWeight = Number(config.max_weight);
  requireCondition(
    finite(maxWeight) && maxWeight > 0 && maxWeight <= 1,
    'config.max_weight가 잘못되었습니다.',
  );
  requireCondition(Array.isArray(target.weights), 'bestFactorPortfolio.weights가 배열이 아닙니다.');
  requireCondition(
    integer(target.selectedSecurityCount)
      && Number(target.selectedSecurityCount) === target.weights.length,
    'bestFactorPortfolio 종목 수가 다릅니다.',
  );
  requireCondition(
    integer(config.top_n)
      && Number(config.top_n) >= 1
      && Number(config.top_n) <= 50
      && target.weights.length <= Number(config.top_n),
    'bestFactorPortfolio 종목 수 또는 Top-N이 잘못되었습니다.',
  );
  requireCondition(
    integer(target.eligibleSecurityCount)
      && Number(target.eligibleSecurityCount) >= target.weights.length,
    'bestFactorPortfolio 적격 종목 수가 잘못되었습니다.',
  );

  const symbols = new Set();
  const weights = target.weights.map((row, index) => {
    const symbol = typeof row?.symbol === 'string' ? row.symbol.trim().toUpperCase() : '';
    const weight = Number(row?.weight);
    requireCondition(
      isRecord(row)
        && row.rank === index + 1
        && symbol
        && !symbols.has(symbol)
        && finite(row.factorScore)
        && finite(weight)
        && weight > 0
        && weight <= maxWeight + 1e-12,
      'bestFactorPortfolio 보유 행이 잘못되었습니다.',
    );
    if (Object.prototype.hasOwnProperty.call(row, 'maxWeight')) {
      requireCondition(
        closeNumber(row.maxWeight, maxWeight),
        '보유 행 maxWeight가 config와 다릅니다.',
      );
    }
    symbols.add(symbol);
    return weight;
  });
  const cashWeight = Number(target.cashWeight);
  requireCondition(
    finite(cashWeight) && cashWeight >= 0 && cashWeight <= 1,
    'bestFactorPortfolio 현금 비중이 잘못되었습니다.',
  );
  requireCondition(
    closeNumber(weights.reduce((sum, value) => sum + value, 0) + cashWeight, 1),
    'bestFactorPortfolio 비중과 현금의 합이 1이 아닙니다.',
  );

  const concentration = target.concentration;
  requireCondition(isRecord(concentration), 'bestFactorPortfolio concentration이 없습니다.');
  const invested = weights.reduce((sum, value) => sum + value, 0);
  const normalized = invested > 0 ? weights.map((value) => value / invested) : [];
  const hhi = normalized.reduce((sum, value) => sum + value * value, 0);
  const ordered = weights.slice().sort((left, right) => right - left);
  const expected = {
    investedWeight: invested,
    cashWeight,
    riskySleeveHhi: hhi,
    effectiveNames: hhi > 0 ? 1 / hhi : 0,
    top1Weight: ordered.slice(0, 1).reduce((sum, value) => sum + value, 0),
    top5Weight: ordered.slice(0, 5).reduce((sum, value) => sum + value, 0),
    maxWeight: ordered[0] || 0,
  };
  Object.entries(expected).forEach(([field, value]) => {
    requireCondition(
      closeNumber(concentration[field], value),
      `bestFactorPortfolio concentration.${field}가 잘못되었습니다.`,
    );
  });
  return { target, maxWeight };
}


function validateFactorHoldingHistorySidecarData(payload, data) {
  const expectedFields = [
    'contract',
    'contractVersion',
    'resultKey',
    'weightingPolicy',
    'weightTiming',
    'startDate',
    'endDate',
    'sessionCount',
    'dates',
    'factorCount',
    'independentFactorCount',
    'diagnosticFactorCount',
    'factorDefinitionSha256',
    'policyDefinitionSha256',
    'symbols',
    'factors',
  ];
  const definitions = Array.isArray(payload.factorDefinitions) ? payload.factorDefinitions : [];
  const factorIds = definitions.map((row) => row?.factor).filter(requiredText).sort();
  const independent = definitions
    .filter((row) => row?.selection_eligible === true && row?.compatibility_alias_of === null)
    .map((row) => row.factor)
    .sort();
  const independentSet = new Set(independent);
  const diagnostic = factorIds.filter((factor) => !independentSet.has(factor));
  const dates = payload.performance.dates.slice(-SELECTED_HOLDING_HISTORY_SESSION_COUNT);
  requireCondition(
    exactRecordKeys(data, expectedFields)
      && factorIds.length === EXPECTED_INDEPENDENT_FACTOR_COUNT + EXPECTED_ALIAS_FACTOR_COUNT
      && independent.length === EXPECTED_INDEPENDENT_FACTOR_COUNT
      && diagnostic.length === EXPECTED_ALIAS_FACTOR_COUNT
      && data.contract === FACTOR_HOLDING_HISTORY_SIDECAR_CONTRACT
      && data.contractVersion === FACTOR_HOLDING_HISTORY_SIDECAR_CONTRACT_VERSION
      && data.resultKey === payload.resultKey
      && data.weightingPolicy === payload.weightingPolicy
      && data.weightTiming === SELECTED_HOLDING_HISTORY_WEIGHT_TIMING
      && data.startDate === dates[0]
      && data.endDate === dates.at(-1)
      && data.sessionCount === SELECTED_HOLDING_HISTORY_SESSION_COUNT
      && sameJson(data.dates, dates)
      && data.factorCount === factorIds.length
      && data.independentFactorCount === independent.length
      && data.diagnosticFactorCount === diagnostic.length
      && data.factorDefinitionSha256 === payload.meta?.factorDefinitionSha256
      && data.policyDefinitionSha256 === payload.meta?.policyDefinitionSha256,
    '팩터별 보유 이력 sidecar provenance/date/count 계약이 잘못되었습니다.',
  );

  requireCondition(Array.isArray(data.symbols), '팩터별 보유 이력 symbol dictionary가 배열이 아닙니다.');
  const symbols = [];
  const names = [];
  data.symbols.forEach((row, index) => {
    requireCondition(
      Array.isArray(row)
        && row.length === 2
        && requiredText(row[0])
        && requiredText(row[1]),
      `팩터별 보유 이력 symbols[${index}]가 잘못되었습니다.`,
    );
    symbols.push(row[0]);
    names.push(row[1]);
  });
  requireCondition(
    new Set(symbols).size === symbols.length
      && sameJson([...symbols].sort(), symbols),
    '팩터별 보유 이력 symbol dictionary의 순서/유일성이 잘못되었습니다.',
  );

  requireCondition(
    isRecord(data.factors)
      && sameJson(Object.keys(data.factors).sort(), factorIds),
    '팩터별 보유 이력이 64개 팩터를 정확히 포함하지 않습니다.',
  );
  const allowedStatuses = new Set(HOLDING_EXECUTION_STATUSES);
  const selectedSessions = [];
  const topN = payload.config.top_n;
  factorIds.forEach((factor) => {
    const factorHistory = data.factors[factor];
    requireCondition(
      exactRecordKeys(factorHistory, ['factor', 'weightingPolicyId', 'resultKey', 'sessions'])
        && factorHistory.factor === factor
        && factorHistory.weightingPolicyId === payload.weightingPolicy
        && factorHistory.resultKey === payload.resultKey
        && Array.isArray(factorHistory.sessions)
        && factorHistory.sessions.length === dates.length,
      `팩터별 보유 이력 ${factor} identity/session 계약이 잘못되었습니다.`,
    );
    let previousMetadata = null;
    factorHistory.sessions.forEach((session, sessionIndex) => {
      const date = dates[sessionIndex];
      const signalDate = session?.lastSignalDate;
      const executionDate = session?.lastExecutionDate;
      const metadata = [signalDate, executionDate];
      requireCondition(
        exactRecordKeys(session, [
          'valuationAvailable',
          'cashWeight',
          'executionStatus',
          'lastSignalDate',
          'lastExecutionDate',
          'weights',
        ])
          && typeof session.valuationAvailable === 'boolean'
          && strictJsonNumber(session.cashWeight)
          && session.cashWeight >= 0
          && session.cashWeight <= 1
          && allowedStatuses.has(session.executionStatus)
          && ((signalDate === null && executionDate === null)
            || (requiredText(signalDate)
              && requiredText(executionDate)
              && signalDate <= executionDate
              && executionDate <= date)),
        `팩터별 보유 이력 ${factor}/${date} metadata가 잘못되었습니다.`,
      );
      if (['executed', 'executed_partial_unpriceable_targets'].includes(session.executionStatus)) {
        requireCondition(
          executionDate === date,
          `팩터별 보유 이력 ${factor}/${date} 체결일이 다릅니다.`,
        );
      } else if (sessionIndex > 0) {
        requireCondition(
          sameJson(metadata, previousMetadata),
          `팩터별 보유 이력 ${factor}/${date} 미체결 메타데이터가 변경되었습니다.`,
        );
      }
      previousMetadata = metadata;
      requireCondition(
        Array.isArray(session.weights) && session.weights.length <= topN,
        `팩터별 보유 이력 ${factor}/${date} 비중 개수가 top_n을 넘습니다.`,
      );
      const observedIndexes = new Set();
      const expandedWeights = [];
      let total = session.cashWeight;
      session.weights.forEach((pair, index) => {
        const symbolIndex = pair?.[0];
        const weight = pair?.[1];
        requireCondition(
          Array.isArray(pair)
            && pair.length === 2
            && Number.isInteger(symbolIndex)
            && symbolIndex >= 0
            && symbolIndex < symbols.length
            && !observedIndexes.has(symbolIndex)
            && strictJsonNumber(weight)
            && weight > 0
            && weight <= 1,
          `팩터별 보유 이력 ${factor}/${date}/weights[${index}]가 잘못되었습니다.`,
        );
        observedIndexes.add(symbolIndex);
        total += weight;
        expandedWeights.push({
          rank: index + 1,
          symbol: symbols[symbolIndex],
          name: names[symbolIndex],
          weight,
        });
      });
      requireCondition(
        closeNumber(total, 1)
          && sameJson(
            expandedWeights.map((row) => [row.weight, row.symbol]),
            [...expandedWeights]
              .sort(compareWeightSymbolOrder)
              .map((row) => [row.weight, row.symbol]),
          ),
        `팩터별 보유 이력 ${factor}/${date} 배분/정렬이 잘못되었습니다.`,
      );
      if (factor === payload.bestFactor) {
        selectedSessions.push({
          date,
          valuationAvailable: session.valuationAvailable,
          cashWeight: session.cashWeight,
          executionStatus: session.executionStatus,
          lastSignalDate: signalDate,
          lastExecutionDate: executionDate,
          weights: expandedWeights,
        });
      }
    });
  });
  requireCondition(
    sameJson(selectedSessions, payload.bestFactorBacktestHoldingHistory.sessions),
    '팩터별 보유 이력 sidecar의 최고 팩터가 Python history와 다릅니다.',
  );
  return data;
}

function validateFactorHoldingHistorySidecarManifest(payload) {
  const manifest = payload.factorHoldingHistorySidecar;
  const hasData = isRecord(manifest) && Object.prototype.hasOwnProperty.call(manifest, 'data');
  const expectedFields = [
    'contract',
    'contractVersion',
    'storage',
    'path',
    'sha256',
    'bytes',
    'resultKey',
    'weightingPolicy',
    'weightTiming',
    'startDate',
    'endDate',
    'sessionCount',
    'factorCount',
    'independentFactorCount',
    'diagnosticFactorCount',
    ...(hasData ? ['data'] : []),
  ];
  const expectedPath = `data/${FACTOR_HOLDING_HISTORY_SIDECAR_DIRECTORY}/${payload.resultKey}.json`;
  requireCondition(
    exactRecordKeys(manifest, expectedFields)
      && manifest.contract === FACTOR_HOLDING_HISTORY_SIDECAR_CONTRACT
      && manifest.contractVersion === FACTOR_HOLDING_HISTORY_SIDECAR_CONTRACT_VERSION
      && manifest.storage === (hasData ? 'embedded' : 'external')
      && manifest.path === expectedPath
      && validSha256(manifest.sha256)
      && nonnegativeInteger(manifest.bytes)
      && manifest.bytes >= 1
      && manifest.bytes <= MAX_FACTOR_HOLDING_HISTORY_SIDECAR_BYTES
      && manifest.resultKey === payload.resultKey
      && manifest.weightingPolicy === payload.weightingPolicy
      && manifest.weightTiming === SELECTED_HOLDING_HISTORY_WEIGHT_TIMING
      && manifest.startDate === payload.bestFactorBacktestHoldingHistory.startDate
      && manifest.endDate === payload.bestFactorBacktestHoldingHistory.endDate
      && manifest.sessionCount === SELECTED_HOLDING_HISTORY_SESSION_COUNT
      && manifest.factorCount === EXPECTED_INDEPENDENT_FACTOR_COUNT + EXPECTED_ALIAS_FACTOR_COUNT
      && manifest.independentFactorCount === EXPECTED_INDEPENDENT_FACTOR_COUNT
      && manifest.diagnosticFactorCount === EXPECTED_ALIAS_FACTOR_COUNT
      && manifest.factorCount === payload.meta?.factorCount
      && manifest.independentFactorCount === payload.meta?.independentFactorCount
      && manifest.diagnosticFactorCount === payload.meta?.aliasFactorCount,
    '팩터별 보유 이력 sidecar manifest 계약이 잘못되었습니다.',
  );
  if (hasData) validateFactorHoldingHistorySidecarData(payload, manifest.data);
  return manifest;
}


async function validateResult(entry, payload, summary = null, options = {}) {
  const apiResult = options.source === 'local_api' || options.source === 'remote_api';
  requireCondition(
    isRecord(payload) && payload.schemaVersion === RESULT_SCHEMA_VERSION,
    `detail schemaVersion ${RESULT_SCHEMA_VERSION}가 아닙니다.`,
  );
  const forbidden = [
    'selectedFactor',
    'selectedWeightingPolicy',
    'selectedReason',
    'selectionDecision',
    'factorPolicyRanking',
    'policyDiagnostics',
    'weightingPolicyRegistry',
    'gridAccounting',
    'currentResearchTarget',
    'currentTransition',
    'selectedBacktestHoldingHistory',
  ];
  requireCondition(
    forbidden.every((field) => !Object.prototype.hasOwnProperty.call(payload, field)),
    'detail에 제거된 현재 Python/팩터×정책 계약 필드가 남아 있습니다.',
  );
  const required = [
    'bestFactor',
    'weightingPolicy',
    'bestFactorReason',
    'factorSelectionDecision',
    'factorAccounting',
    'factorRanking',
    'weightingMethodology',
    'allocationMethod',
    'bestFactorPortfolio',
    'factorPortfolios',
    'bestFactorTransition',
    'performance',
    'backtestHeldPortfolio',
    'bestFactorBacktestHoldingHistory',
    'factorHoldingHistorySidecar',
    'factorDefinitions',
    'factorDiagnostics',
    'researchInputs',
    'researchScope',
    'config',
    'meta',
    'data',
  ];
  required.forEach((field) => requireCondition(
    Object.prototype.hasOwnProperty.call(payload, field),
    `detail 필드가 없습니다: ${field}`,
  ));

  validateIdentity(payload.resultIdentity, entry.resultKey, 'detail', {
    requireCanonicalTransport: !apiResult,
  });
  requireCondition(
    sameJson(payload.resultIdentity, entry.identity),
    apiResult
      ? 'detail resultIdentity가 API 응답 identity와 다릅니다.'
      : 'detail resultIdentity가 manifest와 다릅니다.',
  );
  requireCondition(payload.resultKey === entry.resultKey, 'detail resultKey가 다릅니다.');
  const data = payload.data;
  requireCondition(
    isRecord(data)
      && data.synthetic === false
      && data.mode === 'live_market'
      && integer(data.analyzedSecurityCount)
      && Number(data.analyzedSecurityCount) >= 2700
      && requiredText(data.asOf),
    '결과는 2,700개 이상 종목의 실제시장 비합성 실행이어야 합니다.',
  );
  const observedHashFields = isRecord(data.inputSha256)
    ? Object.keys(data.inputSha256).sort()
    : [];
  requireCondition(
    sameJson(observedHashFields, [...LIVE_INPUT_HASH_FIELDS].sort())
      && observedHashFields.every((field) => validSha256(data.inputSha256[field])),
    '실제시장 provenance 입력 해시 계약이 다릅니다.',
  );
  validateResearchInputsPayload(payload.researchInputs, entry.normalizedInputs);
  if (apiResult) {
    requireCondition(
      sameJson(payload.researchInputs, options.expectedResearchInputs),
      'API 결과 researchInputs가 요청과 다릅니다.',
    );
  }

  const policyId = 'score_liquidity_rank';
  const policy = payload.weightingMethodology;
  const allocation = payload.allocationMethod;
  const config = payload.config;
  requireCondition(
    payload.weightingPolicy === policyId
      && isRecord(policy)
      && policy.policyId === policyId
      && policy.optimized === false
      && Object.keys(policy).every((key) => ['registryVersion', 'policyId', 'policy', 'optimized'].includes(key))
      && isRecord(policy.policy)
      && policy.policy.selectionRole === 'fixed_methodology_not_optimized'
      && isRecord(allocation)
      && allocation.policyId === policyId
      && allocation.fixed === true,
    '비중 방식은 고정 팩터·유동성 방법이어야 합니다.',
  );
  const parameters = allocation.parameters;
  requireCondition(
    isRecord(parameters)
      && closeNumber(parameters.factorScoreWeight, 0.70)
      && closeNumber(parameters.liquidityWeight, 0.30)
      && closeNumber(parameters.marketCapWeight, 0.00)
      && closeNumber(parameters.rankFloor, 0.05)
      && closeNumber(config.allocation_score_weight, 0.70)
      && closeNumber(config.allocation_liquidity_weight, 0.30)
      && closeNumber(config.allocation_market_cap_weight, 0.00)
      && closeNumber(config.allocation_rank_floor, 0.05)
      && parameters.topN === config.top_n
      && closeNumber(parameters.maxWeight, config.max_weight),
    '고정 비중 방법의 70/30 입력 또는 상한이 다릅니다.',
  );

  const definitions = payload.factorDefinitions;
  const ranking = payload.factorRanking;
  const portfolios = payload.factorPortfolios;
  requireCondition(
    Array.isArray(definitions)
      && definitions.length === EXPECTED_INDEPENDENT_FACTOR_COUNT + EXPECTED_ALIAS_FACTOR_COUNT
      && Array.isArray(ranking)
      && ranking.length === definitions.length
      && isRecord(portfolios)
      && Object.keys(portfolios).length === definitions.length,
    '팩터 정의·랭킹·포트폴리오의 64개 coverage가 다릅니다.',
  );
  const factors = definitions.map((row) => row?.factor);
  requireCondition(
    factors.every(requiredText)
      && new Set(factors).size === factors.length
      && sameJson(Object.keys(portfolios).sort(), [...factors].sort()),
    '팩터 식별자 또는 포트폴리오 coverage가 잘못되었습니다.',
  );
  requireCondition(
    ranking.every((row) => isRecord(row) && factors.includes(row.factor) && row.policy_id === policyId)
      && new Set(ranking.map((row) => row.factor)).size === ranking.length,
    'factorRanking은 고정 정책 아래 팩터별 한 행이어야 합니다.',
  );
  const selectedRows = ranking.filter((row) => row.selected === true);
  requireCondition(
    selectedRows.length === 1
      && selectedRows[0].factor === payload.bestFactor
      && selectedRows[0].selection_eligible === true
      && selectedRows[0].selection_status === 'eligible'
      && finite(selectedRows[0].selection_score),
    'Python 최고 팩터 선택 행이 정확히 하나가 아닙니다.',
  );
  const accounting = payload.factorAccounting;
  requireCondition(
    isRecord(accounting)
      && accounting.expectedIndependentFactorCount === EXPECTED_INDEPENDENT_FACTOR_COUNT
      && accounting.evaluatedIndependentFactorCount === EXPECTED_INDEPENDENT_FACTOR_COUNT
      && accounting.diagnosticAliasFactorCount === EXPECTED_ALIAS_FACTOR_COUNT
      && accounting.availableIndependentFactorCount + accounting.excludedIndependentFactorCount
        === EXPECTED_INDEPENDENT_FACTOR_COUNT,
    'factorAccounting이 61개 독립 팩터 계약과 다릅니다.',
  );

  const { target, maxWeight } = validateTargetAllocation(payload);
  requireCondition(
    target === payload.bestFactorPortfolio
      && sameJson(target, portfolios[payload.bestFactor])
      && target.factor === payload.bestFactor
      && target.weightingPolicyId === policyId
      && target.targetType === 'factor_portfolio'
      && target.asOf === data.asOf
      && target.signalDate === data.asOf,
    '동일 입력 최고 팩터 포트폴리오가 팩터 결과와 다릅니다.',
  );
  target.weights.forEach((row) => {
    const components = [row.scoreComponent, row.liquidityComponent];
    requireCondition(
      components.every((value) => finite(value) && Number(value) >= 0 && Number(value) <= 1)
        && finite(row.trailingDollarVolume)
        && Number(row.trailingDollarVolume) > 0
        && row.trailingMarketCap === null
        && closeNumber(row.marketCapComponent, 0.0),
      '포트폴리오의 팩터·유동성 구성값이 잘못되었습니다.',
    );
    const expectedRaw = 0.05
      + 0.70 * Number(row.scoreComponent)
      + 0.30 * Number(row.liquidityComponent);
    requireCondition(closeNumber(row.rawPolicyScore, expectedRaw), '고정 비중 raw score가 다릅니다.');
  });

  requireCondition(
    isRecord(payload.performance)
      && payload.performance.weightingPolicyId === policyId
      && Array.isArray(payload.performance.dates)
      && payload.performance.dates.length === Number(config.evaluation_window_days) + 1
      && isRecord(payload.performance.factorCurves)
      && sameJson(Object.keys(payload.performance.factorCurves).sort(), [...factors].sort()),
    'Python 성과 곡선의 입력 기간 또는 팩터 coverage가 다릅니다.',
  );
  if (!apiResult) {
    requireCondition(
      isRecord(summary)
        && summary.schemaVersion === RESULT_SCHEMA_VERSION
        && sameJson(summary.resultIdentity, payload.resultIdentity)
        && summary.bestFactor === payload.bestFactor
        && summary.weightingPolicy === policyId
        && sameJson(summary.bestFactorPortfolio, target)
        && sameJson(summary.weights, target.weights)
        && closeNumber(summary.cashWeight, target.cashWeight)
        && closeNumber(summary.maxWeight, maxWeight),
      'summary/detail 최고 팩터 또는 포트폴리오가 다릅니다.',
    );
  }
  return selectedRows[0];
}

function bindManualUpdateControls() {
  const button = document.querySelector('#manual-update-button');
  if (button) {
    button.setAttribute('href', MANUAL_UPDATE_WORKFLOW_URL);
    button.setAttribute('target', '_blank');
    button.setAttribute('rel', 'noopener');
    if (typeof button.addEventListener === 'function') {
      button.addEventListener('click', () => {
        const status = document.querySelector('#manual-update-status');
        if (status) {
          status.textContent = '저장소 쓰기 권한이 있는 GitHub 계정으로 Run workflow를 눌러 실행 시점의 최신 제공자 데이터 재실행을 시작하세요.';
        }
      });
    }
  }

  const command = document.querySelector('#manual-update-command');
  if (command) command.textContent = MANUAL_UPDATE_COMMAND;

  const copyButton = document.querySelector('#copy-update-command');
  if (!copyButton || typeof copyButton.addEventListener !== 'function') return;
  copyButton.addEventListener('click', async () => {
    const status = document.querySelector('#manual-update-status');
    try {
      if (typeof navigator === 'undefined' || !navigator.clipboard || !window.isSecureContext) {
        throw new Error('clipboard unavailable');
      }
      await navigator.clipboard.writeText(MANUAL_UPDATE_COMMAND);
      if (status) status.textContent = 'CLI 실행 명령을 복사했습니다. 터미널에서 붙여넣어 수동 실행할 수 있습니다.';
    } catch (_) {
      if (status) status.textContent = `복사가 제한되었습니다. 아래 명령을 직접 복사하세요: ${MANUAL_UPDATE_COMMAND}`;
    }
  });
}

const formatPercent = (value) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-';
  return `${(Number(value) * 100).toFixed(2)}%`;
};

const formatNumber = (value) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-';
  return Number(value).toLocaleString('ko-KR', { maximumFractionDigits: 4 });
};

const formatInteger = (value) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-';
  return Number(value).toLocaleString('ko-KR', { maximumFractionDigits: 0 });
};

const formatCount = (value) => {
  const formatted = formatInteger(value);
  return formatted === '-' ? '-' : `${formatted}개`;
};

const classForNumber = (value) => Number(value) >= 0 ? 'positive' : 'negative';
const textValue = (value) => value === null || value === undefined ? '-' : String(value);
const joinReasonList = (value) => {
  if (Array.isArray(value)) return value.map(textValue).filter((item) => item !== '-').join(', ');
  const text = textValue(value);
  return text === '-' ? '' : text;
};

function formatKoreanDateTime(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return textValue(value);
  return `${date.toLocaleString('ko-KR', {
    timeZone: 'Asia/Seoul',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })} KST`;
}

function humanProvider(value) {
  const text = textValue(value);
  const labels = {
    'yfinance-free-public-data': '야후 파이낸스 무료 공개 데이터',
    'yahoo-chart-fallback': 'Yahoo chart 조정종가 보강 데이터',
    'nasdaq-latest-repair': 'Nasdaq 최신 종가 보강 데이터',
    'stooq-fallback': 'Stooq 무료 일별 종가 대체 데이터',
    'finance-datareader-fallback': 'FinanceDataReader 무료 종가 대체 데이터',
    'no-live-price-provider': '사용 가능한 실시간 가격 제공자 없음',
    'offline-sample': '오프라인 샘플 데이터',
    'offline_sample': '오프라인 샘플 데이터',
  };
  if (text.includes('+')) {
    return text.split('+').map((part) => labels[part] || `기타 제공자(${part})`).join(' + ');
  }
  return labels[text] || text;
}

function humanOutputLabel(value) {
  const text = textValue(value);
  const labels = {
    'Research signals (not tradable)': '연구용 신호',
    'Practical recommendations': '실행 가능성 검토를 통과한 추천 후보',
    'No current recommendation': '현재 추천 후보 없음',
  };
  return labels[text] || text;
}

function automationDate(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
    ? value : null;
}

function automationTimestamp(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T.+(?:Z|[+-]\d{2}:\d{2})$/.test(value)) return null;
  if (!automationDate(value.slice(0, 10))) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function validateAutomationStatus(status, reference, now = Date.now()) {
  requireCondition(
    isRecord(status) && status.schemaVersion === 1
      && status.contract === AUTOMATION_STATUS_CONTRACT
      && status.project === 'momentum-factor-lab'
      && ['available', 'degraded', 'failed', 'unavailable'].includes(status.state),
    '자동화 상태 형식을 확인할 수 없습니다.',
  );
  const attemptedAt = automationTimestamp(status.attemptedAtUtc);
  const generatedAt = automationTimestamp(reference?.generatedAtUtc);
  requireCondition(
    attemptedAt !== null && generatedAt !== null
      && attemptedAt >= generatedAt && attemptedAt <= now + 5 * 60 * 1000,
    '자동화 상태 시각과 공개 결과가 일치하지 않습니다.',
  );
  requireCondition(
    validSha256(reference?.resultKey) && automationDate(reference?.dataAsOf)
      && reference.path === 'data/dashboard.json'
      && isRecord(status.lastGood)
      && ['resultKey', 'dataAsOf', 'generatedAtUtc', 'path'].every((key) => (
        status.lastGood[key] === reference[key]
      )),
    '자동화 상태와 공개 결과가 일치하지 않습니다.',
  );
  requireCondition(
    (status.targetDataAsOf === null || automationDate(status.targetDataAsOf))
      && typeof status.reasonCode === 'string' && status.reasonCode.length > 0
      && isRecord(status.publication),
    '자동화 갱신 정보를 확인할 수 없습니다.',
  );
  if (status.state === 'available') {
    requireCondition(
      status.publication.updated === true && status.targetDataAsOf === reference.dataAsOf,
      '자동화 성공 기록과 공개 결과가 일치하지 않습니다.',
    );
  } else {
    requireCondition(
      status.publication.updated === false && status.publication.lastGoodPreserved === true,
      '자동화 보존 기록과 공개 결과가 일치하지 않습니다.',
    );
  }
  return status;
}

function automationReason(status) {
  const reasons = {
    no_comparable_factor: '공통 평가기간을 충족한 팩터 없음',
    no_eligible_factor: '품질 기준을 통과한 팩터 없음',
    execution_failed: '수집·분석 실행 실패',
    stale_market_data: '목표 거래일의 시장 데이터 미확보',
    incomplete_market_session: '아직 완료되지 않은 시장 거래일 감지',
    published: '수집·검증 완료',
  };
  return reasons[status?.reasonCode] || '수집·분석 또는 검증 실패';
}

function automationStatusView({ automation, payload, manifest, source, summary = {} }) {
  if (!isRecord(payload)) {
    return {
      title: '검증 결과 없음', detail: '표시할 검증 결과가 없습니다.', tone: 'error',
      automationTitle: '자동화 상태 확인 불가', automationDetail: '공개 결과를 대조할 수 없음',
      automationTone: 'error',
      attemptedAtUtc: null, historical: false,
    };
  }
  const asOf = payload?.data?.asOf || summary.data_as_of || '-';
  const defaultEntry = manifest?.entries?.find((entry) => entry.resultKey === manifest.defaultResultKey);
  const defaultAsOf = defaultEntry?.identity?.keyParts?.marketSnapshot?.dataAsOf;
  const historical = source === 'static_grid' && automationDate(asOf)
    && automationDate(defaultAsOf) && asOf < defaultAsOf;
  const resultLabel = historical ? '과거 기준 조회' : '개별 검증 결과';
  let title = '자동화 상태 확인 중';
  let tone = 'pending';
  let detail = `마지막 검증 기준일 ${asOf}`;
  let status = null;
  if (automation?.phase === 'loaded') {
    try {
      status = validateAutomationStatus(automation.status, automation.reference);
      if (source === 'static_grid' && payload?.resultKey === manifest?.defaultResultKey) {
        requireCondition(
          payload.resultKey === automation.reference.resultKey
            && payload.data?.asOf === automation.reference.dataAsOf
            && payload.generatedAtUtc === automation.reference.generatedAtUtc,
          '현재 결과와 자동화 기록이 일치하지 않습니다.',
        );
      }
      if (status.state === 'available') {
        title = '수집·검증 완료';
        tone = 'ok';
      } else {
        title = status.state === 'degraded' ? '갱신 보류' : '갱신 실패';
        tone = 'error';
      }
      detail = `마지막 검증 기준일 ${automation.reference.dataAsOf}`;
      if (status.state !== 'available') {
        detail += ` · 목표일 ${status.targetDataAsOf || '확인 불가'} · ${automationReason(status)}`;
      }
    } catch (error) {
      status = null;
      title = '자동화 상태 확인 불가';
      detail += ' · 상태 기록과 공개 결과를 대조할 수 없음';
    }
  } else if (automation?.phase === 'error') {
    title = '자동화 상태 확인 불가';
    detail += ' · 상태 파일을 불러오지 못함';
  }
  const individual = source === 'local_api' || source === 'remote_api';
  return {
    title: historical || individual ? resultLabel : title,
    detail: historical || individual ? `조회 기준일 ${asOf} · ${humanOutputLabel(summary.recommendation_output_label)}` : detail,
    tone: historical || individual ? 'neutral' : tone,
    automationTitle: title,
    automationDetail: detail,
    automationTone: tone,
    attemptedAtUtc: status?.attemptedAtUtc || null,
    historical,
  };
}

function isPracticalRun(run = currentRun()) {
  const summary = run.summary || {};
  return summary.recommendation_output_key === 'recommendations'
    && summary.research_only === false
    && summary.recommendation_output_available === true
    && summary.tradable_output_available === true
    && summary.current_recommendations_available === true
    && summary.tradable_recommendations_available === true
    && summary.same_run_factor_selection_blocked_for_tradable === false
    && summary.same_sample_selection_blocked_for_tradable === false;
}

function humanFactorCategory(value) {
  const text = textValue(value);
  const labels = {
    traditional: '전통 모멘텀',
    recent: '최근 수익률',
    composite: '복합 모멘텀',
    risk_adjusted: '위험조정 모멘텀',
    trend: '추세/이동평균',
    drawdown: '낙폭/고점 근접',
    breakout: '돌파',
    reversal: '반전 보정',
    acceleration: '가속도',
    quality: '추세 품질',
    cross_sectional: '횡단면 상대강도',
    robust: '이상치 완화',
    range: '가격 범위 위치',
    unknown: '분류 정보 없음',
  };
  return labels[text] || `기타(${text})`;
}

function humanWeightingMethod(value) {
  const text = textValue(value);
  const labels = {
    equal: '동일 비중',
    score_size_liquidity: '점수·규모·유동성 기반',
    score_proportional_capped: '팩터 점수 비례·상한 적용',
    best_factor_score_proportional_capped: '최고 팩터 점수 비례·상한 적용',
    top_factor_equal_sleeve: '상위 팩터 동일비중 합산',
  };
  return labels[text] || text;
}

function currentRun() {
  const runs = state.data?.runs || [];
  return runs[state.activeRunIndex] || runs[state.data?.latest_run_index || 0] || state.data?.latest || {};
}

function runPayloadGeneratedAt(run) {
  return run?.generated_at_utc || state.data?.generated_at_utc || null;
}

function uniqueDates(run) {
  const historyDates = Object.values(run.factor_holding_histories || {})
    .flatMap((history) => history?.sessions || [])
    .map((session) => session?.date)
    .filter(Boolean);
  return [...new Set([
    run.summary?.data_as_of,
    ...historyDates,
  ].filter(Boolean))].sort().reverse();
}

function selectedDate() {
  return document.querySelector('#date-select').value;
}

function selectedWindow() {
  return document.querySelector('#window-select')?.value || 'FULL';
}

function selectedFactor() {
  const selector = document.querySelector('#factor-select');
  return selector?.value || currentRun().summary?.selected_factor || '';
}

function selectedLookbackMonths() {
  const sessions = Number(state.payload?.config?.evaluation_window_days);
  return Number.isFinite(sessions) ? Math.max(1, Math.round(sessions / 21)) : DASHBOARD_INPUT_DEFAULTS.lookbackMonths;
}

function selectedRebalanceFrequency() {
  const value = state.payload?.config?.rebalance_frequency || DASHBOARD_INPUT_DEFAULTS.rebalanceFrequency;
  return ['W', 'ME', 'QE'].includes(value) ? value : DASHBOARD_INPUT_DEFAULTS.rebalanceFrequency;
}

function clampedTransactionCostBps() {
  return clampNumber(state.payload?.config?.transaction_cost_bps, 0, 200, DASHBOARD_INPUT_DEFAULTS.transactionCostBps);
}

function clampedSlippageBps() {
  return clampNumber(state.payload?.config?.slippage_bps, 0, 200, DASHBOARD_INPUT_DEFAULTS.slippageBps);
}

function clampNumber(value, minValue, maxValue, fallback) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(minValue, Math.min(maxValue, parsed));
}

function optionalNumber(value) {
  if (value === null || value === undefined) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function clampedTopN() {
  return Math.round(clampNumber(state.payload?.config?.top_n, 1, 50, DASHBOARD_INPUT_DEFAULTS.topN));
}

function storedScenarioRowLimit(run = currentRun(), factor = selectedFactor()) {
  const factorRows = (run?.factor_score_snapshots || [])
    .filter((snapshot) => !factor || snapshot?.factor === factor)
    .map((snapshot) => Array.isArray(snapshot?.rows) ? snapshot.rows.length : 0);
  const latestOutputCount = latestOutputMatchesFactor(run || {}, factor)
    ? (run?.latest_output_rows || []).length
    : 0;
  const observed = Math.max(0, ...factorRows, latestOutputCount);
  return Math.max(1, Math.min(50, observed || DASHBOARD_INPUT_DEFAULTS.topN));
}

function syncTopNAvailability(run = currentRun(), factor = selectedFactor()) {
  return storedScenarioRowLimit(run, factor);
}

function clampedMaxWeight() {
  return clampNumber(state.payload?.config?.max_weight, 0.01, 1, DASHBOARD_INPUT_DEFAULTS.maxWeightPercent / 100);
}

function inputScenarioParameters() {
  const transactionCostBps = clampedTransactionCostBps();
  const slippageBps = clampedSlippageBps();
  return {
    lookbackMonths: selectedLookbackMonths(),
    topN: clampedTopN(),
    maxWeight: clampedMaxWeight(),
    rebalanceFrequency: selectedRebalanceFrequency(),
    transactionCostBps,
    slippageBps,
    totalCostRate: (transactionCostBps + slippageBps) / 10000,
  };
}

function rebalanceFrequencyLabel(value) {
  const labels = { W: '주간', ME: '월간', QE: '분기' };
  return labels[value] || value || '-';
}

function factorOptions(run = currentRun()) {
  const options = run.factor_options || [];
  if (options.length) return options;
  const factors = [...new Set([
    run.summary?.selected_factor,
    ...(run.factor_leaders || []).map((row) => row.best_factor),
    ...(run.factor_period_rankings || []).map((row) => row.factor),
  ].filter(Boolean))].sort();
  return factors.map((factor) => ({ factor, category: 'unknown', description_ko: '팩터 설명 정보가 없습니다.' }));
}

function factorDescription(factor, run = currentRun()) {
  const option = factorOptions(run).find((item) => item.factor === factor);
  if (!option) return '팩터 설명 정보가 없습니다.';
  const category = humanFactorCategory(option.category);
  const description = option.description_ko || option.description || '설명 정보가 없습니다.';
  return `${category} · ${description}`;
}

function periodMatrixEntry(run, date, windowKey) {
  return (run.factor_period_matrix || []).find((row) => row.date === date && row.window === windowKey) || null;
}

function periodFactorStats(run, date, windowKey, factor) {
  const matrix = periodMatrixEntry(run, date, windowKey);
  if (matrix && Array.isArray(matrix.factors)) {
    const index = matrix.factors.indexOf(factor);
    if (index >= 0) {
      return {
        factor,
        rank: index + 1,
        period_return: optionalNumber(matrix.returns?.[index]),
        factor_count: matrix.factors.length,
        window_label: matrix.window_label || windowKey,
      };
    }
    return {
      factor,
      rank: null,
      period_return: null,
      factor_count: matrix.factors.length,
      window_label: matrix.window_label || windowKey,
    };
  }
  const row = (run.factor_period_rankings || []).find((item) => (
    item.date === date && item.window === windowKey && item.factor === factor
  ));
  if (!row) return null;
  return { ...row, rank: row.rank, factor_count: row.factor_count || null };
}

function periodFactorStatsIncludingDiagnostic(run, date, windowKey, factor) {
  const ranked = periodFactorStats(run, date, windowKey, factor);
  if (ranked && optionalNumber(ranked.period_return) !== null) return ranked;

  const series = factorBacktestSeries(run, factor);
  const endIndex = Array.isArray(series?.dates) ? series.dates.indexOf(date) : -1;
  const tradingDays = tradingDaysForWindow(run, windowKey);
  const startIndex = endIndex - tradingDays;
  const start = startIndex >= 0 ? strictPositiveNav(series?.equity?.[startIndex]) : null;
  const end = endIndex >= 0 ? strictPositiveNav(series?.equity?.[endIndex]) : null;
  const matrix = periodMatrixEntry(run, date, windowKey);
  const option = factorOptions(run).find((row) => row.factor === factor) || {};
  return {
    factor,
    rank: null,
    period_return: start !== null && end !== null ? end / start - 1 : null,
    factor_count: matrix?.factors?.length ?? ranked?.factor_count ?? null,
    window_label: matrix?.window_label || ranked?.window_label || windowKey,
    selection_eligible: option.selection_eligible === true,
    selection_status: option.selection_status || 'diagnostic_only',
    diagnostic_fallback: true,
  };
}

function periodBestStats(run, date, windowKey) {
  const matrix = periodMatrixEntry(run, date, windowKey);
  if (matrix && Array.isArray(matrix.factors) && matrix.factors.length) {
    return {
      factor: matrix.factors[0],
      rank: 1,
      period_return: optionalNumber(matrix.returns?.[0]),
      factor_count: matrix.factors.length,
      window_label: matrix.window_label || windowKey,
    };
  }
  const leader = (run.factor_leaders || []).find((item) => item.date === date && item.window === windowKey);
  if (!leader) return null;
  return {
    factor: leader.best_factor,
    rank: 1,
    period_return: leader.best_return,
    factor_count: leader.factor_count,
    window_label: leader.window_label || windowKey,
  };
}

function factorScoreSnapshot(run, date, factor) {
  return (run.factor_score_snapshots || []).find((snapshot) => snapshot.date === date && snapshot.factor === factor) || null;
}

function factorWeightSnapshot(run, date, windowKey, factor) {
  return (run.factor_weight_snapshots || []).find((snapshot) => (
    snapshot.date === date && snapshot.window === windowKey && snapshot.factor === factor
  )) || null;
}

function normalizeSnapshotRows(snapshot) {
  const rows = snapshot?.rows || [];
  return rows
    .map((row) => {
      if (Array.isArray(row)) return { symbol: row[0], score: Number(row[1]) };
      return { symbol: row.symbol, score: Number(row.score) };
    })
    .filter((row) => row.symbol && Number.isFinite(row.score))
    .sort((a, b) => Number(b.score) - Number(a.score) || String(a.symbol).localeCompare(String(b.symbol)));
}

function normalizeWeightRows(snapshot) {
  const rows = snapshot?.rows || [];
  return rows
    .map((row) => {
      if (Array.isArray(row)) return { symbol: row[0], weight: Number(row[1]), score: Number(row[2]) };
      return { symbol: row.symbol, weight: Number(row.weight ?? row.default_weight), score: Number(row.score) };
    })
    .filter((row) => row.symbol && Number.isFinite(row.weight) && row.weight > 0)
    .sort((a, b) => Number(b.weight) - Number(a.weight) || String(a.symbol).localeCompare(String(b.symbol)));
}

function computeScenarioAllocation(rows, topN, maxWeight) {
  const safeRows = normalizeSnapshotRows({ rows });
  const count = Math.max(1, Math.min(50, Math.round(Number(topN) || 20), safeRows.length || 1));
  const cap = Math.max(0.01, Math.min(0.5, Number(maxWeight) || 0.1));
  const selected = safeRows.slice(0, count);
  const scores = selected.map((row) => Number(row.score) || 0);
  const minScore = scores.length ? Math.min(...scores) : 0;
  const maxScore = scores.length ? Math.max(...scores) : 0;
  const scoreRange = maxScore - minScore;
  const rawScores = scoreRange > 0
    ? scores.map((score) => score - minScore + Math.max(scoreRange * 1e-6, 1e-9))
    : selected.map((_, index) => selected.length - index);
  const weights = Array(selected.length).fill(0);
  const remainingIndexes = new Set(selected.map((_, index) => index));
  let remainingBudget = 1;
  while (remainingIndexes.size && remainingBudget > 1e-12) {
    const activeRawTotal = [...remainingIndexes].reduce((sum, index) => sum + rawScores[index], 0);
    if (activeRawTotal <= 0) break;
    const cappedThisRound = [];
    for (const index of remainingIndexes) {
      const candidateWeight = remainingBudget * (rawScores[index] / activeRawTotal);
      if (candidateWeight > cap) {
        weights[index] = cap;
        cappedThisRound.push(index);
      }
    }
    if (!cappedThisRound.length) {
      for (const index of remainingIndexes) {
        weights[index] = remainingBudget * (rawScores[index] / activeRawTotal);
      }
      remainingBudget = 0;
      break;
    }
    cappedThisRound.forEach((index) => {
      remainingIndexes.delete(index);
      remainingBudget -= weights[index];
    });
  }
  const weighted = selected.map((row, index) => ({
    ...row,
    display_rank: index + 1,
    display_weight: Math.max(0, weights[index] || 0),
    scenario_weight: Math.max(0, weights[index] || 0),
  }));
  const investedTotal = weighted.reduce((sum, row) => sum + row.display_weight, 0);
  return {
    weighted,
    investedTotal,
    displayedTotal: investedTotal,
    portfolioTotal: investedTotal,
    cashTotal: Math.max(0, 1 - investedTotal),
    unusedCandidateCount: Math.max(0, safeRows.length - weighted.length),
    weightingMethod: 'score_proportional_capped',
    topN: count,
    maxWeight: cap,
    availableCount: safeRows.length,
  };
}

function topFactorsForDate(run, date, windowKey, limit = 10) {
  const matrix = periodMatrixEntry(run, date, windowKey);
  if (matrix && Array.isArray(matrix.factors)) {
    return matrix.factors
      .map((factor, index) => ({
        factor,
        rank: index + 1,
        period_return: optionalNumber(matrix.returns?.[index]),
        window_label: matrix.window_label || windowKey,
        factor_count: matrix.factor_count || matrix.factors.length,
      }))
      .filter((row) => row.factor)
      .slice(0, limit);
  }
  return (run.factor_period_rankings || [])
    .filter((row) => row.date === date && row.window === windowKey)
    .sort((a, b) => Number(a.rank || 9999) - Number(b.rank || 9999))
    .slice(0, limit)
    .map((row, index) => ({
      factor: row.factor,
      rank: row.rank || index + 1,
      period_return: optionalNumber(row.period_return),
      window_label: row.window_label || windowKey,
      factor_count: row.factor_count || null,
    }))
    .filter((row) => row.factor);
}

function capAggregatedWeights(rows, maxWeight) {
  const cap = Math.max(0.01, Math.min(0.5, Number(maxWeight) || 0.1));
  const clean = rows
    .map((row) => ({ ...row, raw_ensemble_weight: Math.max(0, Number(row.raw_ensemble_weight) || 0) }))
    .filter((row) => row.symbol && row.raw_ensemble_weight > 0);
  const rawTotal = clean.reduce((sum, row) => sum + row.raw_ensemble_weight, 0);
  if (!clean.length || rawTotal <= 0) {
    return {
      rows: [],
      investedTotal: 0,
      cashTotal: 1,
      maxWeight: cap,
    };
  }
  const targetBudget = Math.min(1, rawTotal);
  const weights = clean.map((row) => row.raw_ensemble_weight * targetBudget / rawTotal);
  const active = new Set(clean.map((_, index) => index));
  let remainingBudget = targetBudget;
  while (active.size && remainingBudget > 1e-12) {
    const activeWeightTotal = [...active].reduce((sum, index) => sum + weights[index], 0);
    if (activeWeightTotal <= 0) break;
    const cappedThisRound = [];
    for (const index of active) {
      const candidateWeight = remainingBudget * (weights[index] / activeWeightTotal);
      if (candidateWeight > cap) {
        weights[index] = cap;
        cappedThisRound.push(index);
      }
    }
    if (!cappedThisRound.length) {
      for (const index of active) {
        weights[index] = remainingBudget * (weights[index] / activeWeightTotal);
      }
      remainingBudget = 0;
      break;
    }
    cappedThisRound.forEach((index) => {
      active.delete(index);
      remainingBudget -= weights[index];
    });
  }
  const cappedRows = clean.map((row, index) => ({
    ...row,
    display_weight: Math.max(0, weights[index] || 0),
    weight_cap: cap,
    weight_cap_excess: Math.max(0, (row.raw_ensemble_weight * targetBudget / rawTotal) - (weights[index] || 0)),
  }));
  const investedTotal = cappedRows.reduce((sum, row) => sum + row.display_weight, 0);
  return {
    rows: cappedRows,
    investedTotal,
    cashTotal: Math.max(0, 1 - investedTotal),
    maxWeight: cap,
  };
}

function topFactorEnsembleAllocation(run, date, windowKey, topN, maxWeight, factorLimit = 10) {
  const factorRows = topFactorsForDate(run, date, windowKey, factorLimit);
  const displayTopN = Math.max(1, Math.min(50, Math.round(Number(topN) || 20)));
  const sleeves = [];
  const missingFactors = [];
  factorRows.forEach((factorRow) => {
    const snapshot = factorWeightSnapshot(run, date, windowKey, factorRow.factor);
    const rows = normalizeWeightRows(snapshot);
    if (!rows.length) {
      missingFactors.push(factorRow.factor);
      return;
    }
    sleeves.push({ ...factorRow, snapshot, rows });
  });

  const bySymbol = new Map();
  const sleeveWeight = sleeves.length ? 1 / sleeves.length : 0;
  sleeves.forEach((sleeve) => {
    sleeve.rows.forEach((row) => {
      const key = String(row.symbol);
      const current = bySymbol.get(key) || {
        symbol: key,
        raw_ensemble_weight: 0,
        factor_count: 0,
        factors: [],
        score_sum: 0,
        best_score: Number.NEGATIVE_INFINITY,
        factor_weight_sum: 0,
      };
      const sleeveContribution = sleeveWeight * (Number(row.weight) || 0);
      current.raw_ensemble_weight += sleeveContribution;
      current.factor_weight_sum += Number(row.weight) || 0;
      current.factor_count += 1;
      current.factors.push(sleeve.factor);
      current.score_sum += Number(row.score) || 0;
      current.best_score = Math.max(current.best_score, Number(row.score) || Number.NEGATIVE_INFINITY);
      bySymbol.set(key, current);
    });
  });

  const capped = capAggregatedWeights([...bySymbol.values()], maxWeight);
  const allWeighted = capped.rows
    .sort((a, b) => (
      Number(b.display_weight) - Number(a.display_weight)
      || Number(b.factor_count) - Number(a.factor_count)
      || Number(b.score_sum) - Number(a.score_sum)
      || String(a.symbol).localeCompare(String(b.symbol))
    ));
  const weighted = allWeighted
    .slice(0, displayTopN)
    .map((row, index) => ({
      ...row,
      display_rank: index + 1,
      display_weight: Math.max(0, row.display_weight || 0),
      weighting_method: 'top_factor_equal_sleeve',
    }));

  return {
    weighted,
    topN: displayTopN,
    factorRows,
    sleeves,
    factorsUsedCount: sleeves.length,
    factorLimit,
    missingFactors,
    totalCandidateCount: bySymbol.size,
    hiddenWeight: allWeighted.slice(displayTopN).reduce((sum, row) => sum + (Number(row.display_weight) || 0), 0),
    investedTotal: capped.investedTotal,
    cashTotal: capped.cashTotal,
    maxWeight: capped.maxWeight,
    windowLabel: factorRows[0]?.window_label || (run.periods || []).find((period) => period.key === windowKey)?.label || windowKey || '-',
  };
}

function latestOutputFactor(run) {
  const rows = Array.isArray(run.latest_output_rows) ? run.latest_output_rows : [];
  if (!rows.length) return '';
  const rowFactors = [...new Set(rows.map((row) => row?.selected_factor).filter(Boolean))];
  if (rowFactors.length === 1) return rowFactors[0];
  if (rowFactors.length === 0) return run.summary?.selected_factor || '';
  return '';
}

function latestOutputMatchesFactor(run, factor) {
  const outputFactor = latestOutputFactor(run);
  return Boolean(outputFactor && factor && outputFactor === factor);
}

function latestOutputSignalRows(run, topN, factor = null) {
  if (factor && !latestOutputMatchesFactor(run, factor)) return [];
  const rows = Array.isArray(run.latest_output_rows) ? run.latest_output_rows : [];
  const count = Math.max(1, Math.min(50, Math.round(Number(topN) || 20), rows.length || 1));
  return rows.slice(0, count).map((row, index) => ({
    rank: row.rank || index + 1,
    symbol: row.symbol,
    score: optionalNumber(row.score),
    weight: optionalNumber(row.weight) || 0,
    pre_cap_weight: optionalNumber(row.pre_cap_weight ?? row.proposed_weight ?? row.weight) || 0,
    weighting_method: row.weighting_method || 'latest_output_rows',
    signal_date: row.signal_date || run.summary?.data_as_of || '-',
    selected_factor: row.selected_factor || run.summary?.selected_factor || '-',
  })).filter((row) => row.symbol);
}

function bestFactorSignalRows(run, date, windowKey, topN, maxWeight) {
  const best = periodBestStats(run, date, windowKey);
  const snapshot = best?.factor ? factorScoreSnapshot(run, date, best.factor) : null;
  const allocation = computeScenarioAllocation(snapshot?.rows || [], topN, maxWeight);
  const researchOnly = !isPracticalRun(run);
  const requestedTopN = Math.max(1, Math.min(50, Math.round(Number(topN) || 20)));
  let rows = allocation.weighted.map((row) => ({
    rank: row.display_rank,
    symbol: row.symbol,
    score: row.score,
    weight: researchOnly ? 0 : row.display_weight,
    pre_cap_weight: row.display_weight,
    weighting_method: 'best_factor_score_proportional_capped',
    signal_date: snapshot?.score_date || date,
    selected_factor: best?.factor || '-',
  }));
  let signalSource = 'best_factor_score_snapshot';
  if (!rows.length && Array.isArray(run.latest_output_rows) && run.latest_output_rows.length) {
    rows = latestOutputSignalRows(run, requestedTopN);
    signalSource = 'latest_output_rows_fallback';
  }
  return {
    rows,
    best,
    snapshot,
    allocation,
    researchOnly,
    signalSource,
    topN: signalSource === 'latest_output_rows_fallback' ? requestedTopN : allocation.topN,
    maxWeight: allocation.maxWeight,
    windowLabel: best?.window_label || (run.periods || []).find((period) => period.key === windowKey)?.label || windowKey || '-',
  };
}

function setText(selector, value) {
  const target = document.querySelector(selector);
  if (target) target.textContent = textValue(value);
}

function appendDefinition(target, label, value) {
  const dt = document.createElement('dt');
  dt.textContent = label;
  const dd = document.createElement('dd');
  dd.textContent = textValue(value);
  target.append(dt, dd);
}

function formatCounts(counts, labels = {}) {
  if (!counts || typeof counts !== 'object' || Array.isArray(counts)) return '-';
  const entries = Object.entries(counts).filter(([, value]) => Number(value) > 0);
  if (!entries.length) return '-';
  return entries
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .map(([key, value]) => `${labels[key] || key} ${formatInteger(value)}`)
    .join(' · ');
}

function humanSourceName(value) {
  const text = textValue(value);
  const labels = {
    'yfinance-adjusted-daily': 'yfinance 조정가격',
    'yahoo-chart-adjusted-daily-fallback': 'Yahoo chart 보강',
    'nasdaq-latest-close-repair': 'Nasdaq 최신일 보강',
    'stooq-daily-close-fallback': 'Stooq 대체',
    'finance-datareader-close-fallback': 'FinanceDataReader 대체',
    'yfinance-fast-info-market-cap': '시가총액 보강',
    'finviz-snapshot-market-cap': 'Finviz 시가총액 보강',
    'live-run-summary': '전체 실행 요약',
    'acquisition-run-diagnostics': '전체 수집 실행',
    'packaged-default-universe': '패키지 유니버스',
  };
  return labels[text] || text;
}

function formatCoverageMetric(ratio, numerator, denominator) {
  const ratioText = formatPercent(ratio);
  const num = Number(numerator);
  const den = Number(denominator);
  if (Number.isFinite(num) && Number.isFinite(den) && den > 0) {
    return `${ratioText} (${formatInteger(num)} / ${formatInteger(den)})`;
  }
  return ratioText;
}

function formatSourceHealth(rows, context = {}) {
  if (!Array.isArray(rows) || !rows.length) return '-';
  const validRows = rows.filter((row) => row && row.source);
  if (!validRows.length) return '-';

  const pieces = [];
  const requested = optionalNumber(context.requestedCandidateCount);
  const usable = optionalNumber(context.providerReturnedCandidateCount);
  const finalEligible = optionalNumber(context.latestEligibleSecurityCount);
  if (requested !== null && usable !== null) {
    const unavailable = Math.max(0, requested - usable);
    pieces.push(
      `전체 결과: 공급자 사용 가능 ${formatInteger(usable)} / 후보 ${formatInteger(requested)}`
      + `${finalEligible !== null ? ` · 최종 편입 적격 ${formatInteger(finalEligible)}` : ''}`
      + ` · 미반환/사용 불가 ${formatInteger(unavailable)}`,
    );
  }

  const bySource = new Map();
  validRows.forEach((row) => {
    if (!bySource.has(row.source)) {
      bySource.set(row.source, {
        statuses: new Map(),
        successRows: 0,
        noNewerRows: 0,
        failedRows: 0,
        rowCount: 0,
      });
    }
    const aggregate = bySource.get(row.source);
    const status = row.status || '';
    if (status) aggregate.statuses.set(status, (aggregate.statuses.get(status) || 0) + 1);
    aggregate.successRows += Math.max(0, Number(row.success_rows) || 0);
    aggregate.noNewerRows += Math.max(0, Number(row.no_newer_rows) || 0);
    aggregate.failedRows += Math.max(0, Number(row.failed_rows) || 0);
    aggregate.rowCount += Math.max(0, Number(row.row_count) || 0);
  });

  const statusLabels = {
    fetched: '수집 성공',
    loaded: '로드',
    full_requested_universe: '전체 후보 요청',
    no_newer_rows: '새 행 없음',
    failed: '실패',
  };
  const statusOrder = ['fetched', 'loaded', 'full_requested_universe', 'no_newer_rows', 'failed'];
  let recordedFailures = 0;
  bySource.forEach((aggregate, source) => {
    const parts = [];
    statusOrder.forEach((status) => {
      const count = aggregate.statuses.get(status) || 0;
      if (count > 0) parts.push(`${statusLabels[status]} ${formatInteger(count)}건`);
      if (status === 'failed') recordedFailures += count;
    });
    [...aggregate.statuses.entries()]
      .filter(([status]) => !statusOrder.includes(status))
      .sort(([left], [right]) => left.localeCompare(right))
      .forEach(([status, count]) => parts.push(`${status} ${formatInteger(count)}건`));
    if (!aggregate.statuses.has('fetched') && aggregate.successRows > 0) {
      parts.push(`성공 ${formatInteger(aggregate.successRows)}`);
    }
    if (!aggregate.statuses.has('no_newer_rows') && aggregate.noNewerRows > 0) {
      parts.push(`추가 없음 ${formatInteger(aggregate.noNewerRows)}`);
    }
    if (!aggregate.statuses.has('failed') && aggregate.failedRows > 0) {
      parts.push(`실패 ${formatInteger(aggregate.failedRows)}`);
      recordedFailures += aggregate.failedRows;
    }
    if (!parts.length) parts.push(`기록 ${formatInteger(aggregate.rowCount)}`);
    pieces.push(`${humanSourceName(source)}: ${parts.join(', ')}`);
  });
  if (recordedFailures > 0) {
    pieces.push('실패 건수는 단계별 원천·보강 시도 기록이며, 최종 사용 가능 여부는 앞의 전체 결과를 기준으로 판단합니다.');
  }
  return pieces.join(' · ');
}

function setStatusMessage(message) {
  const statusCard = document.querySelector('#run-status');
  statusCard.replaceChildren();
  statusCard.textContent = message;
  statusCard.setAttribute('aria-busy', 'true');
  statusCard.classList.add('is-updating');
}

function appendStatusLine(target, label, value) {
  const row = document.createElement('div');
  row.className = 'status-line';
  const labelNode = document.createElement('span');
  labelNode.className = 'status-label';
  labelNode.textContent = label;
  const valueNode = document.createElement('span');
  valueNode.className = 'status-value';
  valueNode.textContent = textValue(value);
  row.append(labelNode, valueNode);
  target.appendChild(row);
  return row;
}

function appendFactorHoldingHistoryLoadStatus(target, payload) {
  const error = payload?.__factorHoldingHistorySidecarError;
  if (!error) return;
  appendStatusLine(
    target,
    '팩터별 보유 이력',
    `검증 실패 · 추가 팩터 이력을 표시하지 않음 (${error})`,
  );
}

function appendHeader(tr, value) {
  const th = document.createElement('th');
  th.setAttribute('scope', 'col');
  th.textContent = textValue(value);
  tr.appendChild(th);
}

function appendRowHeader(tr, value) {
  const th = document.createElement('th');
  th.setAttribute('scope', 'row');
  const strong = document.createElement('strong');
  strong.textContent = textValue(value);
  th.appendChild(strong);
  tr.appendChild(th);
}

function appendCell(tr, value, options = {}) {
  const td = document.createElement('td');
  if (options.className) td.className = options.className;
  if (options.badge) {
    const span = document.createElement('span');
    span.className = 'badge';
    span.textContent = textValue(value);
    td.appendChild(span);
  } else if (options.strong) {
    const strong = document.createElement('strong');
    strong.textContent = textValue(value);
    td.appendChild(strong);
  } else {
    td.textContent = textValue(value);
  }
  tr.appendChild(td);
}

function appendEmpty(selector, message) {
  const target = document.querySelector(selector);
  if (!target) return;
  target.replaceChildren();
  const empty = document.createElement('div');
  empty.className = 'empty-state';
  empty.textContent = message;
  target.appendChild(empty);
}

function barWidth(value, maxAbs) {
  if (!Number.isFinite(Number(value)) || maxAbs <= 0) return '0%';
  return `${Math.max(3, Math.min(100, Math.abs(Number(value)) / maxAbs * 100)).toFixed(1)}%`;
}

function factorComparisonBarClass({ selected = false, best = false } = {}) {
  if (selected) return CHART_PALETTE_CLASS_MAP.bars.focal;
  if (best) return CHART_PALETTE_CLASS_MAP.bars.best;
  return CHART_PALETTE_CLASS_MAP.bars.context;
}

function benchmarkPaletteClass(symbol) {
  return CHART_PALETTE_CLASS_MAP.benchmarks[symbol]
    || CHART_PALETTE_CLASS_MAP.benchmarks.default;
}

function scenarioAllocationForFactor(run, date, windowKey, factor, topN, maxWeight) {
  const snapshot = factorScoreSnapshot(run, date, factor);
  let allocation = computeScenarioAllocation(snapshot?.rows || [], topN, maxWeight);
  let fallbackSource = null;
  if (!allocation.weighted.length) {
    const weightSnapshot = factorWeightSnapshot(run, date, windowKey, factor);
    const weightRows = normalizeWeightRows(weightSnapshot).map((row) => ({
      symbol: row.symbol,
      score: Number.isFinite(Number(row.score)) ? Number(row.score) : Number(row.weight) || 0,
    }));
    allocation = computeScenarioAllocation(weightRows, topN, maxWeight);
    if (allocation.weighted.length) fallbackSource = 'factor_weight_snapshot_fallback';
  }
  if (!allocation.weighted.length) {
    const holdingRows = (run.holdings || [])
      .filter((row) => row.date === date && row.window === windowKey && row.factor === factor)
      .map((row) => ({
        symbol: row.symbol,
        score: Number.isFinite(Number(row.score)) ? Number(row.score) : Number(row.default_weight) || 0,
      }));
    allocation = computeScenarioAllocation(holdingRows, topN, maxWeight);
    if (allocation.weighted.length) fallbackSource = 'holding_rows_fallback';
  }
  const latestOutputRowsFactor = latestOutputFactor(run);
  if (
    !allocation.weighted.length
    && Array.isArray(run.latest_output_rows)
    && run.latest_output_rows.length
    && latestOutputMatchesFactor(run, factor)
  ) {
    const fallbackRows = latestOutputSignalRows(run, topN, factor).map((row, index) => {
      const displayWeight = Math.max(0, Math.min(maxWeight, optionalNumber(row.pre_cap_weight) || optionalNumber(row.weight) || 0));
      return {
        ...row,
        display_rank: row.rank || index + 1,
        display_weight: displayWeight,
        scenario_weight: displayWeight,
      };
    });
    const investedTotal = fallbackRows.reduce((sum, row) => sum + (Number(row.display_weight) || 0), 0);
    allocation = {
      weighted: fallbackRows,
      investedTotal,
      displayedTotal: investedTotal,
      portfolioTotal: investedTotal,
      cashTotal: Math.max(0, 1 - investedTotal),
      unusedCandidateCount: Math.max(0, (run.latest_output_rows || []).length - fallbackRows.length),
      weightingMethod: 'latest_output_rows_fallback',
      topN: Math.max(1, Math.min(50, Math.round(Number(topN) || DASHBOARD_INPUT_DEFAULTS.topN))),
      maxWeight,
      availableCount: fallbackRows.length,
    };
    fallbackSource = 'latest_output_rows_fallback';
  }
  return { allocation, snapshot, fallbackSource, latestOutputRowsFactor };
}

function portfolioHoldingsFromPayload(payload, factor) {
  const target = payload.factorPortfolios?.[factor]
    || (factor === payload.bestFactor ? payload.bestFactorPortfolio : null)
    || {};
  const rows = Array.isArray(target.weights) ? target.weights : [];
  const weighted = rows.map((row, index) => ({
    ...row,
    display_rank: row.rank || index + 1,
    score: optionalNumber(row.factorScore),
    display_weight: Math.max(0, Number(row.weight) || 0),
  }));
  const investedTotal = weighted.reduce((sum, row) => sum + row.display_weight, 0);
  const cashTotal = Math.max(0, optionalNumber(target.cashWeight) ?? (1 - investedTotal));
  return {
    weighted,
    investedTotal,
    displayedTotal: investedTotal,
    portfolioTotal: investedTotal,
    cashTotal,
    topN: Number(payload.config?.top_n) || weighted.length,
    maxWeight: Number(payload.config?.max_weight) || 0,
    availableCount: Number(target.eligibleSecurityCount) || weighted.length,
    selectedFactor: factor || target.factor || '-',
    weightingPolicyId: payload.weightingPolicy || target.weightingPolicyId || '-',
    scoreDate: target.signalDate || target.asOf || payload.data?.asOf || null,
    missingReason: target.status === 'available' && weighted.length
      ? null
      : (target.reasons || []).join(', ') || 'Python 선택 포트폴리오를 사용할 수 없습니다.',
  };
}

function weightedHoldingsForFactor(factor) {
  return portfolioHoldingsFromPayload(state.payload || {}, factor);
}

function currentWeightedHoldings() {
  const payload = state.payload || {};
  return weightedHoldingsForFactor(selectedFactor() || payload.bestFactor);
}

function bestWeightedHoldings() {
  const payload = state.payload || {};
  return weightedHoldingsForFactor(payload.bestFactor || payload.bestFactorPortfolio?.factor);
}

function appendBarRow(target, label, valueLabel, value, maxAbs, options = {}) {
  const row = document.createElement('div');
  row.className = `bar-row ${options.className || ''}`.trim();

  const labelNode = document.createElement('div');
  labelNode.className = 'bar-label';
  labelNode.textContent = textValue(label);

  const track = document.createElement('div');
  track.className = 'bar-track';
  const fill = document.createElement('div');
  fill.className = `bar-fill ${Number(value) < 0 ? 'negative' : ''}`;
  fill.style.setProperty('--bar-width', barWidth(value, maxAbs));
  track.appendChild(fill);

  const valueNode = document.createElement('div');
  valueNode.className = `bar-value ${classForNumber(value)}`;
  valueNode.textContent = valueLabel;

  row.append(labelNode, track, valueNode);
  target.appendChild(row);
}

function factorAvailableDates(run, factor) {
  const dates = (run.factor_holding_histories?.[factor]?.sessions || [])
    .map((session) => session?.date)
    .filter(Boolean);
  if (run.summary?.data_as_of) dates.push(run.summary.data_as_of);
  return new Set(dates);
}

function fillDateOptions(run, preferredDate = null, factor = selectedFactor()) {
  const dates = uniqueDates(run);
  const availableDates = factorAvailableDates(run, factor);
  const dateSelect = document.querySelector('#date-select');
  dateSelect.replaceChildren();
  dates.forEach((date) => {
    const option = document.createElement('option');
    option.value = date;
    option.textContent = availableDates.has(date) ? `${date} · 종목/비중 가능` : `${date} · 팩터 수익률만`;
    dateSelect.appendChild(option);
  });
  if (dates.length) {
    dateSelect.value = preferredDate && dates.includes(preferredDate) ? preferredDate : dates[0];
  }
}

function syncFactorDependentControls(run, factor, preferredDate = null) {
  fillDateOptions(run, preferredDate, factor);
  syncTopNAvailability(run, factor);
}

function factorOptionLabel(item, bestDefaultFactor, run) {
  if (item.factor === run.summary?.selected_factor) return `${item.factor} · 동일 입력 Python 최고`;
  if (item.selection_eligible === false) {
    const reason = item.selection_status === 'extreme_event_excluded' ? '극단사건 제외' : '선정 제외';
    return `${item.factor} · ${reason} · 진단용`;
  }
  return `${item.factor} · ${humanFactorCategory(item.category)}`;
}

function updateFactorOptionLabels(run, bestDefaultFactor) {
  const factorSelect = document.querySelector('#factor-select');
  if (!factorSelect) return;
  const metadata = new Map(factorOptions(run).map((item) => [item.factor, item]));
  Array.from(factorSelect.children || []).forEach((option) => {
    const item = metadata.get(option.value) || { factor: option.value, category: 'unknown' };
    option.textContent = factorOptionLabel(item, bestDefaultFactor, run);
  });
}

function defaultFactorForRun(run, factors, previousFactor = '', bestDefaultFactor = null) {
  if (previousFactor && factors.includes(previousFactor)) return previousFactor;
  if (factors.includes(run.summary?.selected_factor)) return run.summary.selected_factor;
  if (bestDefaultFactor && factors.includes(bestDefaultFactor)) return bestDefaultFactor;
  return factors[0] || '';
}

function syncDefaultFactorToCurrentBasis() {
  const run = currentRun();
  const factorSelect = document.querySelector('#factor-select');
  if (!run || !factorSelect) return;
  const bestDefaultFactor = run.summary?.selected_factor;
  updateFactorOptionLabels(run, bestDefaultFactor);
  // Date/window browsing never replaces the factor the user is inspecting.
  fillDateOptions(run, selectedDate(), factorSelect.value);
}

function fillControls() {
  const runSelect = document.querySelector('#run-select');
  const runs = state.data.runs || [];
  if (state.manifest) {
    runSelect.value = state.baseEntry?.resultKey || state.entry?.resultKey || state.manifest.defaultResultKey;
    runSelect.disabled = state.manifest.entries.length <= 1;
  } else {
    runSelect.replaceChildren();
    runs.forEach((run, index) => {
      const option = document.createElement('option');
      option.value = String(index);
      const prefix = runs.length <= 1 ? '최신 실행만 표시' : `실행 ${index + 1}`;
      option.textContent = `${prefix} · 기준일 ${run.summary?.data_as_of || '알 수 없음'} · 실행 ${formatKoreanDateTime(run.summary?.run_timestamp_utc)} · ${run.summary?.selected_factor || '-'}`;
      runSelect.appendChild(option);
    });
    runSelect.value = String(state.activeRunIndex);
    runSelect.disabled = runs.length <= 1;
  }

  const run = currentRun();
  const windowSelect = document.querySelector('#window-select');
  if (windowSelect) windowSelect.value = 'FULL';

  const previousDate = document.querySelector('#date-select')?.value || null;
  fillDateOptions(run, previousDate);
  const dateForDefault = selectedDate();

  const factorSelect = document.querySelector('#factor-select');
  const previousFactor = state.hasUserSelectedFactor ? factorSelect?.value || '' : '';
  factorSelect.replaceChildren();
  const options = factorOptions(run);
  const bestDefaultFactor = run.summary?.selected_factor;
  options.forEach((item) => {
    const option = document.createElement('option');
    option.value = item.factor;
    option.textContent = factorOptionLabel(item, bestDefaultFactor, run);
    factorSelect.appendChild(option);
  });
  const factors = options.map((item) => item.factor);
  factorSelect.value = defaultFactorForRun(run, factors, previousFactor, bestDefaultFactor);

  fillDateOptions(run, selectedDate());
}

function renderSummary() {
  const run = currentRun();
  const date = selectedDate();
  const windowKey = selectedWindow();
  const payload = state.payload || {};
  const officialFactor = payload.bestFactor || run.summary?.selected_factor;
  const selectedRow = bestFactorRow(payload);
  const comparisonFactor = selectedFactor();
  const comparisonFull = fullPythonPeriod()?.factors?.[comparisonFactor];
  const summary = run.summary || {};
  const latestRunAt = formatKoreanDateTime(summary.run_timestamp_utc);
  const runPayloadGeneratedAtText = formatKoreanDateTime(runPayloadGeneratedAt(run));
  setText('#best-factor', officialFactor || '-');
  setText(
    '#best-factor-detail',
    `합성 점수 ${formatNumber(selectedRow?.selection_score)} / 100`,
  );
  setText('#selected-factor', comparisonFactor || '-');
  setText(
    '#selected-factor-detail',
    `전체 평가기간 누적 ${formatPercent(pythonPerformanceMetric(comparisonFull, 'cumulativeReturn'))}`,
  );
  const automationView = automationStatusView({
    automation: state.automation, payload, manifest: state.manifest,
    source: state.resultSource, summary,
  });
  setText('#recommendation-status', automationView.title);
  const dataStatus = document.querySelector('#recommendation-status');
  if (dataStatus) dataStatus.dataset.tone = automationView.tone;
  const providerSummary = payload.data?.mode === 'live_market' && payload.data?.synthetic === false
    ? '실제시장 공개 데이터'
    : humanProvider(summary.provider);
  setText('#data-provider', `${automationView.detail} · ${providerSummary}`);
  setText('#latest-run-at', latestRunAt);
  setText('#latest-run-detail', `분석 실행 기준 · 실행 결과 생성 ${runPayloadGeneratedAtText}`);
  const portfolio = currentWeightedHoldings();
  setText('#weight-summary', `${formatInteger(portfolio.weighted.length)}종목 · 투자 ${formatPercent(portfolio.investedTotal)} · 현금 ${formatPercent(portfolio.cashTotal)}`);

  const statusCard = document.querySelector('#run-status');
  statusCard.replaceChildren();
  statusCard.removeAttribute('aria-busy');
  statusCard.classList.remove('is-updating');
  appendStatusLine(statusCard, '자동화', automationView.automationTitle);
  if (automationView.attemptedAtUtc) {
    appendStatusLine(statusCard, '최근 시도', formatKoreanDateTime(automationView.attemptedAtUtc));
  }
  if (automationView.automationTone !== 'ok' || automationView.historical
    || ['local_api', 'remote_api'].includes(state.resultSource)) {
    const automationDetail = appendStatusLine(statusCard, '갱신 점검', automationView.automationDetail);
    automationDetail.classList.add('status-line-automation-detail');
  }
  appendStatusLine(statusCard, '공개 상태', resultSourceLabel(state.resultSource));
  appendStatusLine(statusCard, '데이터 기준일', summary.data_as_of || '-');
  appendStatusLine(statusCard, '평가 종료일', run.common_evaluation_period?.endDate || summary.data_as_of || '-');
  appendStatusLine(statusCard, '신호 상태', humanOutputLabel(summary.recommendation_output_label));
  appendFactorHoldingHistoryLoadStatus(statusCard, state.payload);

  setText('#generated-at', `사이트 빌드 시각: ${formatKoreanDateTime(state.data.generated_at_utc)}`);
}

function appendDiagnosticBar(target, {
  label,
  detail,
  value,
  valueLabel,
  maxAbs = 1,
  selected = false,
  threshold = null,
  diverging = false,
}) {
  const row = document.createElement('div');
  row.className = `diagnostic-bar-row${selected ? ' is-selected' : ''}`;
  const labelNode = document.createElement('div');
  labelNode.className = 'diagnostic-bar-label';
  const strong = document.createElement('strong');
  strong.textContent = label;
  const small = document.createElement('small');
  small.textContent = detail;
  labelNode.append(strong, small);

  const track = document.createElement('div');
  track.className = `diagnostic-bar-track${diverging ? ' diverging' : ''}`;
  if (diverging) {
    const zero = document.createElement('span');
    zero.className = 'diagnostic-zero-line';
    track.appendChild(zero);
  }
  if (Number.isFinite(Number(threshold))) {
    const thresholdLine = document.createElement('span');
    thresholdLine.className = 'diagnostic-threshold-line';
    thresholdLine.style.setProperty('--threshold-position', `${Math.max(0, Math.min(100, Number(threshold) * 100))}%`);
    thresholdLine.title = `고중복 기준 |ρ| ${formatNumber(threshold)}`;
    track.appendChild(thresholdLine);
  }
  const fill = document.createElement('span');
  fill.className = `diagnostic-bar-fill${Number(value) < 0 ? ' negative' : ''}`;
  const ratio = Math.max(0, Math.min(1, Math.abs(Number(value) || 0) / Math.max(Math.abs(maxAbs), 1e-12)));
  if (diverging) {
    fill.style.setProperty('--diagnostic-width', `${ratio * 50}%`);
    fill.style.setProperty('--diagnostic-left', Number(value) < 0 ? `${50 - ratio * 50}%` : '50%');
  } else {
    fill.style.setProperty('--diagnostic-width', `${ratio * 100}%`);
    fill.style.setProperty('--diagnostic-left', '0%');
  }
  track.appendChild(fill);
  const valueNode = document.createElement('strong');
  valueNode.className = 'diagnostic-bar-value';
  valueNode.textContent = valueLabel;
  row.append(labelNode, track, valueNode);
  target.appendChild(row);
}

function appendDiagnosticTable(target, {
  label,
  headers,
  rows,
  selectedFactor: selected,
  rowHeaderIndex = 1,
}) {
  const wrap = document.createElement('div');
  wrap.className = 'diagnostic-table-wrap';
  wrap.setAttribute('role', 'region');
  wrap.setAttribute('tabindex', '0');
  wrap.setAttribute('aria-label', label);
  const table = document.createElement('table');
  table.className = 'diagnostic-table';
  const thead = document.createElement('thead');
  const header = document.createElement('tr');
  headers.forEach((text) => appendHeaderCell(header, text));
  thead.appendChild(header);
  const tbody = document.createElement('tbody');
  rows.forEach((row) => {
    const tr = document.createElement('tr');
    if (row.factor === selected) tr.className = 'is-selected';
    row.cells.forEach((cell, index) => {
      if (index === rowHeaderIndex) appendRowHeader(tr, cell.text);
      else appendCell(tr, cell.text, cell.options || {});
    });
    tbody.appendChild(tr);
  });
  table.append(thead, tbody);
  wrap.appendChild(table);
  target.appendChild(wrap);
}

function renderRankIcEvidence(target, diagnostics) {
  const rows = diagnostics.rank_ic_rows || diagnostics.rank_ic_top || [];
  if (!rows.length) {
    appendEmpty('#factor-rank-ic-summary', 'Forward Rank-IC 진단이 없습니다.');
    return;
  }
  const selected = selectedFactor();
  const selectedAlias = (diagnostics.aliases || []).find((row) => row.factor === selected);
  const diagnosticSelected = selectedAlias?.bestFactorName || selected;
  const availableRows = rows.filter((row) => (
    row.available === true && Number.isFinite(Number(row.mean_rank_ic))
  ));
  const top = availableRows.slice().sort((left, right) => Number(right.mean_rank_ic) - Number(left.mean_rank_ic)).slice(0, 8);
  const selectedRow = rows.find((row) => row.factor === diagnosticSelected);
  if (selectedRow?.available === true && !top.some((row) => row.factor === diagnosticSelected)) top.push(selectedRow);
  const observationCounts = availableRows.map((row) => Number(row.observations)).filter(Number.isFinite);
  const minimumObservations = observationCounts.length ? Math.min(...observationCounts) : null;
  const maximumObservations = observationCounts.length ? Math.max(...observationCounts) : null;
  const observationLabel = minimumObservations === maximumObservations
    ? formatInteger(minimumObservations)
    : `${formatInteger(minimumObservations)}–${formatInteger(maximumObservations)}`;
  const meta = document.createElement('p');
  meta.className = 'diagnostic-contract-note';
  meta.textContent = `${formatInteger(diagnostics.rank_ic_horizon_days)}세션 Forward · 최대 ${formatInteger(diagnostics.rank_ic_requested_sessions)}개 신호일 · 팩터별 실제 ${observationLabel}개 중첩 일별 IC · 독립 표본 검정이 아닌 동일표본 탐색 진단${selectedAlias ? ` · 선택 alias ${selected}는 ${diagnosticSelected}와 중복되어 canonical 행을 강조` : ''}`;
  target.appendChild(meta);
  const chart = document.createElement('div');
  chart.className = 'diagnostic-ranked-chart';
  const maxAbs = Math.max(...top.map((row) => Math.abs(Number(row.mean_rank_ic) || 0)), 0.01);
  top.forEach((row) => appendDiagnosticBar(chart, {
    label: row.factor,
    detail: `${humanFactorCategory(row.category)} · 양수 ${formatPercent(row.positive_ic_rate)}`,
    value: row.mean_rank_ic,
    valueLabel: formatNumber(row.mean_rank_ic),
    maxAbs,
    selected: row.factor === diagnosticSelected,
    diverging: true,
  }));
  target.appendChild(chart);
  appendDiagnosticTable(target, {
    label: '독립 팩터 61개 Forward Rank-IC 전체 표',
    headers: ['순위', '팩터', '카테고리', '평균 IC', '중앙값', '표준편차', '양수 비율', '관측', '평균 N', '기간'],
    selectedFactor: diagnosticSelected,
    rows: rows.map((row, index) => ({
      factor: row.factor,
      cells: [
        { text: row.rank || index + 1 },
        { text: row.factor },
        { text: humanFactorCategory(row.category) },
        { text: formatNumber(row.mean_rank_ic), options: { className: classForNumber(row.mean_rank_ic) } },
        { text: formatNumber(row.median_rank_ic), options: { className: classForNumber(row.median_rank_ic) } },
        { text: formatNumber(row.standard_deviation) },
        { text: formatPercent(row.positive_ic_rate) },
        { text: formatInteger(row.observations) },
        { text: formatInteger(row.average_security_count) },
        { text: `${row.start_date || '-'} → ${row.end_date || '-'}` },
      ],
    })),
  });
}

function renderRedundancyEvidence(target, diagnostics) {
  const rows = diagnostics.redundancy_rows || diagnostics.redundancy_top || [];
  const pairs = diagnostics.redundancy_pairs || [];
  if (!rows.length) {
    appendEmpty('#factor-redundancy-summary', '팩터 중복도 진단이 없습니다.');
    return;
  }
  const selected = selectedFactor();
  const selectedAlias = (diagnostics.aliases || []).find((row) => row.factor === selected);
  const diagnosticSelected = selectedAlias?.bestFactorName || selected;
  const threshold = Number(diagnostics.redundancy_threshold_abs) || 0.95;
  const top = pairs.slice(0, 8).map((row) => ({
    ...row,
    factor: row.left_factor,
    nearest_factor: row.right_factor,
  }));
  const selectedRow = rows.find((row) => row.factor === diagnosticSelected);
  if (selectedRow?.available === true && !top.some((row) => row.factor === diagnosticSelected || row.nearest_factor === diagnosticSelected)) top.push(selectedRow);
  const highPairCount = Number(diagnostics.redundancy_high_pair_count);
  const meta = document.createElement('p');
  meta.className = 'diagnostic-contract-note';
  meta.textContent = `${diagnostics.redundancy_date || rows[0]?.diagnostic_date || '-'} 최신 공통 신호일 횡단면 Spearman · 독립 팩터 고유쌍 ${formatInteger(diagnostics.redundancy_pair_count)}개 · |ρ| ≥ ${formatNumber(threshold)} 고중복 ${formatInteger(highPairCount)}쌍 · alias 제외${selectedAlias ? ` · 선택 alias ${selected}는 ${diagnosticSelected} canonical 행으로 표시` : ''}`;
  target.appendChild(meta);
  const chart = document.createElement('div');
  chart.className = 'diagnostic-ranked-chart';
  top.forEach((row) => appendDiagnosticBar(chart, {
    label: `${row.factor || row.left_factor} ↔ ${row.nearest_factor || row.right_factor}`,
    detail: `공통 ${formatInteger(row.common_security_count)}종목 · signed ${formatNumber(row.signed_rank_corr)}`,
    value: row.abs_rank_corr,
    valueLabel: formatNumber(row.abs_rank_corr),
    maxAbs: 1,
    threshold,
    selected: row.factor === diagnosticSelected || row.nearest_factor === diagnosticSelected,
  }));
  target.appendChild(chart);
  appendDiagnosticTable(target, {
    label: '독립 팩터 61개 최신 중복도 전체 표',
    headers: ['순위', '팩터', '가장 가까운 팩터', 'signed ρ', '|ρ|', '고중복 피어', '공통 N', '진단일'],
    selectedFactor: diagnosticSelected,
    rows: rows.map((row, index) => ({
      factor: row.factor,
      cells: [
        { text: row.rank || index + 1 },
        { text: row.factor },
        { text: row.nearest_factor || '-' },
        { text: formatNumber(row.signed_rank_corr), options: { className: classForNumber(row.signed_rank_corr) } },
        { text: formatNumber(row.abs_rank_corr) },
        { text: formatInteger(row.high_corr_peer_count) },
        { text: formatInteger(row.common_security_count) },
        { text: row.diagnostic_date || diagnostics.redundancy_date || '-' },
      ],
    })),
  });
}

function renderDiagnostics() {
  const run = currentRun();
  const summary = run.summary || {};
  const quality = run.data_quality_summary || {};
  const dataSummary = document.querySelector('#data-quality-summary');
  dataSummary.replaceChildren();
  appendDefinition(dataSummary, '후보 종목', formatCount(summary.candidate_universe_size ?? quality.candidate_universe_size));
  appendDefinition(dataSummary, '가격 분석 가능 종목', formatCount(summary.eligible_price_universe_size ?? quality.eligible_price_universe_size));
  appendDefinition(dataSummary, '최종 편입 적격 종목', formatCount(summary.liquidity_eligible_universe_size ?? quality.liquidity_eligible_universe_size));
  appendDefinition(dataSummary, '모형 가격 보유 종목', formatCount(quality.fetched_price_symbol_count));
  appendDefinition(dataSummary, '제외 종목 수', formatCount(quality.excluded_symbols));
  if (quality.latest_eligibility_exclusion_counts) {
    const overlapNote = quality.exclusion_counts_may_overlap
      ? ' · 규칙 간 중복 집계이므로 합계는 제외 종목 수와 일치하지 않을 수 있음'
      : '';
    appendDefinition(
      dataSummary,
      '최종 적격 제외 사유',
      `${formatCounts(quality.latest_eligibility_exclusion_counts, {
        insufficient_history: '이력 부족',
        liquidity_requirement: '유동성 기준',
        missing_or_below_min_price: '가격 누락/최저가 미달',
        recent_extreme_return: '최근 극단 수익률',
        recent_price_coverage: '최근 가격 커버리지',
        recent_volume_coverage: '최근 거래량 커버리지',
      })}${overlapNote}`,
    );
  }
  appendDefinition(
    dataSummary,
    '요청 가격 커버리지',
    formatCoverageMetric(
      quality.price_coverage_ratio,
      quality.provider_returned_symbol_count,
      quality.provider_requested_symbol_count,
    ),
  );
  appendDefinition(
    dataSummary,
    '모형 가격 보유 비율',
    formatCoverageMetric(
      quality.model_price_universe_ratio,
      quality.fetched_price_symbol_count,
      summary.candidate_universe_size ?? quality.candidate_universe_size,
    ),
  );
  appendDefinition(
    dataSummary,
    '가격 분석 가능 비율',
    formatCoverageMetric(
      quality.eligible_price_ratio,
      summary.eligible_price_universe_size ?? quality.eligible_price_universe_size,
      summary.candidate_universe_size ?? quality.candidate_universe_size,
    ),
  );
  appendDefinition(
    dataSummary,
    '최종 편입 적격 비율',
    formatCoverageMetric(
      quality.liquidity_eligible_ratio,
      summary.liquidity_eligible_universe_size ?? quality.liquidity_eligible_universe_size,
      summary.candidate_universe_size ?? quality.candidate_universe_size,
    ),
  );
  appendDefinition(
    dataSummary,
    '신선 가격 비율 (분석 가능 후보)',
    formatCoverageMetric(quality.fresh_price_ratio, quality.fresh_price_rows, quality.price_quality_rows),
  );
  appendDefinition(dataSummary, '데이터 기준일', quality.data_as_of || summary.data_as_of || '-');
  appendDefinition(dataSummary, '최근 실행 시각', formatKoreanDateTime(summary.run_timestamp_utc));
  appendDefinition(dataSummary, '실행 결과 생성 시각', formatKoreanDateTime(runPayloadGeneratedAt(run)));
  appendDefinition(dataSummary, '가격 제공자', humanProvider(quality.provider || summary.provider));
  appendDefinition(dataSummary, '소스별 수집 상태', formatSourceHealth(quality.source_health, {
    requestedCandidateCount: summary.candidate_universe_size ?? quality.candidate_universe_size,
    providerReturnedCandidateCount: quality.provider_returned_symbol_count,
    latestEligibleSecurityCount: summary.liquidity_eligible_universe_size ?? quality.liquidity_eligible_universe_size,
  }));
  appendDefinition(
    dataSummary,
    '가격 소스 분포',
    formatCounts(quality.price_source_counts, {
      'yfinance-adjusted-daily': 'yfinance',
      'yahoo-chart-adjusted-daily-fallback': 'Yahoo chart',
      'nasdaq-latest-close-repair': 'Nasdaq 보강',
      'stooq-daily-close-fallback': 'Stooq',
      'finance-datareader-close-fallback': 'FinanceDataReader',
    }),
  );
  appendDefinition(
    dataSummary,
    '품질 상태',
    formatCounts(quality.data_quality_status_counts, {
      pass: '통과',
      missing_price: '가격 누락',
      missing_volume: '거래량 누락',
      provider_adjustment_incompatible: '조정가격 불일치',
      stale_price: '오래된 가격',
      insufficient_history: '이력 부족',
      below_liquidity_floor: '유동성 부족',
      excluded: '분석 가능 중 최종 제외',
      benchmark_comparator_only: '벤치마크 전용',
    }),
  );
  appendDefinition(
    dataSummary,
    '최종 편입 적격 상태',
    formatCounts(quality.final_eligibility_status_counts || quality.liquidity_status_counts, { pass: '통과', fail: '미통과' }),
  );
  appendDefinition(
    dataSummary,
    '체결 용량 상태',
    quality.capacity_status_note || formatCounts(quality.capacity_status_counts, { pass: '통과', fail: '미통과' }),
  );

  const gateTarget = document.querySelector('#tradability-gate-list');
  gateTarget.replaceChildren();
  const gates = run.tradability_gate || [];
  if (!gates.length) {
    appendEmpty('#tradability-gate-list', '추천/신호 게이트 정보가 없습니다.');
  } else {
    gates.forEach((gate) => {
      const item = document.createElement('div');
      item.className = `gate-item ${gate.passed ? 'pass' : 'block'}`;
      const title = document.createElement('strong');
      title.textContent = `${gate.passed ? '통과' : '점검 필요'} · ${gate.label_ko || gate.key}`;
      const detail = document.createElement('small');
      detail.textContent = gate.description_ko || '추가 실행 가능성 점검 항목입니다.';
      item.append(title, detail);
      gateTarget.appendChild(item);
    });
  }

  const diagnostics = run.factor_diagnostics || {};
  setText('#factor-scope-note', diagnostics.scope_note_ko || '팩터 진단 정보가 없습니다.');

  const categoryTarget = document.querySelector('#factor-category-summary');
  categoryTarget.replaceChildren();
  const categories = diagnostics.category_summary || [];
  if (!categories.length) {
    appendEmpty('#factor-category-summary', '팩터 카테고리 요약이 없습니다.');
  } else {
    categories.slice(0, 8).forEach((row) => {
      const item = document.createElement('div');
      item.className = 'mini-item';
      const title = document.createElement('strong');
      title.textContent = `${humanFactorCategory(row.category)} · ${formatInteger(row.factor_count)}개`;
      const detail = document.createElement('small');
      detail.textContent = `평균 Rank-IC ${formatNumber(row.avg_mean_rank_ic)} · 양수 비율 ${formatPercent(row.avg_positive_ic_rate)} · 예: ${row.example_factors || '-'}`;
      item.append(title, detail);
      categoryTarget.appendChild(item);
    });
  }

  const icTarget = document.querySelector('#factor-rank-ic-summary');
  icTarget.replaceChildren();
  renderRankIcEvidence(icTarget, diagnostics);

  const redundancyTarget = document.querySelector('#factor-redundancy-summary');
  redundancyTarget.replaceChildren();
  renderRedundancyEvidence(redundancyTarget, diagnostics);
}


function renderHoldingsTable() {
  const {
    weighted,
    investedTotal,
    cashTotal,
    topN,
    selectedFactor: factor,
    weightingPolicyId,
    scoreDate,
    maxWeight,
    missingReason,
  } = currentWeightedHoldings();
  setText(
    '#holdings-availability',
    missingReason || `${scoreDate || '-'} 신호 · ${factor} × ${fixedPolicyLabel(state.payload || {}, weightingPolicyId)} · Top ${formatInteger(topN)} · 상한 ${formatPercent(maxWeight)} · 투자 ${formatPercent(investedTotal)} · 현금 ${formatPercent(cashTotal)}`,
  );
  const tbody = document.querySelector('#holdings-table tbody');
  tbody.replaceChildren();
  if (!weighted.length) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 7;
    td.textContent = missingReason || 'Python 선택 포트폴리오가 없습니다.';
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }
  weighted.forEach((row) => {
    const tr = document.createElement('tr');
    appendCell(tr, row.display_rank);
    appendCell(tr, row.symbol, { strong: true });
    appendCell(tr, row.name || '-');
    appendCell(tr, formatNumber(row.score));
    appendCell(tr, Number.isFinite(Number(row.latestPrice)) ? `$${formatNumber(row.latestPrice)}` : '-');
    appendCell(tr, formatPercent(row.display_weight));
    appendCell(tr, scoreDate || '-');
    tbody.appendChild(tr);
  });
}

function renderFactorReturnChart() {
  const factor = selectedFactor();
  const bestFactor = state.payload?.bestFactor;
  let rows = [...(state.payload?.factorRanking || [])]
    .filter((row) => finite(row.selection_score))
    .sort((left, right) => Number(left.rank || 9999) - Number(right.rank || 9999));
  const selectedRow = rows.find((row) => row.factor === factor);
  rows = rows.slice(0, 10);
  if (selectedRow && !rows.some((row) => row.factor === selectedRow.factor)) rows.push(selectedRow);
  const target = document.querySelector('#factor-return-chart');
  target.replaceChildren();
  setText(
    '#factor-chart-meta',
    `선택 ${factor || '-'} · 최고 ${bestFactor || '-'}`,
  );
  if (!rows.length) {
    appendEmpty('#factor-return-chart', '현재 입력에서 비교 가능한 팩터 점수가 없습니다.');
    return;
  }
  const maxAbs = 100;
  rows.forEach((row) => appendBarRow(
    target,
    `${row.rank}. ${row.factor}`,
    `${formatNumber(row.selection_score)} / 100`,
    row.selection_score,
    maxAbs,
    {
      className: [
        row.factor === factor ? 'is-selected' : '',
        row.factor === bestFactor ? 'is-best' : '',
        factorComparisonBarClass({
          selected: row.factor === factor,
          best: row.factor === bestFactor,
        }),
      ].filter(Boolean).join(' '),
    },
  ));
  if (!selectedRow) {
    const missingNote = document.createElement('div');
    missingNote.className = 'scenario-note';
    missingNote.textContent = '선택 팩터는 현재 가드레일 또는 데이터 조건 때문에 상대 점수를 표시할 수 없습니다.';
    target.appendChild(missingNote);
  }
}


function renderPortfolioWeightChart({
  selector,
  metaSelector,
  portfolio,
  className,
  emptyMessage,
}) {
  const {
    weighted,
    cashTotal,
    selectedFactor: factor,
    weightingPolicyId,
  } = portfolio;
  const target = document.querySelector(selector);
  if (!target) return;
  target.replaceChildren();
  setText(
    metaSelector,
    `${factor} · ${fixedPolicyLabel(state.payload || {}, weightingPolicyId)} · ${formatInteger(weighted.length)}종목`,
  );
  if (!weighted.length) {
    appendEmpty(selector, emptyMessage);
    return;
  }
  const maxWeightValue = Math.max(
    ...weighted.map((row) => Number(row.display_weight) || 0),
    Number(cashTotal) || 0,
    0.01,
  );
  weighted.forEach((row) => appendBarRow(
    target,
    row.symbol,
    formatPercent(row.display_weight),
    row.display_weight,
    maxWeightValue,
    { className },
  ));
  if (cashTotal > 0.000001) {
    appendBarRow(
      target,
      '현금/미사용',
      formatPercent(cashTotal),
      cashTotal,
      maxWeightValue,
      { className: CHART_PALETTE_CLASS_MAP.bars.neutralOpen },
    );
  }
}

function renderWeightChart() {
  const comparisonFactor = selectedFactor();
  renderPortfolioWeightChart({
    selector: '#comparison-weight-chart',
    metaSelector: '#comparison-weight-chart-meta',
    portfolio: weightedHoldingsForFactor(comparisonFactor),
    className: CHART_PALETTE_CLASS_MAP.bars.focal,
    emptyMessage: '사용자 선택 팩터의 Python 포트폴리오가 없습니다.',
  });
  renderPortfolioWeightChart({
    selector: '#weight-chart',
    metaSelector: '#weight-chart-meta',
    portfolio: bestWeightedHoldings(),
    className: CHART_PALETTE_CLASS_MAP.bars.best,
    emptyMessage: 'Python 최고 팩터 포트폴리오가 없습니다.',
  });
}

function factorBacktestSeries(run, factor) {
  return (run.factor_backtest_series || []).find((series) => series.factor === factor) || null;
}

function benchmarkBacktestSeries(run) {
  const series = run.benchmark_backtest_series;
  if (!series || !Array.isArray(series.dates)) return null;
  return series;
}

function strictPositiveNav(value) {
  return typeof value === 'number' && Number.isFinite(value) && value > 0
    ? value
    : null;
}

function strictFiniteNumber(value) {
  return typeof value === 'number' && Number.isFinite(value)
    ? value
    : null;
}

function seriesPointsThroughDate(series, date, limit = 260) {
  if (!series || !Array.isArray(series.dates)) return [];
  const points = series.dates.map((pointDate, index) => ({
    date: pointDate,
    equity: strictPositiveNav(series.equity?.[index]),
    drawdown: strictFiniteNumber(series.drawdown?.[index]),
  })).filter((point) => point.date);
  const through = date ? points.filter((point) => String(point.date) <= String(date)) : points;
  const limited = through.slice(-limit);
  return limited.some((point) => point.equity === null) ? [] : limited;
}

function normalizedLine(points) {
  if (!points.length) return [];
  const base = points[0].equity || 1;
  return points.map((point) => ({ ...point, normalized: base ? point.equity / base : point.equity }));
}

function commonEvaluationPeriodFromPayload(payload) {
  const dates = Array.isArray(payload?.performance?.dates) ? payload.performance.dates : [];
  const full = (payload?.performance?.periods || []).find((period) => period?.key === 'FULL');
  if (!full || !dates.length) return null;
  const startIndex = dates.indexOf(full.startDate);
  const endIndex = dates.lastIndexOf(full.endDate);
  if (
    startIndex < 0
    || endIndex <= startIndex
    || endIndex - startIndex !== Number(full.returnObservationCount)
  ) return null;
  return {
    key: full.key,
    label: full.label,
    startDate: full.startDate,
    endDate: full.endDate,
    startIndex,
    endIndex,
    returnObservationCount: endIndex - startIndex,
  };
}

function commonEvaluationSeriesPoints(series, period) {
  if (!series || !period || !Array.isArray(series.dates)) return [];
  const startIndex = series.dates.indexOf(period.startDate);
  const endIndex = series.dates.lastIndexOf(period.endDate);
  if (
    startIndex < 0
    || endIndex <= startIndex
    || endIndex - startIndex !== Number(period.returnObservationCount)
  ) return [];
  const dates = series.dates.slice(startIndex, endIndex + 1);
  const equity = dates.map((_date, offset) => (
    strictPositiveNav(series.equity?.[startIndex + offset])
  ));
  if (
    dates.length !== Number(period.returnObservationCount) + 1
    || equity.some((value) => value === null)
  ) return [];
  const base = equity[0];
  let peak = 1;
  return dates.map((date, offset) => {
    const pointEquity = equity[offset];
    const normalized = pointEquity / base;
    peak = Math.max(peak, normalized);
    return {
      date,
      equity: pointEquity,
      normalized,
      drawdown: peak > 0 ? normalized / peak - 1 : 0,
    };
  });
}

function commonEvaluationSeriesSegments(series, period) {
  if (!series || !period || !Array.isArray(series.dates)) {
    return { points: [], segments: [], missingCount: 0, missingDates: [], available: false };
  }
  const startIndex = series.dates.indexOf(period.startDate);
  const endIndex = series.dates.lastIndexOf(period.endDate);
  if (
    startIndex < 0
    || endIndex <= startIndex
    || endIndex - startIndex !== Number(period.returnObservationCount)
  ) {
    return { points: [], segments: [], missingCount: 0, missingDates: [], available: false };
  }
  const dates = series.dates.slice(startIndex, endIndex + 1);
  const raw = dates.map((_date, offset) => strictPositiveNav(series.equity?.[startIndex + offset]));
  const base = raw[0];
  const terminal = raw.at(-1);
  if (base === null || terminal === null) {
    return {
      points: [],
      segments: [],
      missingCount: raw.filter((value) => value === null).length,
      missingDates: dates.filter((_date, index) => raw[index] === null),
      available: false,
    };
  }
  const segments = [];
  let segment = [];
  let peak = 1;
  const points = [];
  const missingDates = [];
  dates.forEach((date, index) => {
    const value = raw[index];
    if (value === null) {
      missingDates.push(date);
      if (segment.length) segments.push(segment);
      segment = [];
      return;
    }
    const normalized = value / base;
    peak = Math.max(peak, normalized);
    const point = {
      date,
      equity: value,
      normalized,
      drawdown: peak > 0 ? normalized / peak - 1 : 0,
    };
    points.push(point);
    segment.push(point);
  });
  if (segment.length) segments.push(segment);
  return {
    points,
    segments,
    missingCount: missingDates.length,
    missingDates,
    available: points.length >= 2,
  };
}

function formatAxisDate(value) {
  if (!value) return '-';
  const parts = String(value).split('-');
  if (parts.length >= 3) return `${parts[1]}/${parts[2]}`;
  return String(value);
}

function formatChartAxisDate(value, mode = 'month') {
  if (!value) return '-';
  const parts = String(value).split('-').map((part) => Number(part));
  if (parts.length < 3 || parts.some((part) => !Number.isFinite(part))) return formatAxisDate(value);
  const [year, month, day] = parts;
  if (mode === 'quarter') return `${String(year).slice(2)}년 ${Math.floor((month - 1) / 3) + 1}분기`;
  if (mode === 'week') return `${month}/${day}`;
  return `${String(year).slice(2)}.${String(month).padStart(2, '0')}`;
}

function parseDateString(value) {
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

function daysBetween(start, end) {
  const startDate = parseDateString(start);
  const endDate = parseDateString(end);
  if (!startDate || !endDate) return 0;
  return Math.max(0, Math.round((endDate - startDate) / 86400000));
}

function dateTickKey(year, month, day, mode) {
  if (mode === 'week') return `${year}-${String(month).padStart(2, '0')}-W${Math.ceil(day / 7)}`;
  if (mode === 'quarter') return `${year}-Q${Math.floor((month - 1) / 3) + 1}`;
  return `${year}-${String(month).padStart(2, '0')}`;
}

function dateTickMarks(dates) {
  if (!dates.length) return [];
  const spanDays = daysBetween(dates[0], dates.at(-1));
  const mode = spanDays <= 70 ? 'week' : (spanDays <= 420 ? 'month' : 'quarter');
  const ticks = [];
  let previousKey = '';
  dates.forEach((date, index) => {
    const parts = String(date).split('-').map((part) => Number(part));
    if (parts.length < 3 || parts.some((part) => !Number.isFinite(part))) return;
    const [year, month, day] = parts;
    const key = dateTickKey(year, month, day, mode);
    if (index === dates.length - 1 && key === previousKey && ticks.length) {
      ticks[ticks.length - 1] = { index, date, label: formatChartAxisDate(date, mode) };
      previousKey = key;
      return;
    }
    if (index === 0 || index === dates.length - 1 || key !== previousKey) {
      if (mode !== 'quarter' || index === 0 || index === dates.length - 1 || [1, 4, 7, 10].includes(month)) {
        ticks.push({ index, date, label: formatChartAxisDate(date, mode) });
      }
    }
    previousKey = key;
  });
  const maxTicks = 12;
  if (ticks.length <= maxTicks) return ticks;
  const stride = Math.ceil((ticks.length - 2) / (maxTicks - 2));
  return ticks.filter((tick, index) => index === 0 || index === ticks.length - 1 || index % stride === 0);
}

function formatPercentTick(value) {
  if (!Number.isFinite(Number(value))) return '-';
  const percent = Number(value) * 100;
  const decimals = Math.abs(percent) < 10 && Math.abs(percent % 1) > 0.001 ? 1 : 0;
  return `${percent.toFixed(decimals)}%`;
}

function niceReturnTicks(minReturn, maxReturn) {
  let lower = Math.min(Number(minReturn) || 0, 0);
  let upper = Math.max(Number(maxReturn) || 0, 0);
  if (Math.abs(upper - lower) < 0.02) {
    lower -= 0.02;
    upper += 0.02;
  }
  const candidates = [0.01, 0.02, 0.05, 0.10, 0.25, 0.50, 1.0, 2.0, 5.0];
  let step = candidates.at(-1);
  for (const candidate of candidates) {
    const start = Math.floor(lower / candidate) * candidate;
    const end = Math.ceil(upper / candidate) * candidate;
    const count = Math.round((end - start) / candidate) + 1;
    if (count >= 4 && count <= 7) {
      step = candidate;
      break;
    }
  }
  const start = Math.floor(lower / step) * step;
  const end = Math.ceil(upper / step) * step;
  const ticks = [];
  for (let value = start; value <= end + step / 2; value += step) {
    ticks.push(Number(value.toFixed(6)));
  }
  return ticks;
}

const PERFORMANCE_PERIODS = [
  { key: '1W', label: '최근 1주', tradingDays: 5 },
  { key: '1M', label: '최근 1개월', tradingDays: 21 },
  { key: '3M', label: '최근 3개월', tradingDays: 63 },
  { key: '6M', label: '최근 6개월', tradingDays: 126 },
  { key: '1Y', label: '최근 1년', tradingDays: 252 },
  { key: 'YTD', label: 'YTD', ytd: true },
];

const PERFORMANCE_METRICS = [
  { key: 'cumulativeReturn', label: '누적 수익률', formatter: formatPercent },
  { key: 'sharpe', label: '샤프지수', formatter: (value) => formatNumberWithDigits(value, 2) },
  { key: 'volatility', label: '변동성(표준편차)', formatter: formatPercent },
  { key: 'maxDrawdown', label: 'MDD', formatter: formatPercent },
  { key: 'sortino', label: '소르티노 지수', formatter: (value) => formatNumberWithDigits(value, 2) },
  { key: 'calmar', label: '칼마 지수', formatter: (value) => formatNumberWithDigits(value, 2) },
  { key: 'cvar', label: 'CVaR(95%)', formatter: formatPercent },
  { key: 'winRate', label: '일간 승률', formatter: formatPercent },
];

function formatNumberWithDigits(value, digits = 2) {
  if (value === Infinity) return '∞';
  if (value === -Infinity) return '-∞';
  if (value === null || value === undefined || Number.isNaN(Number(value)) || !Number.isFinite(Number(value))) return '-';
  return Number(value).toLocaleString('ko-KR', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function periodPoints(points, period) {
  if (!points.length) return [];
  if (period.ytd) {
    const endYear = String(points.at(-1).date || '').slice(0, 4);
    const ytdPoints = points.filter((point) => String(point.date || '').startsWith(endYear));
    return ytdPoints.length >= 2 ? ytdPoints : points.slice(-Math.min(points.length, 2));
  }
  return points.slice(-Math.min(points.length, period.tradingDays + 1));
}

function returnSeries(points) {
  const returns = [];
  for (let index = 1; index < points.length; index += 1) {
    const previous = Number(points[index - 1].equity);
    const current = Number(points[index].equity);
    if (Number.isFinite(previous) && Number.isFinite(current) && previous > 0) {
      returns.push(current / previous - 1);
    }
  }
  return returns;
}

function populationStd(values) {
  if (values.length < 2) return null;
  const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
  const variance = values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / values.length;
  return Math.sqrt(Math.max(0, variance));
}

function maxDrawdownFromPoints(points) {
  let peak = -Infinity;
  let maxDrawdown = 0;
  points.forEach((point) => {
    const equity = Number(point.equity);
    if (!Number.isFinite(equity)) return;
    peak = Math.max(peak, equity);
    if (peak > 0) maxDrawdown = Math.min(maxDrawdown, equity / peak - 1);
  });
  return maxDrawdown;
}

function cvarFromReturns(returns, tail = 0.05) {
  const clean = returns.filter((value) => Number.isFinite(value)).sort((a, b) => a - b);
  if (!clean.length) return null;
  const count = Math.max(1, Math.ceil(clean.length * tail));
  const tailReturns = clean.slice(0, count);
  return tailReturns.reduce((sum, value) => sum + value, 0) / tailReturns.length;
}

function performanceMetrics(points, period) {
  const slice = periodPoints(points, period);
  if (slice.length < 2) return null;
  const returns = returnSeries(slice);
  if (!returns.length) return null;
  const first = Number(slice[0].equity);
  const last = Number(slice.at(-1).equity);
  const cumulativeReturn = first > 0 ? last / first - 1 : null;
  const mean = returns.reduce((sum, value) => sum + value, 0) / returns.length;
  const std = populationStd(returns);
  const downside = returns.filter((value) => value < 0);
  const downsideStd = downside.length >= 2 ? populationStd(downside) : null;
  const annualizedReturn = cumulativeReturn === null || cumulativeReturn <= -1
    ? null
    : ((1 + cumulativeReturn) ** (252 / returns.length) - 1);
  const volatility = std === null ? null : std * Math.sqrt(252);
  const maxDrawdown = maxDrawdownFromPoints(slice);
  const winRate = returns.filter((value) => value > 0).length / returns.length;
  return {
    cumulativeReturn,
    sharpe: std && std > 0 ? (mean / std) * Math.sqrt(252) : null,
    volatility,
    maxDrawdown,
    sortino: downside.length === 0 && mean > 0 ? Infinity : (downsideStd && downsideStd > 0 ? (mean / downsideStd) * Math.sqrt(252) : null),
    calmar: maxDrawdown < 0 && annualizedReturn !== null ? annualizedReturn / Math.abs(maxDrawdown) : null,
    cvar: cvarFromReturns(returns),
    winRate,
  };
}

function appendSvgText(svg, text, x, y, className, anchor = 'middle') {
  const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
  label.textContent = text;
  label.setAttribute('x', String(x));
  label.setAttribute('y', String(y));
  label.setAttribute('class', className);
  label.setAttribute('text-anchor', anchor);
  svg.appendChild(label);
  return label;
}

function lookbackFilteredPoints(points, months) {
  if (!points.length) return [];
  const endDate = parseDateString(points.at(-1).date);
  if (!endDate) return points;
  const cutoff = new Date(endDate.getTime());
  cutoff.setUTCMonth(cutoff.getUTCMonth() - Math.max(1, Number(months) || DASHBOARD_INPUT_DEFAULTS.lookbackMonths));
  const filtered = points.filter((point) => {
    const pointDate = parseDateString(point.date);
    return pointDate && pointDate >= cutoff;
  });
  return filtered.length >= 2 ? filtered : points.slice(-Math.min(points.length, 2));
}

function rebalanceBucket(dateText, frequency) {
  const parts = String(dateText || '').split('-').map((part) => Number(part));
  if (parts.length < 3 || parts.some((part) => !Number.isFinite(part))) return String(dateText || '');
  const [year, month, day] = parts;
  if (frequency === 'QE') return `${year}-Q${Math.floor((month - 1) / 3) + 1}`;
  if (frequency === 'W') return `${year}-${String(month).padStart(2, '0')}-W${Math.ceil(day / 7)}`;
  return `${year}-${String(month).padStart(2, '0')}`;
}

function isScenarioRebalance(points, index, frequency) {
  if (index <= 0 || index >= points.length) return false;
  return rebalanceBucket(points[index].date, frequency) !== rebalanceBucket(points[index - 1].date, frequency);
}

function allocationConcentration(allocation) {
  const weights = (allocation?.weighted || []).map((row) => Number(row.display_weight) || 0).filter((value) => value > 0);
  if (!weights.length) return 0;
  return weights.reduce((sum, value) => sum + value * value, 0);
}

function adjustedScenarioPointsFromRaw(rawPoints, params, allocation) {
  if (rawPoints.length < 2) return rawPoints;
  const hasAllocation = Array.isArray(allocation?.weighted) && allocation.weighted.length > 0;
  const invested = hasAllocation ? Math.max(0, Math.min(1, Number(allocation?.investedTotal) || 0)) : 1;
  const topN = Math.max(1, Number(params.topN) || DASHBOARD_INPUT_DEFAULTS.topN);
  const concentration = hasAllocation ? allocationConcentration(allocation) : 1 / topN;
  const equalConcentration = 1 / topN;
  const concentrationTilt = Math.max(-0.5, Math.min(2.5, concentration / Math.max(equalConcentration, 1e-6) - 1));
  const exposureMultiplier = Math.max(0.05, Math.min(1.45, invested * (1 + 0.10 * concentrationTilt)));
  const turnoverProxy = Math.max(0, Math.min(2, 0.35 + 0.20 * Math.max(0, concentrationTilt)));
  const adjusted = [{ ...rawPoints[0], equity: 1, drawdown: 0 }];
  let equity = 1;
  let peak = 1;
  for (let index = 1; index < rawPoints.length; index += 1) {
    const previous = Number(rawPoints[index - 1].equity);
    const current = Number(rawPoints[index].equity);
    let dailyReturn = previous > 0 && Number.isFinite(previous) && Number.isFinite(current)
      ? current / previous - 1
      : 0;
    dailyReturn *= exposureMultiplier;
    if (isScenarioRebalance(rawPoints, index, params.rebalanceFrequency)) {
      dailyReturn -= turnoverProxy * params.totalCostRate;
    }
    equity *= Math.max(0.0001, 1 + dailyReturn);
    peak = Math.max(peak, equity);
    adjusted.push({
      date: rawPoints[index].date,
      equity,
      drawdown: peak > 0 ? equity / peak - 1 : 0,
      scenario_exposure: exposureMultiplier,
      scenario_turnover_proxy: turnoverProxy,
    });
  }
  return adjusted;
}

function scenarioAdjustedSeriesPoints(series, date, params, allocation) {
  const rawPoints = lookbackFilteredPoints(seriesPointsThroughDate(series, date, 2000), params.lookbackMonths);
  return adjustedScenarioPointsFromRaw(rawPoints, params, allocation);
}

function tradingDaysForWindow(run, windowKey) {
  const period = (run.periods || []).find((item) => item.key === windowKey);
  const days = Number(period?.trading_days);
  if (Number.isFinite(days) && days > 0) return Math.round(days);
  const fallback = { '1W': 5, '1M': 21, '3M': 63, '6M': 126, '1Y': 252 };
  return fallback[windowKey] || Math.max(21, Math.round((Number(inputScenarioParameters().lookbackMonths) || 12) * 21));
}

function scenarioLookbackTradingDays(params) {
  const months = Number(params?.lookbackMonths);
  if (!Number.isFinite(months) || months <= 0) return null;
  return Math.max(1, Math.round(months * 21));
}

function scenarioWindowTradingDays(run, windowKey, params) {
  const windowDays = tradingDaysForWindow(run, windowKey);
  const lookbackDays = scenarioLookbackTradingDays(params);
  return lookbackDays ? Math.max(1, Math.min(windowDays, lookbackDays)) : windowDays;
}

function scenarioAdjustedWindowPoints(run, factor, date, windowKey, params, allocation) {
  const series = factorBacktestSeries(run, factor);
  const rawPoints = lookbackFilteredPoints(seriesPointsThroughDate(series, date, 2000), params.lookbackMonths);
  if (rawPoints.length < 2) return [];
  const tradingDays = scenarioWindowTradingDays(run, windowKey, params);
  const windowPoints = rawPoints.slice(-Math.min(rawPoints.length, tradingDays + 1));
  return adjustedScenarioPointsFromRaw(windowPoints, params, allocation);
}

function cumulativeReturnFromPoints(points) {
  if (!Array.isArray(points) || points.length < 2) return null;
  const first = Number(points[0].equity);
  const last = Number(points.at(-1).equity);
  if (!Number.isFinite(first) || !Number.isFinite(last) || first <= 0) return null;
  return last / first - 1;
}

function rawPeriodRows(run, date, windowKey) {
  const matrix = periodMatrixEntry(run, date, windowKey);
  if (matrix && Array.isArray(matrix.factors)) {
    return matrix.factors.map((name, index) => ({
      factor: name,
      raw_rank: index + 1,
      rank: index + 1,
      period_return: optionalNumber(matrix.returns?.[index]),
      raw_period_return: optionalNumber(matrix.returns?.[index]),
      window_label: matrix.window_label || windowKey,
      factor_count: matrix.factor_count || matrix.factors.length,
    }));
  }
  return (run.factor_period_rankings || [])
    .filter((row) => row.date === date && row.window === windowKey)
    .map((row, index) => ({
      factor: row.factor,
      raw_rank: row.rank || index + 1,
      rank: row.rank || index + 1,
      period_return: optionalNumber(row.period_return),
      raw_period_return: optionalNumber(row.period_return),
      window_label: row.window_label || windowKey,
      factor_count: row.factor_count || null,
    }));
}

function scenarioFactorStats(run, date, windowKey, factor, params = inputScenarioParameters()) {
  const rawStats = periodFactorStats(run, date, windowKey, factor) || { factor, rank: null, period_return: null };
  const allocation = scenarioAllocationForFactor(run, date, windowKey, factor, params.topN, params.maxWeight).allocation;
  const points = scenarioAdjustedWindowPoints(run, factor, date, windowKey, params, allocation);
  const scenarioReturn = cumulativeReturnFromPoints(points);
  return {
    ...rawStats,
    factor,
    raw_period_return: rawStats?.period_return ?? null,
    period_return: scenarioReturn ?? rawStats?.period_return ?? null,
    scenario_adjusted: scenarioReturn !== null,
    scenario_points: points,
    scenario_allocation: allocation,
    scenario_inputs: params,
  };
}

function scenarioPeriodRows(run, date, windowKey, params = inputScenarioParameters()) {
  const rows = rawPeriodRows(run, date, windowKey);
  const enhanced = rows.map((row) => {
    const scenario = scenarioFactorStats(run, date, windowKey, row.factor, params);
    return {
      ...row,
      raw_period_return: row.raw_period_return ?? row.period_return,
      period_return: scenario.period_return,
      scenario_adjusted: scenario.scenario_adjusted,
      scenario_points: scenario.scenario_points,
      scenario_allocation: scenario.scenario_allocation,
    };
  });
  return enhanced
    .sort((a, b) => {
      const ar = Number(a.period_return);
      const br = Number(b.period_return);
      if (Number.isFinite(ar) && Number.isFinite(br) && ar !== br) return br - ar;
      if (Number.isFinite(br) !== Number.isFinite(ar)) return Number.isFinite(br) ? 1 : -1;
      return Number(a.raw_rank || 9999) - Number(b.raw_rank || 9999);
    })
    .map((row, index) => ({
      ...row,
      rank: index + 1,
      factor_count: row.factor_count || enhanced.length,
    }));
}

function scenarioBestStats(run, date, windowKey, params = inputScenarioParameters()) {
  return scenarioPeriodRows(run, date, windowKey, params)[0] || periodBestStats(run, date, windowKey);
}

function chartSeriesModel(points = [], segments = null, extra = {}) {
  const finitePoints = (points || []).filter((point) => Number.isFinite(point?.normalized));
  return {
    points: finitePoints,
    segments: segments || (finitePoints.length ? [finitePoints] : []),
    missingCount: 0,
    missingDates: [],
    available: finitePoints.length >= 2,
    ...extra,
  };
}

function fullPythonPeriod() {
  return (state.payload?.performance?.periods || []).find((period) => period?.key === 'FULL') || null;
}

function appendComparisonSummaryItem(target, titleText, valueText, detailText, className = '') {
  const item = document.createElement('div');
  item.className = `comparison-summary-item ${className}`.trim();
  const title = document.createElement('small');
  title.textContent = titleText;
  const value = document.createElement('strong');
  value.textContent = valueText;
  const detail = document.createElement('span');
  detail.textContent = detailText;
  item.append(title, value, detail);
  target.appendChild(item);
}

function renderBacktestComparisonSummary(run, {
  factor,
  best,
}) {
  const target = document.querySelector('#backtest-comparison-summary');
  if (!target) return;
  target.replaceChildren();
  const full = fullPythonPeriod();
  const selectedMetrics = full?.factors?.[factor];
  const bestMetrics = full?.factors?.[best?.factor];
  const official = factor === state.payload?.bestFactor;
  target.hidden = official;
  if (official) return;
  appendComparisonSummaryItem(
    target,
    '선택 팩터',
    factor || '-',
    `전체 평가기간 누적 ${formatPercent(pythonPerformanceMetric(selectedMetrics, 'cumulativeReturn'))}`,
    'selected',
  );
  appendComparisonSummaryItem(
    target,
    '동일 입력 최고 팩터',
    best?.factor || '-',
    best?.factor
      ? `전체 평가기간 누적 ${formatPercent(pythonPerformanceMetric(bestMetrics, 'cumulativeReturn'))} · 선택 점수 ${formatNumber(best.selectionScore)} / 100`
      : '최고 팩터 자료 없음',
    'best',
  );
}

function nearestChartDate(dates = [], requested = null) {
  const validDates = dates.filter(Boolean);
  if (!validDates.length) return null;
  if (requested && validDates.includes(requested)) return requested;
  const targetTime = parseDateString(requested)?.getTime();
  if (!Number.isFinite(targetTime)) return validDates.at(-1);
  return validDates.reduce((nearest, date) => {
    const distance = Math.abs((parseDateString(date)?.getTime() ?? targetTime) - targetTime);
    const nearestDistance = Math.abs((parseDateString(nearest)?.getTime() ?? targetTime) - targetTime);
    return distance < nearestDistance ? date : nearest;
  }, validDates[0]);
}

function chartPointAtDate(points = [], date = null) {
  return points.find((point) => point.date === date) || null;
}

function clientPointToSvg(svg, clientX, clientY = 0) {
  const point = svg?.createSVGPoint?.();
  const ctm = svg?.getScreenCTM?.();
  if (!point || !ctm || typeof ctm.inverse !== 'function') return null;
  try {
    point.x = Number(clientX);
    point.y = Number(clientY);
    const transformed = point.matrixTransform(ctm.inverse());
    return finite(transformed?.x) && finite(transformed?.y)
      ? { x: Number(transformed.x), y: Number(transformed.y) }
      : null;
  } catch (_error) {
    return null;
  }
}

function svgPointToClient(svg, svgX, svgY = 0) {
  const point = svg?.createSVGPoint?.();
  const ctm = svg?.getScreenCTM?.();
  if (!point || !ctm) return null;
  try {
    point.x = Number(svgX);
    point.y = Number(svgY);
    const transformed = point.matrixTransform(ctm);
    return finite(transformed?.x) && finite(transformed?.y)
      ? { x: Number(transformed.x), y: Number(transformed.y) }
      : null;
  } catch (_error) {
    return null;
  }
}

function scrollLeftToReveal({
  scrollLeft,
  clientWidth,
  scrollWidth,
  targetX,
  padding = 48,
}) {
  const current = Math.max(0, Number(scrollLeft) || 0);
  const viewport = Math.max(0, Number(clientWidth) || 0);
  const content = Math.max(viewport, Number(scrollWidth) || 0);
  const target = Number(targetX);
  if (!Number.isFinite(target) || target >= current + padding && target <= current + viewport - padding) {
    return current;
  }
  return Math.max(0, Math.min(content - viewport, target - viewport / 2));
}

function chartIndexForPointer({
  svgX,
  plotLeft,
  plotWidth,
  count,
  clientX,
  hitLeft,
  hitRight,
}) {
  const lastIndex = Math.max(0, Number(count) - 1);
  if (!Number.isInteger(lastIndex) || lastIndex <= 0) return 0;
  const hitWidth = Math.max(0, Number(hitRight) - Number(hitLeft));
  const edgeTolerance = Math.min(12, hitWidth / 4);
  if (Number(clientX) <= Number(hitLeft) + edgeTolerance) return 0;
  if (Number(clientX) >= Number(hitRight) - edgeTolerance) return lastIndex;
  const ratio = Math.max(0, Math.min(1, (Number(svgX) - Number(plotLeft)) / Math.max(Number(plotWidth), 1)));
  return Math.round(ratio * lastIndex);
}

function formatChartReturn(value) {
  if (value === null || value === undefined || value === '' || !Number.isFinite(Number(value))) return '관측 없음';
  const percent = Number(value) * 100;
  return `${percent > 0 ? '+' : ''}${percent.toFixed(2)}%`;
}

function compactChartSeriesLabel(value, maxLength = 22) {
  const label = String(value || '-');
  return label.length > maxLength ? `${label.slice(0, Math.max(1, maxLength - 1))}…` : label;
}

function layoutChartEndLabels(items = [], options = {}) {
  const minY = Number(options.minY);
  const maxY = Number(options.maxY);
  const requestedGap = Math.max(0, Number(options.gap) || 0);
  const labels = items
    .filter((item) => item && Number.isFinite(Number(item.y)))
    .map((item) => ({ ...item, y: Number(item.y) }))
    .sort((left, right) => left.y - right.y);
  if (!labels.length || !Number.isFinite(minY) || !Number.isFinite(maxY) || maxY < minY) {
    return [];
  }
  const gap = labels.length <= 1
    ? 0
    : Math.min(requestedGap, (maxY - minY) / (labels.length - 1));
  labels.forEach((item, index) => {
    const bounded = Math.max(minY, Math.min(maxY, item.y));
    item.labelY = index === 0
      ? bounded
      : Math.max(bounded, labels[index - 1].labelY + gap);
  });
  if (labels.at(-1).labelY > maxY) {
    labels.at(-1).labelY = maxY;
    for (let index = labels.length - 2; index >= 0; index -= 1) {
      labels[index].labelY = Math.min(labels[index].labelY, labels[index + 1].labelY - gap);
    }
  }
  if (labels[0].labelY < minY) {
    const shift = minY - labels[0].labelY;
    labels.forEach((item) => { item.labelY += shift; });
  }
  return labels;
}

function renderBacktestChart() {
  const run = currentRun();
  const factor = selectedFactor();
  const benchmark = benchmarkBacktestSeries(run);
  const benchmarks = Array.isArray(run.comparison_benchmark_series) && run.comparison_benchmark_series.length
    ? run.comparison_benchmark_series
    : (benchmark ? [benchmark] : []);
  const commonPeriod = run.common_evaluation_period;
  const bestRow = (state.payload?.factorRanking || []).find((row) => row.selected === true);
  const best = {
    factor: state.payload?.bestFactor,
    selectionScore: bestRow?.selection_score,
  };
  const selectedModel = commonPeriod
    ? commonEvaluationSeriesSegments(factorBacktestSeries(run, factor), commonPeriod)
    : chartSeriesModel([]);
  const bestModel = best?.factor
    ? (commonPeriod
      ? commonEvaluationSeriesSegments(factorBacktestSeries(run, best.factor), commonPeriod)
      : chartSeriesModel([]))
    : chartSeriesModel([]);
  const benchmarkSeriesList = benchmarks.map((series) => ({
    key: `benchmark-${series.symbol}`,
    symbol: series.symbol,
    label: series.label_ko || BENCHMARK_LABELS[series.symbol] || series.symbol,
    className: benchmarkPaletteClass(series.symbol),
    model: commonPeriod
      ? commonEvaluationSeriesSegments(series, commonPeriod)
      : chartSeriesModel([]),
  }));
  const seriesModels = [
    {
      key: 'selected',
      factor,
      label: best?.factor === factor ? `선택 · 최고 ${factor || '-'}` : `선택 ${factor || '-'}`,
      className: 'selected',
      model: selectedModel,
    },
    ...(best?.factor && best.factor !== factor ? [{
      key: 'best',
      factor: best.factor,
      label: `최고 ${best.factor}`,
      className: 'best',
      model: bestModel,
    }] : []),
    ...benchmarkSeriesList,
  ].filter((series) => series.model.points.length);
  const performanceSeries = seriesModels.map((series) => ({
    key: series.key,
    factor: series.factor,
    symbol: series.symbol,
    label: series.label,
    points: series.model.points,
  }));
  const target = document.querySelector('#backtest-chart');
  if (!target) return;
  target.replaceChildren();
  setText(
    '#backtest-chart-meta',
    commonPeriod
      ? `${commonPeriod.startDate} → ${commonPeriod.endDate} · 누적 수익률`
      : '공통 평가기간 없음',
  );
  renderBacktestComparisonSummary(run, { factor, best });
  const allPoints = seriesModels.flatMap((series) => series.model.points);
  if (!allPoints.length) {
    appendEmpty(
      '#backtest-chart',
      '선택 팩터·Python 최고 팩터·비교지수의 공통 평가기간 원자료가 없습니다.',
    );
    renderPerformanceMetricsTable(performanceSeries);
    return;
  }

  const allValues = allPoints.map((point) => point.normalized).filter((value) => Number.isFinite(value));
  const returnValues = allValues.map((value) => value - 1);
  const tickReturns = niceReturnTicks(Math.min(...returnValues, 0), Math.max(...returnValues, 0));
  const minValue = Math.min(...tickReturns) + 1;
  const maxValue = Math.max(...tickReturns) + 1;
  const allDates = [...new Set(allPoints.map((point) => point.date).filter(Boolean))].sort();
  const dateToIndex = new Map(allDates.map((pointDate, index) => [pointDate, index]));
  const seriesKeys = seriesModels.map((series) => series.key);
  const chartState = state.backtestChart;
  const signature = [
    state.payload?.resultKey,
    factor,
    best?.factor,
    commonPeriod?.startDate,
    commonPeriod?.endDate,
  ].join('|');
  if (chartState.signature !== signature) {
    chartState.signature = signature;
    chartState.previewSeriesKey = null;
    chartState.previewDate = null;
  }
  if (!seriesKeys.includes(chartState.pinnedSeriesKey)) chartState.pinnedSeriesKey = seriesKeys[0];
  chartState.pinnedDate = nearestChartDate(
    allDates,
    chartState.pinnedDate || commonPeriod?.endDate || allDates.at(-1),
  );

  const width = 1240;
  const height = 420;
  const plot = { left: 78, right: 265, top: 26, bottom: 60 };
  const plotWidth = width - plot.left - plot.right;
  const plotHeight = height - plot.top - plot.bottom;
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', `${commonPeriod?.startDate || '-'}부터 ${commonPeriod?.endDate || '-'}까지 누적 성과 비교`);
  const yFor = (value) => height - plot.bottom - ((value - minValue) / Math.max(0.000001, maxValue - minValue)) * plotHeight;
  const xForDate = (date) => {
    const index = dateToIndex.get(date) ?? 0;
    return plot.left + (allDates.length <= 1 ? 0 : index / (allDates.length - 1) * plotWidth);
  };
  const xFor = (point) => xForDate(point.date);
  tickReturns.forEach((tickReturn) => {
    const y = yFor(tickReturn + 1);
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', String(plot.left));
    line.setAttribute('x2', String(width - plot.right));
    line.setAttribute('y1', String(y));
    line.setAttribute('y2', String(y));
    line.setAttribute('class', 'line-grid');
    svg.appendChild(line);
    appendSvgText(svg, formatPercentTick(tickReturn), plot.left - 9, y + 4, 'axis-label', 'end');
  });
  const yAxis = document.createElementNS('http://www.w3.org/2000/svg', 'line');
  yAxis.setAttribute('x1', String(plot.left));
  yAxis.setAttribute('x2', String(plot.left));
  yAxis.setAttribute('y1', String(plot.top));
  yAxis.setAttribute('y2', String(height - plot.bottom));
  yAxis.setAttribute('class', 'axis-line');
  svg.appendChild(yAxis);
  const xAxis = document.createElementNS('http://www.w3.org/2000/svg', 'line');
  xAxis.setAttribute('x1', String(plot.left));
  xAxis.setAttribute('x2', String(width - plot.right));
  xAxis.setAttribute('y1', String(height - plot.bottom));
  xAxis.setAttribute('y2', String(height - plot.bottom));
  xAxis.setAttribute('class', 'axis-line');
  svg.appendChild(xAxis);
  dateTickMarks(allDates).forEach((tickMark) => {
    const x = xForDate(tickMark.date);
    const tick = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    tick.setAttribute('x1', String(x));
    tick.setAttribute('x2', String(x));
    tick.setAttribute('y1', String(height - plot.bottom));
    tick.setAttribute('y2', String(height - plot.bottom + 5));
    tick.setAttribute('class', 'axis-line');
    svg.appendChild(tick);
    appendSvgText(svg, tickMark.label, x, height - plot.bottom + 20, 'axis-label');
  });
  appendSvgText(svg, '날짜', plot.left + plotWidth / 2, height - 6, 'axis-title');
  const yTitle = appendSvgText(svg, '평가 시작 대비 누적 수익률', 14, plot.top + plotHeight / 2, 'axis-title');
  yTitle.setAttribute('transform', `rotate(-90 14 ${plot.top + plotHeight / 2})`);
  const toPolyline = (points) => points.map((point) => (
    `${xFor(point).toFixed(1)},${yFor(point.normalized).toFixed(1)}`
  )).join(' ');
  seriesModels.forEach((series) => {
    series.model.segments.forEach((segment) => {
      if (!segment.length) return;
      const polyline = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
      polyline.setAttribute('points', toPolyline(segment));
      polyline.setAttribute('class', `line-path ${series.className}`);
      polyline.setAttribute('data-series-key', series.key);
      svg.appendChild(polyline);
    });
  });
  const plotEndX = width - plot.right;
  const endLabelX = plotEndX + 24;
  appendSvgText(svg, '종료일 누적', endLabelX, 16, 'chart-end-heading', 'start');
  const endLabels = layoutChartEndLabels(
    seriesModels.map((series) => ({
      series,
      point: series.model.points.at(-1),
      y: yFor(series.model.points.at(-1)?.normalized),
    })),
    {
      minY: plot.top + 8,
      maxY: height - plot.bottom - 8,
      gap: 28,
    },
  );
  endLabels.forEach(({ series, point, labelY }) => {
    const connector = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
    connector.setAttribute('points', [
      `${xFor(point).toFixed(1)},${yFor(point.normalized).toFixed(1)}`,
      `${(plotEndX + 9).toFixed(1)},${labelY.toFixed(1)}`,
      `${(endLabelX - 7).toFixed(1)},${labelY.toFixed(1)}`,
    ].join(' '));
    connector.setAttribute('class', `chart-end-connector ${series.className}`);
    connector.setAttribute('data-series-key', series.key);
    svg.appendChild(connector);
    const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    text.setAttribute('x', String(endLabelX));
    text.setAttribute('y', String(labelY));
    text.setAttribute('class', `chart-end-label ${series.className}`);
    text.setAttribute('data-series-key', series.key);
    text.setAttribute('dominant-baseline', 'middle');
    const title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
    title.textContent = `${series.label} ${formatChartReturn(point.normalized - 1)}`;
    text.appendChild(title);
    const name = document.createElementNS('http://www.w3.org/2000/svg', 'tspan');
    name.setAttribute('class', 'chart-end-name');
    name.textContent = compactChartSeriesLabel(series.label);
    text.appendChild(name);
    const value = document.createElementNS('http://www.w3.org/2000/svg', 'tspan');
    value.setAttribute('class', 'chart-end-value');
    value.setAttribute('dx', '8');
    value.textContent = formatChartReturn(point.normalized - 1);
    text.appendChild(value);
    svg.appendChild(text);
  });
  const dateGuide = document.createElementNS('http://www.w3.org/2000/svg', 'line');
  dateGuide.setAttribute('y1', String(plot.top));
  dateGuide.setAttribute('y2', String(height - plot.bottom));
  dateGuide.setAttribute('class', 'chart-date-guide');
  svg.appendChild(dateGuide);
  const selectedDatePoints = new Map();
  seriesModels.forEach((series) => {
    const marker = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    marker.setAttribute('r', '4');
    marker.setAttribute('class', `chart-series-point ${series.className}`);
    marker.setAttribute('data-series-key', series.key);
    svg.appendChild(marker);
    selectedDatePoints.set(series.key, marker);
  });
  const activePoint = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
  activePoint.setAttribute('r', '5.5');
  activePoint.setAttribute('class', 'chart-active-point');
  svg.appendChild(activePoint);
  const hitTarget = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
  hitTarget.setAttribute('x', String(plot.left));
  hitTarget.setAttribute('y', String(plot.top));
  hitTarget.setAttribute('width', String(plotWidth));
  hitTarget.setAttribute('height', String(plotHeight));
  hitTarget.setAttribute('class', 'chart-hit-target');
  svg.appendChild(hitTarget);
  target.appendChild(svg);

  const seriesControls = document.querySelector('#backtest-series-controls');
  if (seriesControls) {
    seriesControls.replaceChildren();
    seriesModels.forEach((series) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `chart-series-button ${series.className}`;
      button.dataset.seriesKey = series.key;
      const name = document.createElement('span');
      name.className = 'chart-series-name';
      name.textContent = series.label;
      const value = document.createElement('strong');
      value.className = 'chart-series-value';
      value.textContent = '관측 없음';
      button.replaceChildren(name, value);
      button.addEventListener('pointerenter', () => {
        chartState.previewSeriesKey = series.key;
        updatePresentation();
      });
      button.addEventListener('pointerleave', () => {
        chartState.previewSeriesKey = null;
        updatePresentation();
      });
      button.addEventListener('focus', () => {
        chartState.previewSeriesKey = series.key;
        updatePresentation();
      });
      button.addEventListener('blur', () => {
        chartState.previewSeriesKey = null;
        updatePresentation();
      });
      button.addEventListener('click', () => {
        chartState.pinnedSeriesKey = series.key;
        chartState.previewSeriesKey = null;
        updatePresentation();
      });
      seriesControls.appendChild(button);
    });
  }

  const dateInput = document.querySelector('#backtest-date-input');
  if (dateInput) {
    dateInput.min = allDates[0];
    dateInput.max = allDates.at(-1);
    dateInput.value = chartState.pinnedDate;
    dateInput.oninput = () => {
      chartState.previewDate = nearestChartDate(allDates, dateInput.value);
      updatePresentation();
    };
    dateInput.onchange = () => {
      chartState.pinnedDate = nearestChartDate(allDates, dateInput.value);
      chartState.previewDate = null;
      dateInput.value = chartState.pinnedDate;
      updatePresentation();
      ensureActiveDateVisible(chartState.pinnedDate);
    };
    dateInput.onblur = () => {
      chartState.previewDate = null;
      dateInput.value = chartState.pinnedDate;
      updatePresentation();
    };
  }
  const resetButton = document.querySelector('#backtest-date-reset');
  if (resetButton) {
    resetButton.onclick = () => {
      chartState.pinnedDate = nearestChartDate(allDates, commonPeriod?.endDate || allDates.at(-1));
      chartState.previewDate = null;
      if (dateInput) dateInput.value = chartState.pinnedDate;
      updatePresentation();
      ensureActiveDateVisible(chartState.pinnedDate);
      target.focus({ preventScroll: true });
    };
  }

  function updatePresentation() {
    const activeSeriesKey = seriesKeys.includes(chartState.previewSeriesKey)
      ? chartState.previewSeriesKey
      : chartState.pinnedSeriesKey;
    const activeDate = chartState.previewDate || chartState.pinnedDate;
    const activeSeries = seriesModels.find((series) => series.key === activeSeriesKey) || seriesModels[0];
    svg.querySelectorAll('[data-series-key]').forEach((path) => {
      const active = path.getAttribute('data-series-key') === activeSeries.key;
      path.classList.toggle('is-active', active);
      path.classList.toggle('is-muted', !active);
    });
    seriesControls?.querySelectorAll('button').forEach((button) => {
      const key = button.dataset.seriesKey;
      const series = seriesModels.find((item) => item.key === key);
      const seriesPoint = chartPointAtDate(series?.model.points, activeDate);
      const formattedValue = seriesPoint
        ? formatChartReturn(seriesPoint.normalized - 1)
        : '관측 없음';
      button.setAttribute('aria-pressed', String(key === chartState.pinnedSeriesKey));
      button.classList.toggle('is-preview', key === chartState.previewSeriesKey);
      button.querySelector('.chart-series-value').textContent = formattedValue;
      button.setAttribute('aria-label', `${series?.label || key} · ${activeDate} ${formattedValue}`);
    });
    const guideX = xForDate(activeDate);
    dateGuide.setAttribute('x1', String(guideX));
    dateGuide.setAttribute('x2', String(guideX));
    selectedDatePoints.forEach((marker, key) => {
      const series = seriesModels.find((item) => item.key === key);
      const seriesPoint = chartPointAtDate(series?.model.points, activeDate);
      if (!seriesPoint) {
        marker.setAttribute('hidden', '');
        return;
      }
      marker.removeAttribute('hidden');
      marker.setAttribute('cx', String(guideX));
      marker.setAttribute('cy', String(yFor(seriesPoint.normalized)));
    });
    const point = chartPointAtDate(activeSeries.model.points, activeDate);
    if (point) {
      activePoint.removeAttribute('hidden');
      activePoint.setAttribute('class', `chart-active-point ${activeSeries.className}`);
      activePoint.setAttribute('cx', String(guideX));
      activePoint.setAttribute('cy', String(yFor(point.normalized)));
    } else {
      activePoint.setAttribute('hidden', '');
    }
    setText('#backtest-active-date', activeDate || '-');
    setText('#backtest-active-series', activeSeries.label);
    setText('#backtest-active-value', point ? formatChartReturn(point.normalized - 1) : '관측 없음');
    setText(
      '#backtest-active-context',
      point
        ? `평가 시작 대비 누적 수익률 · 원본 관측 ${allDates.indexOf(activeDate) + 1}/${allDates.length}`
        : '선택일에 해당 계열 관측이 없어 임의 보간하지 않습니다.',
    );
    const valueNode = document.querySelector('#backtest-active-value');
    valueNode?.classList.toggle('positive', Boolean(point && point.normalized > 1));
    valueNode?.classList.toggle('negative', Boolean(point && point.normalized < 1));
    target.setAttribute('aria-label', `${activeDate} ${activeSeries.label} ${point ? formatChartReturn(point.normalized - 1) : '관측 없음'}`);
  }

  const dateForClientX = (clientX, clientY) => {
    const hitBounds = hitTarget.getBoundingClientRect();
    const point = clientPointToSvg(svg, clientX, clientY);
    const viewX = point?.x ?? plot.left;
    const index = chartIndexForPointer({
      svgX: viewX,
      plotLeft: plot.left,
      plotWidth,
      count: allDates.length,
      clientX,
      hitLeft: hitBounds.left,
      hitRight: hitBounds.right,
    });
    return allDates[index];
  };
  hitTarget.addEventListener('pointermove', (event) => {
    if (event.pointerType === 'touch') return;
    chartState.previewDate = dateForClientX(event.clientX, event.clientY);
    updatePresentation();
  });
  hitTarget.addEventListener('pointerleave', () => {
    chartState.previewDate = null;
    updatePresentation();
  });
  hitTarget.addEventListener('click', (event) => {
    chartState.pinnedDate = dateForClientX(event.clientX, event.clientY);
    chartState.previewDate = null;
    if (dateInput) dateInput.value = chartState.pinnedDate;
    updatePresentation();
    ensureActiveDateVisible(chartState.pinnedDate);
    target.focus({ preventScroll: true });
  });
  target.onkeydown = (event) => {
    const currentIndex = Math.max(0, allDates.indexOf(chartState.pinnedDate));
    let nextIndex = null;
    if (event.key === 'ArrowLeft') nextIndex = Math.max(0, currentIndex - 1);
    if (event.key === 'ArrowRight') nextIndex = Math.min(allDates.length - 1, currentIndex + 1);
    if (event.key === 'Home') nextIndex = 0;
    if (event.key === 'End') nextIndex = allDates.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    chartState.pinnedDate = allDates[nextIndex];
    chartState.previewDate = null;
    if (dateInput) dateInput.value = chartState.pinnedDate;
    updatePresentation();
    ensureActiveDateVisible(chartState.pinnedDate);
  };
  function ensureActiveDateVisible(date) {
    if (!date || target.scrollWidth <= target.clientWidth) return;
    const revealX = date === allDates.at(-1) ? width : xForDate(date);
    const screenPoint = svgPointToClient(svg, revealX, height / 2);
    if (!screenPoint) return;
    const targetRect = target.getBoundingClientRect();
    const contentX = target.scrollLeft + screenPoint.x - targetRect.left;
    target.scrollLeft = scrollLeftToReveal({
      scrollLeft: target.scrollLeft,
      clientWidth: target.clientWidth,
      scrollWidth: target.scrollWidth,
      targetX: contentX,
    });
  }
  updatePresentation();
  ensureActiveDateVisible(chartState.pinnedDate);
  renderPerformanceMetricsTable(performanceSeries);
}

function pythonPerformanceSource(period, series) {
  if (series.symbol) return period.benchmarks?.[series.symbol] || null;
  if (series.factor) return period.factors?.[series.factor] || null;
  return null;
}

function pythonPerformanceMetric(source, key) {
  if (!source || source.available === false) return null;
  const aliases = {
    volatility: 'annualizedVolatility',
    cvar: 'cvar5',
  };
  const value = source[aliases[key] || key];
  return Number.isFinite(Number(value)) ? Number(value) : null;
}

function renderPythonPerformanceMetricsTable(target, seriesList, periods) {
  target.replaceChildren();
  const availableSeries = (seriesList || []).filter(
    (series) => (series.factor || series.symbol) && series.symbol !== '^IXIC',
  );
  const heading = document.createElement('div');
  heading.className = 'performance-metrics-heading';
  const headingText = document.createElement('div');
  const title = document.createElement('h4');
  title.textContent = '기간별 성과 지표';
  headingText.append(title);
  heading.appendChild(headingText);
  target.appendChild(heading);

  const grid = document.createElement('div');
  grid.className = 'performance-period-grid';
  periods.forEach((period) => {
    const card = document.createElement('section');
    card.className = 'performance-period-card';
    const periodTitle = document.createElement('h5');
    periodTitle.textContent = period.label || period.key;
    card.appendChild(periodTitle);
    const periodMeta = document.createElement('p');
    periodMeta.className = 'performance-period-meta';
    periodMeta.textContent = `${period.startDate || '-'} → ${period.endDate || '-'} · ${formatInteger(period.returnObservationCount)}개 수익률`;
    card.appendChild(periodMeta);

    const qualityRows = availableSeries.map((series) => ({
      series,
      source: pythonPerformanceSource(period, series),
    }));
    const partial = qualityRows.filter(({ source }) => source?.available === true && source.riskMetricsExact === false);
    const unavailable = qualityRows.filter(({ source }) => !source || source.available === false);
    if (partial.length || unavailable.length) {
      const quality = document.createElement('p');
      quality.className = 'performance-quality-note';
      const parts = [];
      partial.forEach(({ series, source }) => {
        parts.push(`${series.factor || series.symbol}: 누적 endpoint 정확 · 일간 위험 ${formatInteger(source.riskObservationCount)}/${formatInteger(source.requiredReturnCount)} 관측`);
      });
      unavailable.forEach(({ series, source }) => {
        parts.push(`${series.factor || series.symbol}: 자료 없음${source?.unavailableReason ? ` (${source.unavailableReason})` : ''}`);
      });
      quality.textContent = parts.join(' · ');
      card.appendChild(quality);
    }

    const wrap = document.createElement('div');
    wrap.className = 'performance-table-wrap';
    wrap.setAttribute('role', 'region');
    wrap.setAttribute('tabindex', '0');
    wrap.setAttribute('aria-label', `${period.label || period.key} 성과 지표 표`);
    const table = document.createElement('table');
    table.className = 'performance-table';
    table.setAttribute('aria-label', `${period.label || period.key} 선택 팩터, 최고 팩터, SPY, QQQ 성과 비교`);
    const thead = document.createElement('thead');
    const header = document.createElement('tr');
    appendHeader(header, '지표');
    availableSeries.forEach((series) => {
      const th = document.createElement('th');
      th.setAttribute('scope', 'col');
      const label = document.createElement('span');
      const seriesClass = series.symbol === 'SPY'
        ? 'benchmark-spy'
        : (series.symbol === 'QQQ' ? 'benchmark-qqq' : series.key);
      label.className = `series-name ${seriesClass}`;
      const role = document.createElement('strong');
      role.textContent = series.symbol || (series.key === 'selected' ? '선택 팩터' : '최고 팩터');
      const identity = document.createElement('small');
      identity.textContent = series.factor || (series.label && series.label !== series.symbol ? series.label : '조정가격 보유');
      label.title = series.label || `${role.textContent} ${identity.textContent}`;
      label.append(role, identity);
      th.appendChild(label);
      header.appendChild(th);
    });
    thead.appendChild(header);
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    PERFORMANCE_METRICS.forEach((metric) => {
      const tr = document.createElement('tr');
      appendRowHeader(tr, metric.label);
      availableSeries.forEach((series) => {
        const source = pythonPerformanceSource(period, series);
        const value = pythonPerformanceMetric(source, metric.key);
        const signedMetric = ['cumulativeReturn', 'maxDrawdown', 'cvar'].includes(metric.key);
        const className = value === null ? 'neutral' : (signedMetric ? classForNumber(value) : '');
        const td = document.createElement('td');
        td.className = className;
        td.textContent = value === null ? '-' : metric.formatter(value);
        if (source?.available === false && source.unavailableReason) td.title = source.unavailableReason;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    card.appendChild(wrap);
    grid.appendChild(card);
  });
  target.appendChild(grid);
}

function renderPerformanceMetricsTable(seriesList) {
  const target = document.querySelector('#performance-metrics-table');
  if (!target) return;
  const pythonPeriods = state.payload?.performance?.periods;
  if (Array.isArray(pythonPeriods) && pythonPeriods.length) {
    renderPythonPerformanceMetricsTable(target, seriesList, pythonPeriods);
    return;
  }
  target.replaceChildren();
  appendEmpty(
    '#performance-metrics-table',
    'Python 기간별 성과 원자료가 없습니다. 브라우저가 지표를 재계산하거나 추정값으로 대체하지 않습니다.',
  );
}

function normalizeDailyActualRows(sourceRows, sourceMeta = {}) {
  return (sourceRows || [])
    .map((row, index) => {
      if (Array.isArray(row)) {
        return {
          date: sourceMeta.date || '-',
          window: sourceMeta.window || '-',
          windowLabel: sourceMeta.window_label || sourceMeta.window || '-',
          factor: sourceMeta.factor || '-',
          rank: index + 1,
          symbol: row[0],
          actualWeight: Number(row[1]),
          score: Number(row[2]),
          weightDate: sourceMeta.weight_date || sourceMeta.date || '-',
          scoreDate: sourceMeta.score_date || sourceMeta.date || '-',
          source: sourceMeta.weight_source || '백테스트 일별 보유 비중',
        };
      }
      return {
        date: row.date || sourceMeta.date || '-',
        window: row.window || sourceMeta.window || null,
        windowLabel: row.window_label || sourceMeta.window_label || row.window || null,
        factor: row.factor || sourceMeta.factor || '-',
        rank: row.rank || index + 1,
        symbol: row.symbol,
        actualWeight: Number(row.default_weight ?? row.weight),
        score: Number(row.score),
        weightDate: row.weight_date || sourceMeta.weight_date || row.date || sourceMeta.date || '-',
        scoreDate: row.score_date || sourceMeta.score_date || row.date || sourceMeta.date || '-',
        executionDate: row.execution_date || sourceMeta.execution_date || null,
        executionStatus: row.execution_status || sourceMeta.execution_status || null,
        valuationAvailable: (row.valuation_available ?? sourceMeta.valuation_available) !== false,
        cashWeight: optionalNumber(row.cash_weight ?? sourceMeta.cash_weight),
        weightTiming: row.weight_timing || sourceMeta.weight_timing || null,
        weightingPolicyId: row.weighting_policy_id || sourceMeta.weighting_policy_id || null,
        historySource: row.history_source || sourceMeta.history_source || null,
        source: row.weight_source || sourceMeta.weight_source || '백테스트 일별 보유 비중',
      };
    })
    .filter((row) => row.symbol && Number.isFinite(row.actualWeight) && row.actualWeight > 0)
    .sort((a, b) => (
      String(b.date).localeCompare(String(a.date))
      || Number(a.rank || 9999) - Number(b.rank || 9999)
      || Number(b.actualWeight) - Number(a.actualWeight)
    ));
}

function selectedDailyWeightRows(run, date, windowKey, factor) {
  const bestFactorName = run.summary?.selected_factor;
  const bestTarget = run.best_factor_portfolio || {};
  const factorTarget = run.factor_portfolios?.[factor];
  const target = factorTarget?.factor === factor
    ? factorTarget
    : (factor === bestFactorName && bestTarget.factor === factor
      ? bestTarget
      : {
      factor,
      status: 'unavailable_factor_target',
      signalDate: null,
      cashWeight: null,
      weights: [],
      reasons: ['factor_portfolio_unavailable'],
    });
  const historyMeta = run.factor_holding_histories?.[factor]
    || (factor === bestFactorName ? run.backtest_holding_history : null);
  let sessions = (historyMeta?.sessions || [])
    .filter((session) => String(session.date || '') <= String(date || '9999-99-99'))
    .sort((left, right) => String(right.date || '').localeCompare(String(left.date || '')))
    .slice(0, 21)
    .map((session) => {
      const rows = normalizeDailyActualRows(session.weights || [], {
        date: session.date,
        weight_date: session.date,
        score_date: session.lastSignalDate,
        execution_date: session.lastExecutionDate,
        execution_status: session.executionStatus,
        cash_weight: session.cashWeight,
        weight_timing: session.weightTiming,
        factor,
        weighting_policy_id: historyMeta?.weightingPolicyId,
        weight_source: historyMeta?.sourceKind === 'legacy_backtest_held_fallback'
          ? '실제 백테스트 보유 fallback'
          : '실제 백테스트 보유 이력',
        history_source: historyMeta?.sourceKind,
      });
      return {
        date: session.date,
        valuationAvailable: session.valuationAvailable !== false,
        lastSignalDate: session.lastSignalDate,
        lastExecutionDate: session.lastExecutionDate,
        executionStatus: session.executionStatus,
        cashWeight: optionalNumber(session.cashWeight) ?? 0,
        weightTiming: session.weightTiming || historyMeta?.weightTiming,
        rows,
      };
    });

  if (!sessions.length) {
    const historyRows = (run.holdings || []).filter((row) => (
      row.factor === factor
      && (!row.window || row.window === windowKey)
      && String(row.date || '') <= String(date || '9999-99-99')
    ));
    const historyDates = [...new Set(historyRows.map((row) => row.date).filter(Boolean))]
      .sort((left, right) => String(right).localeCompare(String(left)))
      .slice(0, 21);
    sessions = historyDates.map((day) => {
      const rows = normalizeDailyActualRows(historyRows.filter((row) => row.date === day));
      const first = rows[0] || {};
      return {
        date: day,
        lastSignalDate: first.scoreDate,
        lastExecutionDate: first.executionDate,
        executionStatus: first.executionStatus,
        valuationAvailable: first.valuationAvailable !== false,
        cashWeight: first.cashWeight ?? 0,
        weightTiming: first.weightTiming,
        rows,
      };
    });
  }

  const targetRows = target.factor === factor && target.status === 'available'
    ? (target.weights || []).filter((row) => row.symbol && Number.isFinite(Number(row.targetWeight)))
    : [];
  const rows = sessions.flatMap((session) => session.rows);
  return {
    rows,
    sessions,
    targetRows,
    sourceKind: historyMeta?.sourceKind || (sessions.length ? 'historical_holdings' : 'factor_history_unavailable'),
    dateCount: sessions.length,
    exactDate: sessions.some((session) => session.date === date),
    bestFactorName,
    historyMeta,
    target,
  };
}

function renderDailyWeightsAnalysis() {
  const run = currentRun();
  const date = selectedDate();
  const windowKey = selectedWindow();
  const factor = selectedFactor();
  const {
    rows,
    sessions,
    targetRows,
    sourceKind,
    dateCount,
    historyMeta,
    target,
    bestFactorName,
  } = selectedDailyWeightRows(run, date, windowKey, factor);

  const currentPortfolioSummary = target.status === 'available'
    ? `현재 입력 포트폴리오 ${formatInteger(target.selectedSecurityCount ?? targetRows.length)}종목 · 현금 ${formatPercent(target.cashWeight)}`
    : `현재 입력 포트폴리오 자료 없음${target.reasons?.length ? ` (${target.reasons.join(', ')})` : ''}`;
  setText(
    '#daily-weight-analysis-note',
    sourceKind === 'factor_history_unavailable'
      ? `${factor || '-'} · 백테스트 보유 이력 없음 · ${currentPortfolioSummary}`
      : sourceKind === 'legacy_backtest_held_fallback'
      ? `${factor || '-'} · 마지막 백테스트 보유 1개 세션 · ${currentPortfolioSummary}`
      : sessions.length
      ? `${factor || '-'} · 실제 백테스트 보유 ${dateCount}개 세션 · ${currentPortfolioSummary}`
      : `${factor || '-'} · 백테스트 보유 없음 · ${currentPortfolioSummary}`,
  );

  const table = document.querySelector('#daily-weights-table');
  const thead = document.querySelector('#daily-weights-table thead');
  const tbody = document.querySelector('#daily-weights-table tbody');
  if (!table || !thead || !tbody) return;

  renderDailyWeightsTable(thead, tbody, {
    sessions,
    targetRows,
    target,
    sourceKind,
    factor,
    bestFactorName,
  });
}

function dailyWeightSymbols(sessions, targetRows) {
  return [
    ...new Set([
      ...(sessions || []).flatMap((session) => session.rows || []).map((row) => row.symbol).filter(Boolean),
      ...(targetRows || []).map((row) => row.symbol).filter(Boolean),
    ]),
  ];
}

function renderDailyWeightsTable(thead, tbody, {
  sessions,
  targetRows,
  target,
  sourceKind,
  factor,
  bestFactorName,
}) {
  tbody.replaceChildren();
  const targetBySymbol = new Map(targetRows.map((row) => [String(row.symbol), row]));
  const symbols = dailyWeightSymbols(sessions, targetRows);
  const headerRow = document.createElement('tr');
  appendHeaderCell(headerRow, '보유 기준일');
  appendHeaderCell(headerRow, '신호일 · 체결일');
  symbols.forEach((symbol) => {
    appendHeaderCell(headerRow, `${symbol} 백테스트 보유`);
    appendHeaderCell(headerRow, `${symbol} 현재 입력 포트폴리오`);
  });
  appendHeaderCell(headerRow, '현금 백테스트 보유');
  appendHeaderCell(headerRow, '현금 현재 입력 포트폴리오');
  thead.replaceChildren(headerRow);

  if (!sessions.length) {
    const exactTarget = target?.factor === factor
      && ['available', 'unavailable'].includes(target?.status)
      && Number.isFinite(Number(target?.cashWeight));
    if (exactTarget) {
      const tr = document.createElement('tr');
      appendCell(tr, target.signalDate || target.asOf || '현재 입력 포트폴리오', { strong: true });
      appendCurrentTargetTimingCell(tr, target);
      symbols.forEach((symbol) => {
        const targetRow = target.status === 'available'
          ? (targetBySymbol.get(String(symbol)) || {
            symbol,
            targetWeight: 0,
            targetState: 'not_selected',
          })
          : null;
        appendWeightMatrixCells(tr, null, targetRow);
      });
      appendWeightMatrixCells(
        tr,
        null,
        {
          symbol: '현금',
          targetWeight: Number(target.cashWeight),
          targetState: target.status === 'unavailable' ? 'fail_closed' : 'cash',
        },
      );
      tbody.appendChild(tr);
      return;
    }
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = Math.max(symbols.length * 2 + 4, 4);
    td.textContent = `선택한 ${factor || '-'} 팩터에는 검증된 실제 보유 이력이 없습니다. 같은 팩터의 현재 입력 포트폴리오도 없어 다른 팩터 값으로 대체하지 않습니다.`;
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  sessions
    .sort((left, right) => String(right.date).localeCompare(String(left.date)))
    .forEach((session) => {
      const tr = document.createElement('tr');
      appendCell(tr, session.date);
      appendHoldingTimingCell(tr, session);
      const bySymbol = new Map(session.rows.map((row) => [String(row.symbol), row]));
      symbols.forEach((symbol) => {
        const exactTarget = targetBySymbol.get(String(symbol));
        const completeTargetRow = target.status === 'available'
          ? (exactTarget || {
            symbol,
            targetWeight: 0,
            targetState: 'not_selected',
          })
          : null;
        appendWeightMatrixCells(tr, bySymbol.get(symbol), completeTargetRow);
      });
      appendWeightMatrixCells(
        tr,
        { symbol: '현금', actualWeight: optionalNumber(session.cashWeight) ?? 0, source: '백테스트 현금' },
        ['available', 'unavailable'].includes(target.status) && Number.isFinite(Number(target.cashWeight))
          ? {
            symbol: '현금',
            targetWeight: Number(target.cashWeight),
            targetState: target.status === 'unavailable' ? 'fail_closed' : 'cash',
          }
          : null,
      );
      tbody.appendChild(tr);
    });
}

function appendCurrentTargetTimingCell(tr, target) {
  const td = document.createElement('td');
  td.className = 'holding-timing-cell';
  const signal = document.createElement('strong');
  signal.textContent = `현재 입력 포트폴리오 신호 ${target.signalDate || target.asOf || '-'}`;
  const execution = document.createElement('small');
  execution.textContent = target.status === 'unavailable'
    ? '실패-폐쇄 · 주식 0% · 현금 보존'
    : '다음 가능 세션 종가 체결 가정 · 과거 보유 아님';
  td.append(signal, execution);
  tr.appendChild(td);
}

function appendHoldingTimingCell(tr, session) {
  const td = document.createElement('td');
  td.className = 'holding-timing-cell';
  const signal = document.createElement('strong');
  signal.textContent = `신호 ${session.lastSignalDate || '-'}`;
  const execution = document.createElement('small');
  execution.textContent = `체결 ${session.lastExecutionDate || '-'} · ${humanExecutionStatus(session.executionStatus)}${session.valuationAvailable === false ? ' · 평가 불가' : ''}`;
  td.append(signal, execution);
  tr.appendChild(td);
}

function humanExecutionStatus(value) {
  const labels = {
    none: '기존 보유 유지',
    executed: '리밸런싱 체결',
    executed_partial_unpriceable_targets: '일부 종목 제외 후 체결',
    blocked_missing_held_quote: '보유종목 시세 누락으로 체결 차단',
    blocked_all_targets_unpriceable: '목표종목 전부 가격 불가로 체결 차단',
    legacy_valued_holding: '이전 결과의 평가 완료 보유',
    valuation_unavailable: '이전 결과 평가 불가',
  };
  return labels[value] || value || '체결 상태 없음';
}

function appendHeaderCell(tr, text) {
  const th = document.createElement('th');
  th.setAttribute('scope', 'col');
  th.textContent = text;
  tr.appendChild(th);
}

function appendWeightMatrixCells(tr, row, targetRow = null) {
  const actual = document.createElement('td');
  actual.className = 'weight-matrix-cell';
  if (row && row.actualWeight !== null) {
    const primary = document.createElement('strong');
    primary.textContent = formatPercent(row.actualWeight);
    const secondary = document.createElement('small');
    secondary.textContent = row.source || (row.scoreDate ? `신호일 ${row.scoreDate}` : '저장 비중');
    actual.title = `${row.symbol || ''} ${row.scoreDate ? `신호일 ${row.scoreDate}` : ''}`.trim();
    actual.append(primary, secondary);
  } else {
    actual.textContent = '-';
  }
  tr.appendChild(actual);

  const target = document.createElement('td');
  target.className = 'weight-matrix-cell';
  const targetWeight = Number(targetRow?.targetWeight);
  if (Number.isFinite(targetWeight) && targetWeight >= 0) {
    const primary = document.createElement('strong');
    primary.textContent = formatPercent(targetWeight);
    const secondary = document.createElement('small');
    const parts = [];
    if (row && row.actualWeight !== null) parts.push(`보유 대비 ${formatPercent(targetWeight - row.actualWeight)}`);
    if (Number.isFinite(Number(targetRow?.factorScore))) parts.push(`신호 ${formatNumber(targetRow.factorScore)}`);
    if (targetRow?.targetState === 'not_selected') parts.push('현재 입력 포트폴리오 미편입');
    if (targetRow?.targetState === 'fail_closed') parts.push('실패-폐쇄 현금');
    secondary.textContent = parts.join(' · ') || '현재 입력 Python 포트폴리오';
    target.append(primary, secondary);
  } else {
    target.textContent = '-';
  }
  tr.appendChild(target);
}

function parseSelectedFactorMethod(factor, option = {}) {
  const text = String(factor || '');
  const override = FACTOR_METHOD_OVERRIDES[text] || null;
  const category = humanFactorCategory(override?.category || option.category || 'unknown');
  const base = {
    category,
    formulaLabel: override?.formula || '팩터별 가격/거래량·재무 신호 산식',
    lookback: '팩터명 또는 카탈로그 정의 구간',
    skip: '팩터별 정의에 따름',
    score: override
      ? `${text} 원자료 산식은 ${override.formula}입니다. 각 종목에 같은 산식을 적용한 뒤 점수가 높은 순서로 후보를 정렬합니다.`
      : '종목별 가격 기반 신호를 계산한 뒤 값이 큰 순서로 순위를 매깁니다.',
    caveat: override
      ? `${override.description} 검증 메모: ${override.validation}`
      : option.description_ko || option.description || '세부 설명 정보가 제한적이므로 팩터명과 카테고리 기반으로 해석합니다.',
  };
  let match = text.match(/^mom_(\d+)_(\d+)$/);
  if (match) {
    const lookback = Number(match[1]);
    const skip = Number(match[2]);
    return {
      ...base,
      formulaLabel: override?.formula || `score_i = P_i(t-${skip}m) / P_i(t-${lookback + skip}m) - 1`,
      lookback: `최근 ${skip}개월을 제외한 직전 ${lookback}개월 가격 변화`,
      skip: `${skip}개월 스킵/제외`,
      score: `각 종목 i에 대해 최근 ${skip}개월을 제외한 직전 ${lookback}개월 누적수익률을 계산합니다. 즉 대략 P_i(t-${skip}m) / P_i(t-${lookback + skip}m) - 1이며, 값이 큰 종목이 상위 모멘텀 후보입니다.`,
      caveat: `${base.caveat} 최근 과열/단기 반전 오염을 줄이기 위해 가장 최근 ${skip}개월은 점수 계산 구간에서 제외합니다.`,
    };
  }
  match = text.match(/^mom_(\d+)m$/);
  if (match) {
    const lookback = Number(match[1]);
    return {
      ...base,
      formulaLabel: override?.formula || `score_i = P_i(t) / P_i(t-${lookback}m) - 1`,
      lookback: `${lookback}개월 가격 변화`,
      skip: '명시적 스킵 없음',
      score: `각 종목의 최근 ${lookback}개월 누적수익률을 계산하고 높은 순서로 정렬합니다. 원자료 산식은 조정종가 기준 가격 변화율입니다.`,
      caveat: `${base.caveat} 단순 기간 모멘텀은 빠른 추세를 직접 보지만 단기 과열과 회전율에 더 민감할 수 있습니다.`,
    };
  }
  match = text.match(/^mom_(\d+)d$/);
  if (match) {
    const days = Number(match[1]);
    return {
      ...base,
      formulaLabel: override?.formula || `score_i = P_i(t) / P_i(t-${days}d) - 1`,
      lookback: `${days}거래일`,
      skip: '명시적 스킵 없음',
      score: `최근 ${days}거래일 내외의 단기 가격 변화를 비교해 단기 모멘텀이 강한 종목을 위로 정렬합니다.`,
      caveat: `${base.caveat} 단기 모멘텀 팩터는 회전율과 반전 위험이 커서 비용/슬리피지 민감도를 함께 봐야 합니다.`,
    };
  }
  match = text.match(/^accel_(\d+)m_vs_(\d+)m$/);
  if (match) {
    return {
      ...base,
      formulaLabel: override?.formula || `${match[1]}개월 모멘텀 - ${match[2]}개월 모멘텀`,
      lookback: `${match[1]}개월과 ${match[2]}개월 수익률 비교`,
      skip: '팩터 정의의 skip 값 적용',
      score: `짧은 기간 모멘텀이 긴 기간 모멘텀보다 얼마나 개선됐는지 계산합니다. 값이 클수록 최근 리더십이 가속된 종목입니다.`,
      caveat: `${base.caveat} 가속도 계열은 추세 변화 속도를 보므로 단순 장기 모멘텀보다 노이즈에 민감할 수 있습니다.`,
    };
  }
  match = text.match(/^high_(\d+)w$/);
  if (match) {
    return {
      ...base,
      formulaLabel: override?.formula || `score_i = P_i(t) / rolling_high_${match[1]}w - 1`,
      lookback: `${match[1]}주 고점/현재가 비교`,
      skip: '명시적 스킵 없음',
      score: `현재 가격이 ${match[1]}주 고점에 얼마나 가까운지로 추세 지속성을 평가합니다. 0에 가까울수록 고점 근접도가 높습니다.`,
      caveat: `${base.caveat} 고점 근접 팩터는 강한 추세를 빠르게 포착하지만 추세 말기 변동성에 유의해야 합니다.`,
    };
  }
  match = text.match(/^breakout_(\d+)d$/);
  if (match) {
    return {
      ...base,
      formulaLabel: override?.formula || `score_i = P_i(t) / prior_high_${match[1]}d - 1 + 확인 모멘텀`,
      lookback: `${match[1]}거래일 가격 범위`,
      skip: '명시적 스킵 없음',
      score: `최근 ${match[1]}거래일 가격 범위에서 상단 돌파/근접 정도와 확인 모멘텀을 함께 평가합니다.`,
      caveat: `${base.caveat} 돌파 팩터는 추세 시작을 포착하려 하지만 false breakout과 비용 민감도가 있습니다.`,
    };
  }
  if (text.includes('winsorized') || text.includes('gap_resistant') || text.includes('jump_excluded') || text.includes('median_return')) {
    return {
      ...base,
      lookback: '주로 63~252거래일 견고화 구간',
      score: `${base.score} 급등락·단일 점프·극단 일수익률 영향을 줄이는 견고화 처리를 포함합니다.`,
      caveat: `${base.caveat} 견고화 계열은 한두 번의 급등락에 덜 끌려가지만, 실제 급격한 추세 전환을 일부 늦게 반영할 수 있습니다.`,
    };
  }
  if (text.includes('risk') || text.includes('vol') || text.includes('ulcer') || text.includes('drawdown') || text.includes('tail')) {
    return {
      ...base,
      lookback: '모멘텀 구간과 63~252거래일 위험 구간',
      score: `${base.score} 상승률을 변동성, 낙폭, 하방위험, 좌측 꼬리위험 같은 위험 지표로 보정합니다.`,
      caveat: `${base.caveat} 위험조정 계열은 단순 수익률보다 안정성을 선호하지만 강한 고변동 추세를 낮게 볼 수 있습니다.`,
    };
  }
  if (text.includes('ma_') || text.includes('trend') || text.includes('range_position') || text.includes('price_vs_ma')) {
    return {
      ...base,
      lookback: '20~252거래일 추세·이동평균·가격 범위 구간',
      score: `${base.score} 이동평균 기울기, 추세 정렬, 가격 범위 내 위치 등을 이용해 추세 품질을 평가합니다.`,
      caveat: `${base.caveat} 추세 품질 계열은 방향성과 지속성을 함께 보지만 횡보장에서는 신호가 둔화될 수 있습니다.`,
    };
  }
  if (text.includes('relative_strength') || text.includes('residual') || text.includes('excess_ir') || text.includes('up_down_capture')) {
    return {
      ...base,
      lookback: '주로 126~252거래일 횡단면/시장상대 구간',
      score: `${base.score} 동일 후보군 또는 시장 프록시 대비 초과 성과·상대 순위·상승/하락 참여도를 비교합니다.`,
      caveat: `${base.caveat} 상대강도 계열은 후보군 구성과 시장 프록시 변화에 민감하므로 단독 투자 결론보다 비교 진단으로 보세요.`,
    };
  }
  return base;
}

function appendMethodItem(target, label, value) {
  const item = document.createElement('div');
  item.className = 'method-item';
  const strong = document.createElement('strong');
  strong.textContent = label;
  const small = document.createElement('small');
  small.textContent = textValue(value);
  item.append(strong, small);
  target.appendChild(item);
}

function renderSelectedFactorMethod() {
  const run = currentRun();
  const factor = selectedFactor();
  const option = factorOptions(run).find((item) => item.factor === factor) || {};
  const method = parseSelectedFactorMethod(factor, option);
  setText('#selected-factor-method-title', factor || '-');
  setText('#selected-factor-method-badge', `${method.category} · 팩터 정의`);
  setText(
    '#selected-factor-method-summary',
    `${factor || '-'}: ${method.score}`,
  );
  const steps = document.querySelector('#selected-factor-method-steps');
  if (steps) {
    steps.replaceChildren();
    appendMethodItem(steps, '팩터 분류', method.category);
    appendMethodItem(steps, '핵심 산식', method.formulaLabel);
    appendMethodItem(steps, '관찰 구간', method.lookback);
    appendMethodItem(steps, '최근 구간 제외', method.skip);
    appendMethodItem(steps, '현재 실행 Top-N', formatInteger(state.payload?.config?.top_n));
    appendMethodItem(steps, '고정 비중 방법', fixedPolicyLabel(state.payload || {}, state.payload?.weightingPolicy));
    appendMethodItem(steps, '성과 계산', 'Python 백테스트 원자료 · 현재 실행의 리밸런싱과 거래비용 적용');
  }
  setText(
    '#selected-factor-method-note',
    method.caveat,
  );
}


const EXPLORATION_PERIODS = [
  { key: '1M', label: '최근 1개월', trading_days: 21 },
  { key: '3M', label: '최근 3개월', trading_days: 63 },
  { key: '6M', label: '최근 6개월', trading_days: 126 },
  { key: '1Y', label: '최근 1년', trading_days: 252 },
];

const BENCHMARK_LABELS = {
  SPY: 'SPY · S&P 500 ETF',
  '^IXIC': '나스닥 종합지수',
  QQQ: 'QQQ · 나스닥 100 ETF',
};

function curveValue(curve, index) {
  const value = Number(curve?.[index]);
  return Number.isFinite(value) && value > 0 ? value : null;
}

function curveReturn(curve, endIndex, tradingDays) {
  const startIndex = endIndex - tradingDays;
  if (startIndex < 0) return null;
  const start = curveValue(curve, startIndex);
  const end = curveValue(curve, endIndex);
  return start && end ? end / start - 1 : null;
}

function drawdownSeries(curve) {
  let peak = null;
  return (curve || []).map((raw) => {
    const value = Number(raw);
    if (!Number.isFinite(value) || value <= 0) return null;
    peak = peak === null ? value : Math.max(peak, value);
    return peak > 0 ? value / peak - 1 : 0;
  });
}

function pythonBenchmarkCurves(payload) {
  const performance = payload.performance || {};
  const curves = performance.benchmarkCurves && typeof performance.benchmarkCurves === 'object'
    ? { ...performance.benchmarkCurves }
    : {};
  const primary = payload.data?.benchmark || payload.config?.benchmark || 'SPY';
  if (!curves[primary] && Array.isArray(performance.benchmarkCurve)) {
    curves[primary] = performance.benchmarkCurve;
  }
  const requestedOrder = [
    primary,
    payload.data?.chartBenchmark || payload.config?.chart_benchmark,
    ...(payload.data?.additionalComparisonBenchmarks || payload.config?.additional_comparison_benchmarks || []),
    'SPY',
    '^IXIC',
    'QQQ',
  ].filter(Boolean);
  return [...new Set(requestedOrder)]
    .filter((symbol) => Array.isArray(curves[symbol]))
    .map((symbol) => ({ symbol, curve: curves[symbol] }));
}

function pythonBacktestSeries(factor, curve, dates) {
  return {
    factor,
    dates: [...dates],
    equity: [...curve],
    drawdown: drawdownSeries(curve),
  };
}

function explorationPeriodData(payload, factors, dates) {
  const curves = payload.performance?.factorCurves || {};
  const startIndex = Math.max(0, dates.length - 90);
  const factorPeriodMatrix = [];
  const factorLeaders = [];
  for (let endIndex = startIndex; endIndex < dates.length; endIndex += 1) {
    EXPLORATION_PERIODS.forEach((period) => {
      const ranked = factors
        .map((factor) => ({
          factor,
          period_return: curveReturn(curves[factor], endIndex, period.trading_days),
        }))
        .filter((row) => Number.isFinite(row.period_return))
        .sort((left, right) => right.period_return - left.period_return || left.factor.localeCompare(right.factor));
      if (!ranked.length) return;
      factorPeriodMatrix.push({
        date: dates[endIndex],
        window: period.key,
        window_label: period.label,
        factors: ranked.map((row) => row.factor),
        returns: ranked.map((row) => row.period_return),
      });
      factorLeaders.push({
        date: dates[endIndex],
        window: period.key,
        window_label: period.label,
        best_factor: ranked[0].factor,
        best_return: ranked[0].period_return,
        factor_count: ranked.length,
      });
    });
  }
  return { factorPeriodMatrix, factorLeaders };
}

function categorySummaryView(definitions) {
  const counts = new Map();
  definitions.forEach((definition) => {
    const category = definition.category || 'unknown';
    if (!counts.has(category)) counts.set(category, []);
    counts.get(category).push(definition.factor);
  });
  return [...counts.entries()]
    .map(([category, factors]) => ({
      category,
      factor_count: factors.length,
      avg_mean_rank_ic: null,
      avg_positive_ic_rate: null,
      example_factors: factors.slice(0, 3).join(', '),
    }))
    .sort((left, right) => right.factor_count - left.factor_count || left.category.localeCompare(right.category));
}

function factorDiagnosticsView(payload) {
  const diagnostics = payload.factorDiagnostics || {};
  const scope = diagnostics.scope || {};
  const rankIc = diagnostics.rankIc || {};
  const redundancy = diagnostics.redundancy || {};
  const rankRows = (rankIc.rows || []).map((row) => ({
    rank: row.rank,
    factor: row.factor,
    category: row.category,
    available: row.available === true,
    unavailable_reason: row.unavailableReason,
    horizon_days: row.horizonSessions,
    observations: row.observations,
    mean_rank_ic: optionalNumber(row.mean),
    median_rank_ic: optionalNumber(row.median),
    standard_deviation: optionalNumber(row.standardDeviation),
    positive_ic_rate: optionalNumber(row.positiveRate),
    start_date: row.startDate,
    end_date: row.endDate,
    minimum_security_count: optionalNumber(row.minimumSecurityCount),
    average_security_count: optionalNumber(row.averageSecurityCount),
    maximum_security_count: optionalNumber(row.maximumSecurityCount),
    latest_finite_count: optionalNumber(row.latestFiniteCount),
  }));
  const redundancyRows = (redundancy.rows || []).map((row) => ({
    rank: row.rank,
    factor: row.factor,
    category: row.category,
    available: row.available === true,
    unavailable_reason: row.unavailableReason,
    nearest_factor: row.nearestFactor,
    signed_rank_corr: optionalNumber(row.signedCorr),
    abs_rank_corr: optionalNumber(row.absCorr),
    valid_peer_count: optionalNumber(row.validPeerCount),
    high_corr_peer_count: optionalNumber(row.highCorrPeerCount),
    common_security_count: optionalNumber(row.commonSecurityCount),
    latest_finite_count: optionalNumber(row.latestFiniteCount),
    diagnostic_date: redundancy.diagnosticDate,
  }));
  return {
    scope_note_ko: `독립 팩터 ${formatInteger(scope.independentFactorCount)}개를 비교하며 호환 alias ${formatInteger(scope.diagnosticAliasCount)}개는 순위를 중복시키지 않도록 제외합니다. Forward Rank-IC는 신호일 t의 횡단면 순위와 ${formatInteger(rankIc.horizonSessions)}세션 후 조정종가 수익률의 Spearman 상관입니다. 최근 최대 ${formatInteger(rankIc.maximumSignalSessions)}개 신호일을 사용한 중첩 일별 동일표본 탐색 진단이므로 독립 표본 유의성이나 미래 성과 보장이 아닙니다.`,
    category_summary: (diagnostics.categorySummary || []).map((row) => ({
      category: row.category,
      factor_count: row.factorCount,
      available_rank_ic_factor_count: row.availableRankIcFactorCount,
      avg_mean_rank_ic: optionalNumber(row.averageMeanRankIc),
      avg_positive_ic_rate: optionalNumber(row.averagePositiveRate),
      avg_max_abs_rank_corr: optionalNumber(row.averageMaxAbsCorr),
      high_corr_factor_count: row.highCorrFactorCount,
      example_factors: Array.isArray(row.exampleFactors) ? row.exampleFactors.join(', ') : '-',
    })),
    rank_ic_horizon_days: rankIc.horizonSessions,
    rank_ic_requested_sessions: rankIc.requestedSignalSessions,
    rank_ic_overlapping: rankIc.overlapping === true,
    rank_ic_method: rankIc.method,
    rank_ic_rows: rankRows,
    rank_ic_top: rankRows.slice(0, 10),
    redundancy_threshold_abs: redundancy.thresholdAbs,
    redundancy_method: redundancy.method,
    redundancy_date: redundancy.diagnosticDate,
    redundancy_pair_count: redundancy.eligiblePairCount,
    redundancy_high_pair_count: redundancy.highRedundancyPairCount,
    redundancy_rows: redundancyRows,
    redundancy_top: redundancyRows.slice(0, 10),
    redundancy_pairs: (redundancy.topPairs || []).map((row) => ({
      rank: row.rank,
      left_factor: row.leftFactor,
      right_factor: row.rightFactor,
      signed_rank_corr: optionalNumber(row.signedCorr),
      abs_rank_corr: optionalNumber(row.absCorr),
      common_security_count: optionalNumber(row.commonSecurityCount),
    })),
    aliases: scope.aliases || [],
  };
}

function priceSourceCounts(payload) {
  return (payload.priceSources || []).reduce((counts, row) => {
    const source = row.price_source || 'unknown';
    counts[source] = (counts[source] || 0) + 1;
    return counts;
  }, {});
}

function sourceHealthView(payload) {
  return (payload.sourceHealth || []).map((row) => ({
    ...row,
    row_count: row.records ?? row.returned_price_symbols ?? row.requested_price_symbols ?? null,
  }));
}

function factorSelectionEligibility(payload, factors) {
  const selectedPolicy = payload.weightingPolicy;
  const selectedPolicyRows = (payload.factorRanking || []).filter((row) => (
    (row.policy_id || row.weightingPolicyId) === selectedPolicy
  ));
  const byFactor = new Map(selectedPolicyRows.map((row) => [row.factor, row]));
  const eligible = factors.filter((factor) => byFactor.get(factor)?.selection_eligible === true);
  if (eligible.length) return { eligible, byFactor };
  const canonical = factors.includes(payload.bestFactor) ? [payload.bestFactor] : [];
  return { eligible: canonical.length ? canonical : [...factors], byFactor };
}

function bytesToHex(bytes) {
  return [...new Uint8Array(bytes)].map((value) => value.toString(16).padStart(2, '0')).join('');
}

async function sha256Hex(bytes) {
  requireCondition(globalThis.crypto?.subtle, '브라우저 SHA-256 검증 기능을 사용할 수 없습니다.');
  const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes);
  return bytesToHex(digest);
}

async function canonicalSha256(value) {
  return sha256Hex(new TextEncoder().encode(canonicalString(value)));
}

async function validateIdentityDigest(identity, label) {
  const canonical = typeof identity?.canonicalKeyPartsJson === 'string'
    ? identity.canonicalKeyPartsJson
    : canonicalString(identity?.keyParts);
  const bytes = new TextEncoder().encode(canonical);
  requireCondition(
    await sha256Hex(bytes) === identity?.resultKey,
    `${label} resultKey가 canonical keyParts SHA-256과 다릅니다.`,
  );
}

async function fetchJson(url, label, reference, fetchImpl = globalThis.fetch) {
  requireCondition(typeof fetchImpl === 'function', `${label} fetch 기능을 사용할 수 없습니다.`);
  const response = await fetchImpl(url, { cache: 'no-store' });
  if (!response?.ok) throw new Error(`${label} HTTP ${response?.status ?? 'unknown'}`);
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (reference !== undefined) {
    requireCondition(isRecord(reference), `${label} artifact reference가 없습니다.`);
    requireCondition(
      bytes.byteLength === Number(reference.bytes),
      `${label} byte count가 manifest와 다릅니다.`,
    );
    requireCondition(
      await sha256Hex(bytes) === reference.sha256,
      `${label} SHA-256이 manifest와 다릅니다.`,
    );
  }
  try {
    return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
  } catch (error) {
    throw new Error(`${label} JSON이 잘못되었습니다: ${error.message}`);
  }
}

async function loadAutomationState(manifest, options = {}) {
  try {
    const defaultEntry = entryByResultKey(manifest, manifest.defaultResultKey);
    const manifestUrl = options.manifestUrl || state.manifestUrl;
    const pageUrl = options.pageUrl || window.location.href;
    const fetchImpl = options.fetchImpl || globalThis.fetch;
    requireCondition(defaultEntry && manifestUrl, '자동화 결과 대조 기준이 없습니다.');
    const [status, summary] = await Promise.all([
      fetchJson(new URL(AUTOMATION_STATUS_URL, pageUrl).href, 'automation status', undefined, fetchImpl),
      fetchJson(new URL(defaultEntry.summary.path, manifestUrl).href, 'automation summary', defaultEntry.summary, fetchImpl),
    ]);
    requireCondition(
      summary.resultKey === defaultEntry.resultKey
        && summary.dataAsOf === defaultEntry.identity.keyParts.marketSnapshot.dataAsOf
        && sameJson(summary.resultIdentity, defaultEntry.identity),
      '자동화 대조용 요약과 manifest가 일치하지 않습니다.',
    );
    const reference = {
      resultKey: summary.resultKey,
      dataAsOf: summary.dataAsOf,
      generatedAtUtc: summary.generatedAt,
      path: 'data/dashboard.json',
    };
    return { phase: 'loaded', status, reference };
  } catch (error) {
    // Failure of the operational status must not discard a validated research result.
    return { phase: 'error', status: null, reference: null };
  }
}

async function fetchLocalApiJson(path, options = {}) {
  const fetchImpl = options.fetchImpl || globalThis.fetch;
  const url = new URL(path, `${LOCAL_API_BASE_URL}/`).href;
  let response;
  try {
    response = await fetchImpl(url, {
      cache: 'no-store',
      method: options.method || 'GET',
      headers: {
        Accept: 'application/json',
        ...(options.body === undefined ? {} : { 'Content-Type': 'application/json' }),
      },
      ...(options.body === undefined ? {} : { body: canonicalString(options.body) }),
    });
  } catch (error) {
    throw new Error(`로컬 API(${LOCAL_API_BASE_URL})에 연결할 수 없습니다: ${error.message}`);
  }
  let body;
  try {
    const bytes = new Uint8Array(await response.arrayBuffer());
    body = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
  } catch (error) {
    throw new Error(`로컬 API 응답 JSON이 잘못되었습니다: ${error.message}`);
  }
  if (!response.ok) {
    const detail = body?.error?.message || `HTTP ${response.status}`;
    throw new Error(`로컬 API가 실행을 거절했습니다: ${detail}`);
  }
  return { statusCode: response.status, body };
}

function waitForPoll() {
  return new Promise((resolve) => window.setTimeout(resolve, LOCAL_API_POLL_INTERVAL_MS));
}

async function resolveLocalApiResult(submission, token, options = {}) {
  if (submission.statusCode === 200) return submission.body;
  requireCondition(
    submission.statusCode === 202
      && validSha256(submission.body?.resultKey)
      && typeof submission.body?.statusUrl === 'string',
    '로컬 API 제출 응답 계약이 잘못되었습니다.',
  );
  const fetchStatus = options.fetchStatus || ((path) => fetchLocalApiJson(path));
  const wait = options.wait || waitForPoll;
  const isCurrent = options.isCurrent || (() => token === state.loadToken);
  const onStatus = options.onStatus || ((status, resultKey) => {
    setInputStatus(`로컬 Python 분석 ${status} · ${resultKey.slice(0, 12)}…`, 'pending');
  });
  let statusUrl = submission.body.statusUrl;
  while (isCurrent()) {
    const statusResponse = await fetchStatus(statusUrl);
    const status = statusResponse.body;
    requireCondition(
      status.resultKey === submission.body.resultKey,
      '로컬 API status resultKey가 제출 결과와 다릅니다.',
    );
    if (status.status === 'complete') {
      requireCondition(isRecord(status.result), '완료된 로컬 API status에 canonical 결과가 없습니다.');
      return status.result;
    }
    if (status.status === 'failed') {
      throw new Error(`로컬 Python 분석 실패: ${status.error?.message || '원인 미표기'}`);
    }
    requireCondition(
      status.status === 'queued' || status.status === 'running',
      '로컬 API job status가 잘못되었습니다.',
    );
    onStatus(status.status, submission.body.resultKey);
    await wait();
    statusUrl = status.statusUrl || statusUrl;
  }
  throw new Error('다른 결과 로드가 시작되어 로컬 API 표시를 취소했습니다.');
}

function normalizeControlApiBase(value) {
  const text = String(value || '').trim();
  if (!text) return null;
  let parsed;
  try {
    parsed = new URL(text);
  } catch (error) {
    throw new Error('원격 API 주소가 올바른 URL이 아닙니다.');
  }
  requireCondition(!parsed.username && !parsed.password, '원격 API 주소에 인증정보를 넣을 수 없습니다.');
  requireCondition(!parsed.search && !parsed.hash, '원격 API 주소에 쿼리나 fragment를 넣을 수 없습니다.');
  const loopback = parsed.hostname === 'localhost'
    || parsed.hostname === '127.0.0.1'
    || parsed.hostname === '::1';
  requireCondition(
    parsed.protocol === 'https:' || (parsed.protocol === 'http:' && loopback),
    '원격 API는 HTTPS여야 합니다.',
  );
  return parsed.href.replace(/\/+$/, '');
}

function isLoopbackOrFilePreview(locationLike = globalThis.location) {
  const protocol = String(locationLike?.protocol || '').toLowerCase();
  const hostname = String(locationLike?.hostname || '').toLowerCase();
  return protocol === 'file:'
    || hostname === 'localhost'
    || hostname === '127.0.0.1'
    || hostname === '::1';
}

function analysisExecutionRoute(controlApiBase, locationLike = globalThis.location) {
  if (controlApiBase) return 'remote';
  return isLoopbackOrFilePreview(locationLike) ? 'local' : 'blocked';
}

function configuredControlApiBase() {
  if (isLoopbackOrFilePreview(window.location)) return null;
  return normalizeControlApiBase(
    document.querySelector?.('meta[name="quant-run-api-base"]')?.content || '',
  );
}

function normalizeControlCapabilities(value) {
  requireCondition(isRecord(value), '원격 API capabilities가 객체가 아닙니다.');
  requireCondition(value.projectId === CONTROL_PROJECT_ID, '원격 API projectId가 다릅니다.');
  requireCondition(
    value.inputSchemaVersion === CONTROL_INPUT_SCHEMA_VERSION,
    '원격 API 입력 schema version이 다릅니다.',
  );
  requireCondition(validSha256(value.inputSchemaHash), '원격 API 입력 schema hash가 잘못되었습니다.');
  requireCondition(
    value.configHashAlgorithm === CONTROL_CONFIG_HASH_ALGORITHM,
    '원격 API config hash algorithm이 다릅니다.',
  );
  requireCondition(value.acceptsRuns === true, '원격 API가 새 분석 실행을 받지 않습니다.');
  const inputKeys = Array.isArray(value.inputs) ? value.inputs.map((field) => field?.key) : [];
  requireCondition(
    inputKeys.length === 26
      && new Set(inputKeys).size === 26
      && sameJson([...inputKeys].sort(), CONTROL_INPUT_KEYS),
    '원격 API가 26개 ResearchInputs 전체를 선언하지 않았습니다.',
  );
  return cloneJson(value);
}

function buildControlRunSubmission(normalizedInputs) {
  return {
    inputSchemaVersion: CONTROL_INPUT_SCHEMA_VERSION,
    inputs: controlRunInputsFromNormalizedInputs(normalizedInputs),
    allowFallback: false,
  };
}

function normalizeControlRunEnvelope(value, expected, capabilities) {
  requireCondition(isRecord(value), '원격 실행 응답이 객체가 아닙니다.');
  requireCondition(value.projectId === CONTROL_PROJECT_ID, '원격 실행 projectId가 다릅니다.');
  requireCondition(requiredText(value.runId), '원격 실행 runId가 없습니다.');
  requireCondition(CONTROL_RUN_STATUSES.includes(value.status), '지원하지 않는 원격 실행 상태입니다.');
  requireCondition(
    value.inputSchemaVersion === capabilities.inputSchemaVersion,
    '원격 실행 inputSchemaVersion이 다릅니다.',
  );
  requireCondition(
    value.inputSchemaHash === capabilities.inputSchemaHash,
    '원격 실행 inputSchemaHash가 다릅니다.',
  );
  requireCondition(
    value.configHashAlgorithm === capabilities.configHashAlgorithm,
    '원격 실행 configHashAlgorithm이 다릅니다.',
  );
  requireCondition(validSha256(value.configHash), '원격 실행 configHash가 잘못되었습니다.');
  requireCondition(
    validSha256(value.effectiveConfigHash)
      && value.effectiveConfigHash === value.configHash,
    'fallback 없는 원격 실행의 effectiveConfigHash가 다릅니다.',
  );
  requireCondition(value.allowFallback === false, '원격 실행이 허용하지 않은 fallback을 요청했습니다.');
  requireCondition(
    Array.isArray(value.ignoredInputs) && value.ignoredInputs.length === 0,
    '원격 실행이 입력을 무시했습니다.',
  );
  requireCondition(
    Array.isArray(value.fallbacks)
      && value.fallbacks.length === 0
      && value.fallbackUsed === false
      && (value.fallbackReason === null || value.fallbackReason === undefined),
    '원격 실행이 허용하지 않은 fallback을 사용했습니다.',
  );
  const expectedInputs = expected.inputs || expected.normalizedInputs;
  requireCondition(isRecord(expectedInputs), '원격 실행의 기대 입력이 없습니다.');
  ['requestedInputs', 'normalizedInputs', 'effectiveInputs'].forEach((field) => {
    requireCondition(
      isRecord(value[field]) && sameJson(value[field], expectedInputs),
      `원격 실행 ${field}가 요청한 26개 입력과 다릅니다.`,
    );
  });
  if (expected.runId) {
    requireCondition(value.runId === expected.runId, '원격 실행 runId가 바뀌었습니다.');
    ['configHash', 'effectiveConfigHash'].forEach((field) => requireCondition(
      value[field] === expected[field],
      `원격 실행 ${field}가 바뀌었습니다.`,
    ));
    const progress = ['queued', 'dispatched', 'running', 'validating', 'published'];
    const previousIndex = progress.indexOf(expected.status);
    const nextIndex = progress.indexOf(value.status);
    const validTransition = (
      (previousIndex >= 0 && nextIndex >= previousIndex)
      || (previousIndex >= 0 && ['failed', 'cancelled'].includes(value.status))
      || expected.status === value.status
    );
    requireCondition(validTransition, '원격 실행 상태가 이전 단계로 되돌아갔습니다.');
  }
  return cloneJson(value);
}

async function fetchControlApiJson(path, options = {}) {
  const fetchImpl = options.fetchImpl || globalThis.fetch;
  const base = options.base || state.controlApiBase;
  requireCondition(base, '원격 API가 설정되지 않았습니다.');
  const url = new URL(path.replace(/^\//, ''), `${base}/`).href;
  const headers = { Accept: 'application/json' };
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (options.token) headers.Authorization = `Bearer ${options.token}`;
  Object.entries(options.headers || {}).forEach(([key, value]) => {
    headers[key] = value;
  });
  let response;
  try {
    response = await fetchImpl(url, {
      cache: 'no-store',
      method: options.method || 'GET',
      headers,
      ...(options.body === undefined ? {} : { body: canonicalString(options.body) }),
    });
  } catch (error) {
    throw new Error(`원격 API에 연결할 수 없습니다: ${error.message}`);
  }
  let body;
  try {
    body = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(
      new Uint8Array(await response.arrayBuffer()),
    ));
  } catch (error) {
    throw new Error(`원격 API 응답 JSON이 잘못되었습니다: ${error.message}`);
  }
  if (!response.ok) {
    throw new Error(body?.error?.message || `원격 API HTTP ${response.status}`);
  }
  return { statusCode: response.status, body };
}

function controlRunStatusText(status) {
  const labels = {
    queued: '대기',
    dispatched: '작업 전달',
    running: '분석 중',
    validating: '결과 검증 중',
    published: '검증 완료',
    failed: '실패',
    cancelled: '취소',
  };
  return labels[status] || status;
}

function controlIdempotencyKey() {
  if (globalThis.crypto?.randomUUID) return `momentum-${globalThis.crypto.randomUUID()}`;
  return `momentum-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function waitForControlPoll() {
  return new Promise((resolve) => window.setTimeout(resolve, CONTROL_API_POLL_INTERVAL_MS));
}

async function resolveControlRun(submission, loadToken, options = {}) {
  const capabilities = options.capabilities || state.controlCapabilities;
  const fetchStatus = options.fetchStatus || ((runId) => (
    fetchControlApiJson(`/v1/runs/${encodeURIComponent(runId)}`)
  ));
  const fetchResult = options.fetchResult || ((runId) => (
    fetchControlApiJson(`/v1/runs/${encodeURIComponent(runId)}/result`)
  ));
  const wait = options.wait || waitForControlPoll;
  const isCurrent = options.isCurrent || (() => loadToken === state.loadToken);
  let current = normalizeControlRunEnvelope(submission, {
    inputs: submission.requestedInputs,
  }, capabilities);
  for (let pollCount = 0; pollCount <= CONTROL_API_MAX_POLLS && isCurrent(); pollCount += 1) {
    state.pendingControlRun = current;
    setInputStatus(
      `원격 Python 분석 ${controlRunStatusText(current.status)} · 현재 결과는 유지합니다.`,
      current.status === 'failed' || current.status === 'cancelled' ? 'error' : 'pending',
    );
    if (current.status === 'published') {
      const resultResponse = await fetchResult(current.runId);
      return normalizeControlRunEnvelope(resultResponse.body, current, capabilities);
    }
    if (current.status === 'failed' || current.status === 'cancelled') {
      throw new Error(
        `원격 Python 분석 ${controlRunStatusText(current.status)}: `
        + `${current.errorMessage || current.errorCode || '원인 미표기'}`,
      );
    }
    if (pollCount === CONTROL_API_MAX_POLLS) {
      throw new Error('원격 분석 상태 확인 시간이 초과되었습니다.');
    }
    await wait();
    const statusResponse = await fetchStatus(current.runId);
    current = normalizeControlRunEnvelope(statusResponse.body, current, capabilities);
  }
  throw new Error('다른 결과 로드가 시작되어 원격 분석 표시를 취소했습니다.');
}

async function fetchVerifiedControlArtifact(resultEnvelope, options = {}) {
  const artifact = resultEnvelope.artifact;
  requireCondition(
    /^github:SonChangGi\/(?:factor|momentum-factor-lab)@[0-9a-f]{40}$/.test(resultEnvelope.codeVersion || ''),
    '원격 결과 codeVersion이 허용된 Momentum commit 형식이 아닙니다.',
  );
  requireCondition(requiredText(resultEnvelope.calculatedAt), '원격 결과 calculatedAt이 없습니다.');
  requireCondition(
    isRecord(artifact)
      && typeof artifact.url === 'string'
      && validSha256(artifact.sha256)
      && nonnegativeInteger(artifact.byteSize)
      && artifact.contractVersion === CONTROL_ARTIFACT_CONTRACT_VERSION,
    '원격 결과 artifact identity가 잘못되었습니다.',
  );
  const resultKey = resultEnvelope.payload?.resultKey;
  const runId = resultEnvelope.runId;
  requireCondition(validSha256(resultKey), '원격 결과 요약 resultKey가 잘못되었습니다.');
  requireCondition(
    /^[A-Za-z0-9][A-Za-z0-9._-]{7,127}$/.test(runId || ''),
    '원격 결과 runId가 안전한 artifact 경로 형식이 아닙니다.',
  );
  const expectedArtifactUrl = (
    `https://sonchanggi.github.io/factor/data/control-runs/v1/`
    + `${runId}/${resultKey}.json`
  );
  requireCondition(
    artifact.url === expectedArtifactUrl,
    '원격 결과 artifact URL이 동일 runId와 resultKey의 허용된 Pages 경로가 아닙니다.',
  );
  const fetchImpl = options.fetchImpl || globalThis.fetch;
  const response = await fetchImpl(expectedArtifactUrl, {
    cache: 'no-store',
    credentials: 'omit',
    referrerPolicy: 'no-referrer',
    redirect: 'error',
  });
  requireCondition(response?.ok, `원격 결과 artifact HTTP ${response?.status ?? 'unknown'}`);
  const bytes = new Uint8Array(await response.arrayBuffer());
  requireCondition(bytes.byteLength === artifact.byteSize, '원격 결과 artifact byte 수가 다릅니다.');
  requireCondition(await sha256Hex(bytes) === artifact.sha256, '원격 결과 artifact SHA-256이 다릅니다.');
  let payload;
  try {
    payload = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
  } catch (error) {
    throw new Error(`원격 결과 artifact JSON이 잘못되었습니다: ${error.message}`);
  }
  const sourceHash = await sha256Hex(new TextEncoder().encode(
    canonicalString(payload?.data?.inputSha256),
  ));
  requireCondition(
    isRecord(resultEnvelope.dataIdentity)
      && requiredText(resultEnvelope.dataIdentity.source)
      && resultEnvelope.dataIdentity.dataAsOf === payload?.data?.asOf
      && resultEnvelope.dataAsOf === payload?.data?.asOf
      && resultEnvelope.dataIdentity.sourceHash === sourceHash,
    '원격 결과 data identity가 artifact와 다릅니다.',
  );
  requireCondition(
    resultEnvelope.calculatedAt === payload?.generatedAtUtc
      && resultEnvelope.payload?.schemaVersion === payload?.schemaVersion
      && resultEnvelope.payload?.resultKey === payload?.resultKey
      && sameJson(resultEnvelope.payload?.researchInputs, payload?.researchInputs)
      && sameJson(resultEnvelope.payload?.dataIdentity, resultEnvelope.dataIdentity),
    '원격 결과 요약과 artifact binding이 다릅니다.',
  );
  return payload;
}

async function initializeControlApi(options = {}) {
  let base;
  try {
    base = options.base === undefined
      ? configuredControlApiBase()
      : normalizeControlApiBase(options.base);
  } catch (error) {
    state.controlApiBase = null;
    state.controlCapabilities = null;
    state.controlApiError = error.message;
    setInputStatus(`원격 API 설정을 사용할 수 없습니다. 현재 정적 결과를 유지합니다. ${error.message}`, 'error');
    return null;
  }
  if (!base) return null;
  state.controlApiBase = base;
  state.controlApiError = null;
  const connection = document.querySelector('#remote-control-connection');
  const localNote = document.querySelector('#local-api-note');
  const mode = document.querySelector('#remote-control-mode');
  if (connection) connection.hidden = false;
  if (localNote) localNote.hidden = true;
  try {
    const response = await fetchControlApiJson(
      `/v1/projects/${CONTROL_PROJECT_ID}/capabilities`,
      { base, fetchImpl: options.fetchImpl },
    );
    state.controlCapabilities = normalizeControlCapabilities(response.body);
    if (mode) mode.textContent = '원격 API 연결';
    return state.controlCapabilities;
  } catch (error) {
    state.controlCapabilities = null;
    state.controlApiError = error.message;
    if (mode) mode.textContent = '원격 API 오류';
    setInputStatus(`원격 API를 사용할 수 없습니다. 현재 정적 결과를 유지합니다. ${error.message}`, 'error');
    return null;
  }
}

async function loadFactorHoldingHistorySidecar(
  payload,
  fetchImpl = globalThis.fetch,
  baseUrl = null,
) {
  const manifest = validateFactorHoldingHistorySidecarManifest(payload);
  if (manifest.storage === 'embedded') {
    requireCondition(globalThis.crypto?.subtle, '팩터별 보유 이력 sidecar SHA-256을 검증할 수 없습니다.');
    const encoded = new TextEncoder().encode(canonicalString(manifest.data));
    requireCondition(
      encoded.byteLength === manifest.bytes,
      '팩터별 보유 이력 embedded sidecar 크기가 manifest와 다릅니다.',
    );
    requireCondition(
      await sha256Hex(encoded) === manifest.sha256,
      '팩터별 보유 이력 embedded sidecar SHA-256이 manifest와 다릅니다.',
    );
    return validateFactorHoldingHistorySidecarData(payload, manifest.data);
  }
  requireCondition(
    manifest.storage === 'external' && requiredText(manifest.path) && typeof fetchImpl === 'function',
    '팩터별 보유 이력 external sidecar loader 계약이 잘못되었습니다.',
  );

  const requestUrl = baseUrl ? new URL(manifest.path, baseUrl).href : manifest.path;
  const response = await fetchImpl(requestUrl, { cache: 'no-store' });
  if (!response?.ok) throw new Error('팩터별 실제 보유 이력 sidecar를 불러오지 못했습니다.');
  const encoded = await response.arrayBuffer();
  if (encoded.byteLength !== Number(manifest.bytes)) {
    throw new Error('팩터별 실제 보유 이력 sidecar 크기가 manifest와 다릅니다.');
  }
  if (!globalThis.crypto?.subtle) {
    throw new Error('팩터별 실제 보유 이력 sidecar SHA-256을 검증할 수 없습니다.');
  }
  const digest = bytesToHex(await globalThis.crypto.subtle.digest('SHA-256', encoded));
  if (digest !== manifest.sha256) {
    throw new Error('팩터별 실제 보유 이력 sidecar SHA-256이 manifest와 다릅니다.');
  }
  const data = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(encoded));
  if (
    data?.contract !== manifest.contract
    || data?.contractVersion !== manifest.contractVersion
    || data?.resultKey !== payload.resultKey
    || data?.weightingPolicy !== payload.weightingPolicy
  ) {
    throw new Error('팩터별 실제 보유 이력 sidecar provenance가 현재 결과와 다릅니다.');
  }
  return validateFactorHoldingHistorySidecarData(payload, data);
}

async function attachFactorHoldingHistorySidecar(payload, options = {}) {
  try {
    payload.__factorHoldingHistorySidecarData = await loadFactorHoldingHistorySidecar(
      payload,
      options.fetchImpl || globalThis.fetch,
      options.pageUrl || null,
    );
    payload.__factorHoldingHistorySidecarError = null;
  } catch (error) {
    payload.__factorHoldingHistorySidecarData = null;
    payload.__factorHoldingHistorySidecarError = String(error?.message || error);
  }
  return payload;
}

async function loadStaticEntryData(entry, options = {}) {
  const manifestUrl = options.manifestUrl || state.manifestUrl;
  const fetchImpl = options.fetchImpl || globalThis.fetch;
  requireCondition(manifestUrl, '정적 grid manifest URL이 없습니다.');
  const detailUrl = new URL(entry.detail.path, manifestUrl).href;
  const summaryUrl = new URL(entry.summary.path, manifestUrl).href;
  const [payload, summary] = await Promise.all([
    fetchJson(detailUrl, 'detail', entry.detail, fetchImpl),
    fetchJson(summaryUrl, 'summary', entry.summary, fetchImpl),
  ]);
  await validateIdentityDigest(entry.identity, 'manifest/detail/summary');
  const selected = await validateResult(entry, payload, summary);
  await attachFactorHoldingHistorySidecar(payload, {
    fetchImpl,
    pageUrl: options.pageUrl || (typeof window !== 'undefined' ? window.location.href : null),
  });
  return { payload, summary, selected, detailUrl, summaryUrl };
}

function factorHoldingHistoryView(payload, factor) {
  const sidecar = payload.__factorHoldingHistorySidecarData
    || payload.factorHoldingHistorySidecar?.data;
  const factorHistory = sidecar?.factors?.[factor];
  const dates = Array.isArray(sidecar?.dates) ? sidecar.dates : [];
  const symbols = Array.isArray(sidecar?.symbols) ? sidecar.symbols : [];
  if (
    !factorHistory
    || factorHistory.factor !== factor
    || factorHistory.weightingPolicyId !== payload.weightingPolicy
    || factorHistory.resultKey !== payload.resultKey
    || !Array.isArray(factorHistory.sessions)
    || factorHistory.sessions.length !== dates.length
  ) return null;

  const sessions = factorHistory.sessions.map((session, sessionIndex) => ({
    date: dates[sessionIndex],
    valuationAvailable: session.valuationAvailable === true,
    cashWeight: optionalNumber(session.cashWeight) ?? 0,
    executionStatus: session.executionStatus || null,
    lastSignalDate: session.lastSignalDate || null,
    lastExecutionDate: session.lastExecutionDate || null,
    weightTiming: sidecar.weightTiming,
    weights: (session.weights || []).map((pair, rank) => {
      const dictionaryRow = symbols[pair?.[0]];
      return {
        rank: rank + 1,
        symbol: dictionaryRow?.[0],
        name: dictionaryRow?.[1],
        weight: Number(pair?.[1]),
      };
    }).filter((row) => row.symbol && row.name && Number.isFinite(row.weight) && row.weight > 0),
  }));
  const rows = sessions.flatMap((session) => session.weights.map((row) => ({
    date: session.date,
    weight_date: session.date,
    score_date: session.lastSignalDate,
    execution_date: session.lastExecutionDate,
    execution_status: session.executionStatus,
    valuation_available: session.valuationAvailable,
    cash_weight: session.cashWeight,
    weight_timing: sidecar.weightTiming,
    factor,
    weighting_policy_id: factorHistory.weightingPolicyId,
    rank: row.rank,
    symbol: row.symbol,
    name: row.name,
    weight: row.weight,
    default_weight: row.weight,
    score: null,
    weight_source: '실제 백테스트 보유 이력 sidecar',
    history_source: 'factor_backtest_holding_history_sidecar',
  })));
  return {
    contractVersion: sidecar.contractVersion,
    factor,
    weightingPolicyId: factorHistory.weightingPolicyId,
    weightTiming: sidecar.weightTiming,
    sourceKind: 'factor_backtest_holding_history_sidecar',
    startDate: sidecar.startDate,
    endDate: sidecar.endDate,
    sessionCount: sessions.length,
    sessions,
    rows,
  };
}

function bestFactorHoldingHistoryView(payload, asOf) {
  const history = payload.bestFactorBacktestHoldingHistory;
  const historyObject = history && !Array.isArray(history) ? history : {};
  let sessions = Array.isArray(history)
    ? history
    : (Array.isArray(historyObject.sessions) ? historyObject.sessions : []);
  let sourceKind = 'selected_backtest_holding_history';
  let factor = historyObject.factor || payload.bestFactor;
  let policy = historyObject.weightingPolicyId || payload.weightingPolicy;
  let weightTiming = historyObject.weightTiming || 'last_complete_close_after_execution_processing';

  if (!sessions.length) {
    const held = payload.backtestHeldPortfolio;
    if (held && Array.isArray(held.weights)) {
      sessions = [{
        date: held.asOf || asOf,
        valuationAvailable: held.valuationAvailable !== false,
        lastSignalDate: held.lastSignalDate,
        lastExecutionDate: held.lastExecutionDate,
        executionStatus: held.valuationAvailable === false ? 'valuation_unavailable' : 'legacy_valued_holding',
        cashWeight: held.cashWeight,
        weights: held.weights,
      }];
      sourceKind = 'legacy_backtest_held_fallback';
      factor = held.factor || factor;
      policy = held.weightingPolicyId || policy;
    }
  }

  const normalizedSessions = sessions
    .map((session) => {
      const date = session.date || session.asOf || session.valuationDate || session.weightDate;
      const normalizedWeights = (session.weights || session.holdings || [])
        .map((row, index) => ({
          rank: row.rank || index + 1,
          symbol: row.symbol,
          name: row.name,
          weight: Number(row.weight),
          factorScore: optionalNumber(row.factorScore ?? row.score),
        }))
        .filter((row) => row.symbol && Number.isFinite(row.weight) && row.weight > 0)
        .sort((left, right) => Number(left.rank) - Number(right.rank) || String(left.symbol).localeCompare(String(right.symbol)));
      return {
        date,
        valuationAvailable: session.valuationAvailable !== false,
        lastSignalDate: session.lastSignalDate || session.signalDate || null,
        lastExecutionDate: session.lastExecutionDate || session.executionDate || null,
        executionStatus: session.executionStatus || null,
        cashWeight: optionalNumber(session.cashWeight) ?? 0,
        weightTiming: session.weightTiming || weightTiming,
        weights: normalizedWeights,
      };
    })
    .filter((session) => session.date)
    .sort((left, right) => String(right.date).localeCompare(String(left.date)))
    .slice(0, 21);

  const rows = normalizedSessions.flatMap((session) => session.weights.map((row) => ({
    date: session.date,
    weight_date: session.date,
    score_date: session.lastSignalDate,
    execution_date: session.lastExecutionDate,
    execution_status: session.executionStatus,
    valuation_available: session.valuationAvailable,
    cash_weight: session.cashWeight,
    weight_timing: session.weightTiming,
    factor,
    weighting_policy_id: policy,
    rank: row.rank,
    symbol: row.symbol,
    name: row.name,
    weight: row.weight,
    default_weight: row.weight,
    score: row.factorScore,
    weight_source: sourceKind === 'legacy_backtest_held_fallback'
      ? '실제 백테스트 보유 fallback'
      : '실제 백테스트 보유 이력',
    history_source: sourceKind,
  })));

  return {
    contractVersion: historyObject.contractVersion || (sourceKind === 'legacy_backtest_held_fallback' ? 'legacy' : 1),
    factor,
    weightingPolicyId: policy,
    weightTiming,
    sourceKind,
    startDate: historyObject.startDate || normalizedSessions.at(-1)?.date || null,
    endDate: historyObject.endDate || normalizedSessions[0]?.date || null,
    sessionCount: normalizedSessions.length,
    sessions: normalizedSessions,
    rows,
  };
}

function portfolioViewFromPython(portfolio, factor, asOf, selectedPolicy) {
  const target = portfolio || {};
  return {
    factor,
    weightingPolicyId: target.weightingPolicyId || selectedPolicy,
    status: target.status,
    signalDate: target.signalDate || asOf,
    asOf: target.asOf || asOf,
    selectedSecurityCount: optionalNumber(target.selectedSecurityCount) ?? 0,
    eligibleSecurityCount: optionalNumber(target.eligibleSecurityCount),
    cashWeight: optionalNumber(target.cashWeight) ?? 0,
    concentration: isRecord(target.concentration) ? { ...target.concentration } : null,
    reasons: Array.isArray(target.reasons) ? [...target.reasons] : [],
    weights: (target.weights || []).map((row, index) => ({
      rank: row.rank || index + 1,
      symbol: row.symbol,
      name: row.name,
      targetWeight: Number(row.weight),
      factorScore: optionalNumber(row.factorScore),
    })).filter((row) => row.symbol && Number.isFinite(row.targetWeight) && row.targetWeight > 0),
  };
}

function bestFactorPortfolioView(payload, asOf) {
  return portfolioViewFromPython(
    payload.bestFactorPortfolio,
    payload.bestFactor,
    asOf,
    payload.weightingPolicy,
  );
}

function adaptSchemaV5Payload(payload) {
  const performance = payload.performance || {};
  const dates = Array.isArray(performance.dates) ? performance.dates : [];
  const commonEvaluationPeriod = commonEvaluationPeriodFromPayload(payload);
  const definitions = Array.isArray(payload.factorDefinitions) ? payload.factorDefinitions : [];
  const definitionByFactor = new Map(definitions.map((definition) => [definition.factor, definition]));
  const factorCurves = performance.factorCurves || {};
  const factors = Object.keys(factorCurves)
    .filter((factor) => Array.isArray(factorCurves[factor]) && factorCurves[factor].length === dates.length)
    .sort();
  const { byFactor: selectionEligibilityByFactor } = factorSelectionEligibility(payload, factors);
  const asOf = payload.data?.asOf || dates.at(-1) || '-';
  const target = payload.bestFactorPortfolio || {};
  const holdingHistory = bestFactorHoldingHistoryView(payload, asOf);
  const factorHoldingHistories = {};
  factors.forEach((factor) => {
    const history = factorHoldingHistoryView(payload, factor);
    if (history) factorHoldingHistories[factor] = history;
  });
  factorHoldingHistories[payload.bestFactor] = holdingHistory;
  const portfolios = payload.factorPortfolios || {};
  const factorPortfolioViews = Object.fromEntries(factors.map((factor) => [
    factor,
    portfolioViewFromPython(
      portfolios[factor],
      factor,
      asOf,
      payload.weightingPolicy,
    ),
  ]));
  const bestFactorPortfolio = factorPortfolioViews[payload.bestFactor]
    || bestFactorPortfolioView(payload, asOf);
  const holdings = holdingHistory.rows;

  const benchmarkSeries = pythonBenchmarkCurves(payload).map(({ symbol, curve }) => ({
    symbol,
    label_ko: BENCHMARK_LABELS[symbol] || symbol,
    dates: [...dates],
    equity: [...curve],
    drawdown: drawdownSeries(curve),
  }));
  const legacyBenchmark = benchmarkSeries.find((series) => series.symbol === '^IXIC')
    || benchmarkSeries.find((series) => series.symbol === 'SPY')
    || benchmarkSeries[0]
    || null;
  const latestWeights = Array.isArray(target.weights) ? target.weights : [];
  const investedWeight = latestWeights.reduce((sum, row) => sum + (Number(row.weight) || 0), 0);
  const selectedDefinition = definitionByFactor.get(payload.bestFactor) || {};
  const qualityRows = Array.isArray(payload.quality) ? payload.quality : [];
  const candidateQualityRows = qualityRows.filter((row) => row?.role === 'candidate');
  const freshCandidateRows = candidateQualityRows.filter((row) => String(row?.last_date || '') === String(asOf));
  const freshPriceRatio = candidateQualityRows.length
    ? freshCandidateRows.length / candidateQualityRows.length
    : null;
  const selectedPolicy = payload.weightingMethodology?.policy || {};
  const summary = {
    run_timestamp_utc: payload.generatedAtUtc,
    data_as_of: asOf,
    provider: payload.data?.provider || payload.data?.sourceLabel,
    selected_factor: payload.bestFactor,
    selected_reason: payload.bestFactorReason,
    recommendation_status: 'current_live_with_limitations_research_only',
    recommendation_output_label: 'Research signals (not tradable)',
    fresh_live_data_available: payload.data?.mode === 'live_market',
    decision_support_tier: 'research_signals',
    execution_limitations: ['research_only', 'not_investment_recommendation', ...(payload.researchScope?.limitations || [])],
    tradability_blockers: ['research_only', 'not_investment_recommendation'],
    default_top_n: payload.config?.top_n || 20,
    default_max_weight: payload.config?.max_weight || 0.1,
    benchmark: payload.data?.benchmark || payload.config?.benchmark || 'SPY',
    chart_benchmark: payload.data?.chartBenchmark || payload.config?.chart_benchmark || '^IXIC',
    chart_benchmark_symbol: payload.data?.chartBenchmark || payload.config?.chart_benchmark || '^IXIC',
    chart_benchmark_price_available: benchmarkSeries.some((series) => series.symbol === '^IXIC'),
    universe_profile: payload.config?.universe_profile || 'large_liquid',
    factor_selection_mode: 'fixed_policy_factor_selection',
    candidate_universe_size: payload.data?.requestedCandidateCount,
    eligible_price_universe_size: payload.data?.analyzedSecurityCount,
    liquidity_eligible_universe_size: payload.data?.latestEligibleSecurityCount,
    factor_count: factors.length,
    factor_library_scope: 'price_momentum_only',
    recommendation_output_key: 'research_signals',
    recommendation_output_available: false,
    tradable_output_available: false,
    current_recommendations_available: false,
    tradable_recommendations_available: false,
    research_only: true,
    fail_closed: true,
    fail_closed_reasons: ['research_only', 'not_investment_recommendation'],
    same_run_factor_selection_blocked_for_tradable: true,
    same_sample_selection_blocked_for_tradable: true,
    recommendation_weighting_method: payload.weightingPolicy,
    recommendation_weight_sum: investedWeight,
    recommendation_cash_weight: Number(target.cashWeight) || 0,
    validation_selected_factor: payload.bestFactor,
    selected_factor_selection_source: 'python_fixed_policy_factor_ranking',
    selected_policy_label: selectedPolicy.label || payload.weightingPolicy,
  };

  const priceCounts = priceSourceCounts(payload);
  const run = {
    schema_version: 5,
    generated_at_utc: payload.generatedAtUtc,
    source_json: 'schema-v5 input-driven Python result',
    summary,
    periods: EXPLORATION_PERIODS,
    factor_options: factors.map((factor) => {
      const definition = definitionByFactor.get(factor) || {};
      return {
        factor,
        category: definition.category || 'unknown',
        description: definition.description || '팩터 설명 정보가 없습니다.',
        description_ko: definition.description || '팩터 설명 정보가 없습니다.',
        formula: definition.formula,
        validation: definition.validation_notes,
        selection_eligible: selectionEligibilityByFactor.get(factor)?.selection_eligible === true,
        selection_status: selectionEligibilityByFactor.get(factor)?.selection_status || 'diagnostic_only',
      };
    }),
    factor_backtest_series: factors.map((factor) => pythonBacktestSeries(factor, factorCurves[factor], dates)),
    benchmark_backtest_series: legacyBenchmark,
    comparison_benchmark_series: benchmarkSeries,
    common_evaluation_period: commonEvaluationPeriod,
    holdings,
    backtest_holding_history: holdingHistory,
    backtest_holding_sessions: holdingHistory.sessions,
    factor_holding_histories: factorHoldingHistories,
    best_factor_portfolio: bestFactorPortfolio,
    factor_portfolios: factorPortfolioViews,
    history_payload_type: 'full',
    history_compaction_note_ko: null,
    tradability_gate: [
      { key: 'actual_market', passed: payload.data?.mode === 'live_market', label_ko: '실제 시장 데이터', description_ko: '합성 데이터가 아닌 제공자 조정가격을 사용합니다.' },
      { key: 'broad_universe', passed: Number(payload.data?.analyzedSecurityCount) >= 2700, label_ko: '2,700개 이상 전체 후보 분석', description_ko: `${formatInteger(payload.data?.analyzedSecurityCount)}개 종목을 분석했습니다.` },
      { key: 'best_factor_portfolio', passed: target.status === 'available', label_ko: '동일 입력 최고 팩터 포트폴리오', description_ko: `${payload.bestFactor} · 고정 비중 방법` },
      { key: 'research_only', passed: false, label_ko: '매매 권고 게이트', description_ko: '동일 표본 설명 연구이며 실제 주문·투자 권고가 아닙니다.' },
    ],
    data_quality_summary: {
      candidate_universe_size: payload.data?.requestedCandidateCount,
      eligible_price_universe_size: payload.data?.analyzedSecurityCount,
      liquidity_eligible_universe_size: payload.data?.latestEligibleSecurityCount,
      fetched_price_symbol_count: payload.data?.providerReturnedCandidateCount,
      excluded_symbols: Math.max(0, Number(payload.data?.requestedCandidateCount || 0) - Number(payload.data?.latestEligibleSecurityCount || 0)),
      price_coverage_ratio: Number(payload.data?.providerReturnedCandidateCount || 0) / Math.max(1, Number(payload.data?.requestedCandidateCount || 1)),
      provider_returned_symbol_count: payload.data?.providerReturnedCandidateCount,
      provider_requested_symbol_count: payload.data?.requestedCandidateCount,
      model_price_universe_ratio: Number(payload.data?.analyzedSecurityCount || 0) / Math.max(1, Number(payload.data?.requestedCandidateCount || 1)),
      eligible_price_ratio: Number(payload.data?.analyzedSecurityCount || 0) / Math.max(1, Number(payload.data?.requestedCandidateCount || 1)),
      liquidity_eligible_ratio: Number(payload.data?.latestEligibleSecurityCount || 0) / Math.max(1, Number(payload.data?.requestedCandidateCount || 1)),
      fresh_price_ratio: freshPriceRatio,
      fresh_price_rows: freshCandidateRows.length,
      price_quality_rows: candidateQualityRows.length,
      data_as_of: asOf,
      provider: payload.data?.provider || payload.data?.sourceLabel,
      source_health: sourceHealthView(payload),
      price_source_counts: priceCounts,
      data_quality_status_counts: {
        pass: candidateQualityRows.filter((row) => row.eligible_latest === true).length,
        excluded: candidateQualityRows.filter((row) => row.eligible_latest !== true).length,
        benchmark_comparator_only: qualityRows.filter((row) => row.role !== 'candidate').length,
      },
      latest_eligibility_exclusion_counts: payload.data?.latestEligibilityExclusionCounts || null,
      exclusion_counts_may_overlap: payload.data?.funnel?.exclusionCountsMayOverlap === true,
      liquidity_status_counts: {
        pass: payload.data?.latestEligibleSecurityCount,
        fail: Math.max(0, Number(payload.data?.analyzedSecurityCount || 0) - Number(payload.data?.latestEligibleSecurityCount || 0)),
      },
      final_eligibility_status_counts: {
        pass: payload.data?.latestEligibleSecurityCount,
        fail: Math.max(0, Number(payload.data?.analyzedSecurityCount || 0) - Number(payload.data?.latestEligibleSecurityCount || 0)),
      },
      capacity_status_counts: null,
      capacity_status_note: '미평가 · 공개 payload에는 주문 규모·시장 충격·참여율을 반영한 체결 용량 모델이 없습니다.',
    },
    factor_diagnostics: payload.factorDiagnostics
      ? factorDiagnosticsView(payload)
      : {
        scope_note_ko: `독립 팩터 ${formatInteger(payload.meta?.independentFactorCount)}개와 호환 alias ${formatInteger(payload.meta?.aliasFactorCount)}개를 하나의 고정 비중 방법에서 비교합니다. Forward Rank-IC와 중복도 값이 없으면 추정하지 않습니다.`,
        category_summary: categorySummaryView(definitions),
        rank_ic_rows: [],
        rank_ic_top: [],
        redundancy_rows: [],
        redundancy_top: [],
        redundancy_pairs: [],
      },
    notes_ko: [
      `동일 입력 최고 팩터: ${payload.bestFactor}`,
      '팩터 선택 점수와 두 포트폴리오는 Python에서 계산됩니다.',
      selectedDefinition.description || '',
    ].filter(Boolean),
  };

  return {
    schema_version: 1,
    generated_at_utc: payload.generatedAtUtc,
    title: '모멘텀 팩터 데일리 대시보드',
    latest_run_index: 0,
    runs: [run],
  };
}

const CANONICAL_COMPONENTS = [
  ['cagr_score', 'CAGR', 'component-cagr'],
  ['calmar_score', 'Calmar', 'component-calmar'],
  ['max_drawdown_score', 'MDD 방어', 'component-drawdown'],
  ['sharpe_score', 'Sharpe', 'component-sharpe'],
  ['sortino_score', 'Sortino', 'component-sortino'],
  ['stability_score', '안정성', 'component-stability'],
];

function fixedPolicyLabel(payload, policyId) {
  if (payload.weightingMethodology?.policyId === policyId) {
    return payload.weightingMethodology?.policy?.label || policyId || '-';
  }
  return policyId || '-';
}

function fixedPolicyClass(policyId) {
  return CHART_PALETTE_CLASS_MAP.policies[policyId]
    || `policy-${String(policyId || 'unavailable').replaceAll('_', '-')}`;
}

function factorSelectionStatusClass(status) {
  return CHART_PALETTE_CLASS_MAP.statuses[status]
    || CHART_PALETTE_CLASS_MAP.statuses.default;
}

function factorSelectionStatusLabel(status) {
  const labels = {
    eligible: '선정 적격',
    data_excluded: '데이터 조건 미충족',
    extreme_event_excluded: '극단사건 가드레일 제외',
  };
  return labels[status] || '상태 미확인';
}

function factorExclusionReasonLabel(code) {
  const labels = {
    terminal_nav_unavailable: '최종 NAV 평가 불가(선정 제외·진단용)',
    duplicate_alias: '독립 팩터와 중복된 호환 alias(선정 제외·진단용)',
    extreme_event: '극단사건 가드레일 미충족(선정 제외·진단용)',
    security_day_contribution: '단일 종목·일 기여도 가드레일 미충족',
    ending_nav_unavailable: '최종 NAV 평가 불가(선정 제외·진단용)',
    policy_input_unavailable: '비중 정책 입력 불충분(선정 제외·진단용)',
    insufficient_history: '공통 비교 이력 부족(선정 제외·진단용)',
  };
  return labels[code] || '기타 데이터·가드레일 조건 미충족(선정 제외·진단용)';
}

function factorRankingStatusText(row) {
  if (row?.selected === true) return '선택';
  const status = factorSelectionStatusLabel(row?.selection_status);
  const reasonCodes = Array.isArray(row?.exclusion_reason_codes)
    ? [...new Set(row.exclusion_reason_codes.filter(Boolean))]
    : [];
  const reasons = reasonCodes.map(factorExclusionReasonLabel);
  if (reasons.length) return `${status} · ${reasons.join(' · ')}`;
  if (row?.comparison_status === 'available') return status;
  if (row?.selection_status) return status;
  return '상태 미확인';
}

function factorRiskQualityText(row) {
  const daily = formatInteger(row?.daily_risk_observations);
  const total = formatInteger(row?.observations);
  const gaps = formatInteger(row?.quote_gap_observations);
  const coverage = formatPercent(row?.valuation_coverage_ratio);
  if (row?.risk_metrics_exact === true) {
    return `exact · 일간 위험 ${daily}/${total} · quote gap ${gaps} · 평가 ${coverage}`;
  }
  return `불완전 · 일간 위험 ${daily}/${total} · quote gap ${gaps} · 평가 ${coverage} · MDD는 관측 종가 기준 하한`;
}

function factorScoreMethodDescription(payload) {
  const lower = Number(payload?.config?.score_winsor_lower);
  const upper = Number(payload?.config?.score_winsor_upper);
  const periods = Number(payload?.config?.stability_periods);
  const lowerLabel = Number.isFinite(lower) ? `${formatNumber(lower * 100)}%` : '-';
  const upperLabel = Number.isFinite(upper) ? `${formatNumber(upper * 100)}%` : '-';
  const periodLabel = Number.isInteger(periods) && periods > 0 ? `${formatInteger(periods)}개` : '-';
  return `성과 구성요소는 실제 실행 설정 ${lowerLabel}~${upperLabel} 백분위에서 윈저화한 뒤 횡단면 percentile 점수로 변환하며, 안정성은 평가창을 ${periodLabel} 하위기간으로 나눈 CAGR 분산을 사용합니다.`;
}

function factorGridAccounting(payload) {
  const accounting = payload?.factorAccounting || {};
  const independentFactorCount = Number(accounting.independentFactorCount) || 0;
  const expectedIndependentFactorCount = Number(accounting.expectedIndependentFactorCount)
    || independentFactorCount;
  const evaluatedIndependentFactorCount = Number(accounting.evaluatedIndependentFactorCount)
    || expectedIndependentFactorCount;
  const availableIndependentFactorCount = Number(accounting.availableIndependentFactorCount) || 0;
  const excludedIndependentFactorCount = Number(accounting.excludedIndependentFactorCount) || 0;
  const commonComparableFactorCount = Number(accounting.commonComparableFactorCount) || 0;
  const diagnosticAliasFactorCount = Number(accounting.diagnosticAliasFactorCount) || 0;
  const missingIndependentFactorCount = Number(accounting.missingIndependentFactorCount) || 0;
  const totalOutputRowCount = Array.isArray(payload?.factorRanking)
    ? payload.factorRanking.length
    : evaluatedIndependentFactorCount + diagnosticAliasFactorCount;
  return {
    independentFactorCount,
    expectedIndependentFactorCount,
    evaluatedIndependentFactorCount,
    availableIndependentFactorCount,
    excludedIndependentFactorCount,
    commonComparableFactorCount,
    diagnosticAliasFactorCount,
    missingIndependentFactorCount,
    totalOutputRowCount,
  };
}

function bestFactorRow(payload) {
  return (payload.factorRanking || []).find((row) => row.selected === true)
    || (payload.factorRanking || []).find((row) => (
      row.factor === payload.bestFactor && row.policy_id === payload.weightingPolicy
    ))
    || null;
}

function appendFactorRankingBar(target, options) {
  const row = document.createElement(options.interactive ? 'button' : 'div');
  row.className = `factor-ranking-bar-row ${options.className || ''} ${options.selected ? 'is-selected' : ''} ${options.best ? 'is-best' : ''}`.trim();
  if (options.interactive) {
    row.type = 'button';
    row.setAttribute('aria-pressed', String(Boolean(options.selected)));
    row.addEventListener('click', options.onClick);
  }
  const label = document.createElement('span');
  label.className = 'factor-ranking-bar-label';
  label.textContent = options.label;
  if (options.detail) {
    const detail = document.createElement('small');
    detail.textContent = options.detail;
    label.appendChild(detail);
  }
  const track = document.createElement('span');
  track.className = 'bar-track';
  const fill = document.createElement('span');
  fill.className = 'bar-fill';
  fill.style.width = `${Math.max(0, Math.min(100, Number(options.width) || 0)).toFixed(2)}%`;
  track.appendChild(fill);
  const value = document.createElement('strong');
  value.textContent = options.valueLabel;
  row.append(label, track, value);
  target.appendChild(row);
}

function selectFactorFromRanking(factor) {
  const selector = document.querySelector('#factor-select');
  if (!selector || !Array.from(selector.options).some((option) => option.value === factor)) return;
  const preferredDate = selectedDate();
  selector.value = factor;
  state.hasUserSelectedFactor = true;
  syncFactorDependentControls(currentRun(), factor, preferredDate);
  renderAll();
  const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  document.querySelector('#visual-dashboard')?.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'start' });
}

function populateFixedPolicyView(payload) {
  return payload;
}

function filteredFactorRanking(payload) {
  const search = String(document.querySelector('#joint-factor-search')?.value || '').trim().toLowerCase();
  return (payload.factorRanking || [])
    .filter((row) => !search || `${row.factor} ${row.category || ''}`.toLowerCase().includes(search))
    .sort((left, right) => (
      Number(left.rank ?? Number.MAX_SAFE_INTEGER) - Number(right.rank ?? Number.MAX_SAFE_INTEGER)
      || Number(right.selection_score ?? -Infinity) - Number(left.selection_score ?? -Infinity)
      || String(left.factor).localeCompare(String(right.factor))
      || String(left.policy_id).localeCompare(String(right.policy_id))
    ));
}

function renderFactorRanking(payload) {
  const rows = filteredFactorRanking(payload);
  const accounting = factorGridAccounting(payload);
  const chart = document.querySelector('#joint-ranking-chart');
  const tbody = document.querySelector('#joint-ranking-table tbody');
  chart.replaceChildren();
  tbody.replaceChildren();
  setText(
    '#joint-ranking-scope',
    `전체 ${formatInteger(accounting.totalOutputRowCount)}개 팩터 · 독립 ${formatInteger(accounting.expectedIndependentFactorCount)}개 + 호환 alias ${formatInteger(accounting.diagnosticAliasFactorCount)}개`,
  );
  setText(
    '#joint-ranking-title',
    `동일 입력의 팩터 랭킹 · 비교 가능 ${formatInteger(accounting.availableIndependentFactorCount)}개 · 제외 ${formatInteger(accounting.excludedIndependentFactorCount)}개`,
  );
  setText(
    '#joint-ranking-scope-note',
    `최고 후보 ${formatInteger(accounting.commonComparableFactorCount)}/${formatInteger(accounting.independentFactorCount)}개 · 제외 팩터와 호환 alias는 진단용`,
  );
  const chartRows = rows.filter((row) => finite(row.selection_score)).slice(0, 12);
  const maxScore = Math.max(...chartRows.map((row) => Number(row.selection_score) || 0), 1);
  const comparisonFactor = selectedFactor();
  chartRows.forEach((row) => {
    const comparisonSelected = row.factor === comparisonFactor;
    appendFactorRankingBar(chart, {
      label: row.factor,
      detail: `${row.selected === true ? '최고 팩터' : factorRankingStatusText(row)}${comparisonSelected ? ' · 비교 중' : ''} · 동일 표본 상대 합성 점수`,
      width: Number(row.selection_score) / maxScore * 100,
      valueLabel: `${formatNumber(row.selection_score)} / 100`,
      className: factorSelectionStatusClass(row.selection_status),
      selected: comparisonSelected,
      best: row.selected === true,
      interactive: true,
      onClick: () => selectFactorFromRanking(row.factor),
    });
  });
  rows.forEach((row) => {
    const tr = document.createElement('tr');
    if (row.factor === comparisonFactor) tr.classList.add('is-selected');
    if (row.selected === true) tr.classList.add('is-best');
    appendCell(tr, row.rank ?? '-');
    appendCell(tr, row.factor, { strong: row.selected === true });
    appendCell(tr, humanFactorCategory(row.category));
    appendCell(
      tr,
      finite(row.selection_score) ? `${formatNumber(row.selection_score)} / 100` : '-',
      { className: finite(row.selection_score) ? 'positive' : 'neutral' },
    );
    appendCell(tr, formatPercent(row.cagr), { className: classForNumber(row.cagr) });
    appendCell(tr, formatNumber(row.sharpe), { className: classForNumber(row.sharpe) });
    appendCell(tr, formatPercent(row.max_drawdown), { className: Number(row.max_drawdown) < 0 ? 'negative' : 'neutral' });
    appendCell(tr, factorRiskQualityText(row), { className: row.risk_metrics_exact === true ? 'neutral' : 'negative' });
    appendCell(tr, factorRankingStatusText(row));
    tbody.appendChild(tr);
  });
  if (!rows.length) {
    appendEmpty('#joint-ranking-chart', '검색 조건에 맞는 팩터가 없습니다.');
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 9;
    td.textContent = '검색 조건에 맞는 팩터가 없습니다.';
    tr.appendChild(td);
    tbody.appendChild(tr);
  }
  setText(
    '#joint-ranking-meta',
    `독립 팩터 ${formatInteger(accounting.expectedIndependentFactorCount)}개: 비교 가능 ${formatInteger(accounting.availableIndependentFactorCount)} · 제외 ${formatInteger(accounting.excludedIndependentFactorCount)} · alias ${formatInteger(accounting.diagnosticAliasFactorCount)} · 현재 표시 ${formatInteger(rows.length)}`,
  );
}

function renderFactorScoreComponents(payload, selected) {
  const target = document.querySelector('#factor-component-chart');
  target.replaceChildren();
  CANONICAL_COMPONENTS.forEach(([key, label, className]) => {
    const value = Number(selected?.[key]);
    appendFactorRankingBar(target, {
      label,
      detail: `가중치 ${formatPercent(selected?.[key.replace('_score', '_weight')])}`,
      width: Number.isFinite(value) ? value : 0,
      valueLabel: Number.isFinite(value) ? formatNumber(value) : '-',
      className: `${className} ${CHART_PALETTE_CLASS_MAP.bars.component}`,
    });
  });
  setText(
    '#factor-selection-reason',
    `최고 팩터 ${payload.bestFactor || '-'} · 상대 합성 점수 ${formatNumber(selected?.selection_score)} / 100`,
  );
}

function renderFixedAllocationMethod(payload) {
  const target = document.querySelector('#allocation-method-card');
  target.replaceChildren();
  const policy = payload.weightingMethodology?.policy || {};
  const parameters = payload.allocationMethod?.parameters || {};
  const item = document.createElement('div');
  item.className = 'mini-item is-selected';
  const title = document.createElement('strong');
  title.textContent = policy.label || payload.weightingPolicy || '-';
  const detail = document.createElement('small');
  detail.textContent = `팩터 ${formatPercent(parameters.factorScoreWeight)} + 거래대금 ${formatPercent(parameters.liquidityWeight)} · 종목당 상한 ${formatPercent(parameters.maxWeight)}`;
  item.append(title, detail);
  target.appendChild(item);
  setText('#allocation-method-meta', `고정 방법 · v${policy.version || '-'}`);
}

function renderFactorGuardrails(payload, selected) {
  const target = document.querySelector('#factor-guardrail-list');
  target.replaceChildren();
  const statusFields = Object.entries(selected || {})
    .filter(([key, value]) => key.startsWith('guardrail_') && typeof value === 'boolean')
    .sort(([left], [right]) => left.localeCompare(right));
  statusFields.forEach(([key, passed]) => {
    const item = document.createElement('div');
    item.className = `gate-item ${passed ? 'pass' : 'block'}`;
    const title = document.createElement('strong');
    title.textContent = `${passed ? '통과' : '미통과'} · ${key.replace('guardrail_', '').replaceAll('_', ' ')}`;
    item.append(title);
    target.appendChild(item);
  });
  if (!statusFields.length) appendEmpty('#factor-guardrail-list', '가드레일 세부 상태가 없습니다.');
  const profile = payload.factorSelectionDecision?.guardrailProfile;
  setText('#factor-guardrail-meta', `${profile?.id || payload.selectionMethod?.guardrailVersion || '-'} · ${formatInteger(profile?.rules?.length || 0)}개 규칙`);
}

function renderAnalysisDataContract(payload) {
  const target = document.querySelector('#analysis-data-contract');
  target.replaceChildren();
  const pairs = [
    ['요청 후보', formatInteger(payload.data?.requestedCandidateCount)],
    ['제공자 반환', formatInteger(payload.data?.providerReturnedCandidateCount)],
    ['실제 분석', formatInteger(payload.data?.analyzedSecurityCount)],
    ['최신 적격', formatInteger(payload.data?.latestEligibleSecurityCount)],
    ['가격 기준', payload.data?.priceBasis || '-'],
    ['거래량 기준', payload.data?.volumeBasis || '-'],
    ['결과 생성', formatKoreanDateTime(payload.generatedAtUtc)],
    ['연구 상태', payload.researchScope?.evidenceStatus || '-'],
  ];
  pairs.forEach(([label, value]) => appendDefinition(target, label, value));
  setText('#analysis-result-key', payload.resultKey || '-');
  document.querySelector('#analysis-result-key').title = payload.resultKey || '-';
}

function requestedThroughText(payload) {
  const data = payload?.data || {};
  const asOf = typeof data.asOf === 'string' && data.asOf ? data.asOf : null;
  const requestedThrough = typeof data.requestedThrough === 'string' && data.requestedThrough
    ? data.requestedThrough
    : null;
  const source = data.sourceLabel || data.provider || '-';
  if (!asOf || !requestedThrough) {
    return `${source} · 요청 종료일 또는 실제 기준일 미표기`;
  }
  if (requestedThrough === asOf) {
    return `${source} · 요청 종료(requestedThrough) ${requestedThrough} = 실제 최신 완료 거래일(asOf) ${asOf}`;
  }
  const requestedDate = parseDateString(requestedThrough);
  const asOfDate = parseDateString(asOf);
  if (!requestedDate || !asOfDate || requestedDate < asOfDate) {
    return `${source} · 요청 종료(requestedThrough) ${requestedThrough} / 실제 기준일(asOf) ${asOf} · 일자 provenance 확인 필요`;
  }
  const weekend = requestedDate && [0, 6].includes(requestedDate.getUTCDay());
  const reason = weekend
    ? '요청 종료일이 주말이므로 직전 미국 거래일 종가를 사용'
    : '요청 종료일이 미국 휴장일이거나 아직 완료되지 않은 거래일이므로 직전 완료 거래일 종가를 사용';
  return `${source} · 요청 종료(requestedThrough) ${requestedThrough} / 실제 최신 완료 거래일(asOf) ${asOf} · ${reason}`;
}

function analysisCountDefinitions(payload) {
  const data = payload?.data || {};
  const pieces = [];
  if (integer(data.requestedCandidateCount)) {
    pieces.push(`요청(requested) ${formatInteger(data.requestedCandidateCount)}=현재 유니버스 후보`);
  }
  if (integer(data.providerReturnedCandidateCount)) {
    pieces.push(`제공자 반환 ${formatInteger(data.providerReturnedCandidateCount)}=가격 열 반환`);
  }
  if (integer(data.analyzedSecurityCount)) {
    pieces.push(`분석(analyzed) ${formatInteger(data.analyzedSecurityCount)}=가격 분석 가능`);
  }
  if (integer(data.latestEligibleSecurityCount)) {
    pieces.push(`최신 적격(latest eligible) ${formatInteger(data.latestEligibleSecurityCount)}=현재 편입 필터 모두 통과`);
  }
  return pieces.length ? pieces.join(' · ') : '유니버스 카운트 정의를 확인할 수 없습니다.';
}

function universeScopeEvidence(payload) {
  const rows = Array.isArray(payload?.sourceHealth) ? payload.sourceHealth : [];
  const evidence = rows.find((row) => (
    isRecord(row)
    && typeof row.point_in_time_universe === 'boolean'
  )) || rows.find((row) => (
    isRecord(row)
    && (row.universe_provenance || row.universe_source_mode || row.universe_profile)
  )) || null;
  const limitations = Array.isArray(payload?.researchScope?.limitations)
    ? payload.researchScope.limitations.filter((value) => typeof value === 'string' && value.trim())
    : [];
  const survivorshipLimitation = limitations.find((value) => (
    value.includes('현재 상장')
    || value.includes('역사적 구성종목')
    || value.includes('상장폐지')
    || value.toLowerCase().includes('ticker reuse')
  )) || null;
  const currentListed = Boolean(survivorshipLimitation?.includes('현재 상장'));
  const pointInTime = typeof evidence?.point_in_time_universe === 'boolean'
    ? evidence.point_in_time_universe
    : null;
  const scope = [
    currentListed ? '현재 상장 종목 중심' : null,
    pointInTime === true
      ? 'Point-in-time 유니버스'
      : (pointInTime === false ? 'Point-in-time 유니버스 아님' : '유니버스 시점성 미확인'),
  ].filter(Boolean).join(' · ');
  const provenance = [
    evidence?.source ? `source ${evidence.source}` : null,
    evidence?.status ? `status ${evidence.status}` : null,
    evidence?.universe_provenance ? `provenance ${evidence.universe_provenance}` : null,
    evidence?.universe_source_mode ? `mode ${evidence.universe_source_mode}` : null,
    evidence?.universe_profile ? `profile ${evidence.universe_profile}` : null,
    integer(evidence?.records) ? `${formatInteger(evidence.records)} records` : null,
  ].filter(Boolean).join(' · ');
  return {
    scope,
    evidence: [survivorshipLimitation, provenance].filter(Boolean).join(' · ')
      || '유니버스 provenance와 생존편향 한계가 payload에 없습니다.',
    pointInTime,
    currentListed,
    sourceRow: evidence,
    limitation: survivorshipLimitation,
  };
}

function renderFactorAnalysis() {
  const payload = state.payload;
  if (!payload) return;
  const target = payload.bestFactorPortfolio || {};
  const selected = bestFactorRow(payload);
  const invested = (target.weights || []).reduce((sum, row) => sum + (Number(row.weight) || 0), 0);
  setText('#analysis-asof', payload.data?.asOf || '-');
  setText('#analysis-source', requestedThroughText(payload));
  setText('#analysis-analyzed', `${formatInteger(payload.data?.analyzedSecurityCount)}개`);
  setText('#analysis-funnel', analysisCountDefinitions(payload));
  setText('#analysis-factor', payload.bestFactor || '-');
  setText('#analysis-factor-score', `동일 표본 상대 합성 점수 ${formatNumber(selected?.selection_score)} / 100 · 절대 신뢰도 아님`);
  setText('#analysis-policy', fixedPolicyLabel(payload, payload.weightingPolicy));
  setText('#analysis-policy-version', `${payload.weightingPolicy || '-'} · v${payload.weightingMethodology?.policy?.version || '-'}`);
  setText('#analysis-invested', formatPercent(invested));
  setText('#analysis-cash', `현금 ${formatPercent(target.cashWeight)} · ${formatInteger(target.selectedSecurityCount)}개 종목`);
  const universeScope = universeScopeEvidence(payload);
  setText('#analysis-universe-scope', universeScope.scope);
  setText('#analysis-universe-evidence', universeScope.evidence);
  renderFactorRanking(payload);
  renderFactorScoreComponents(payload, selected);
  renderFixedAllocationMethod(payload);
  renderFactorGuardrails(payload, selected);
  renderAnalysisDataContract(payload);
}

function bindFactorAnalysisControls() {
  const search = document.querySelector('#joint-factor-search');
  if (search && search.dataset.bound !== 'true') {
    search.dataset.bound = 'true';
    search.addEventListener('input', () => renderFactorRanking(state.payload));
  }
}

function renderAll() {
  if (!state.data) return;
  renderSummary();
  renderDiagnostics();
  renderSelectedFactorMethod();
  renderFactorReturnChart();
  renderBacktestChart();
  renderWeightChart();
  renderHoldingsTable();
  renderDailyWeightsAnalysis();
  renderFactorAnalysis();
}

function renderExploration() {
  if (!state.data) {
    return;
  }
  renderAll();
}

function presetDisplayName(presetId) {
  const labels = {
    latest: '최신 기본 preset',
    'latest-top20': '최신 기준 · Top 20',
    'latest-top30': '최신 기준 · Top 30',
    'prior-seven-sessions-top20': '직전 7개 완료 세션 · Top 20',
  };
  return labels[presetId] || presetId || '정적 preset';
}

function populateResultOptions(manifest) {
  const select = document.querySelector('#run-select');
  select.replaceChildren();
  manifest.entries.forEach((entry) => {
    const option = document.createElement('option');
    const market = entry.identity?.keyParts?.marketSnapshot || {};
    const inputs = entry.normalizedInputs || {};
    option.value = entry.resultKey;
    option.textContent = [
      presetDisplayName(entry.presetId),
      `실제 기준일 ${market.dataAsOf || inputs.effective_end_date || inputs.end_date || '-'}`,
      `Top ${inputs.top_n ?? '-'}`,
    ].join(' · ');
    select.appendChild(option);
  });
  select.value = manifest.defaultResultKey;
  select.disabled = manifest.entries.length <= 1;
}

function fillResearchForm(entry, normalizedInputs = entry.normalizedInputs) {
  INPUT_FIELDS.forEach((field) => {
    const element = document.querySelector(`#${field.id}`);
    if (element && Object.prototype.hasOwnProperty.call(normalizedInputs, field.key)) {
      element.value = serializeInputValue(field, normalizedInputs[field.key]);
    }
  });
}

function readResearchFormRequest() {
  const selectedResultKey = document.querySelector('#run-select')?.value;
  const baseEntry = entryByResultKey(state.manifest, selectedResultKey)
    || state.baseEntry
    || entryByResultKey(state.manifest, state.manifest.defaultResultKey);
  if (!baseEntry) throw new Error(LOCAL_API_REQUIRED);
  const requestedInputs = cloneJson(baseEntry.normalizedInputs);
  INPUT_FIELDS.forEach((field) => {
    const element = document.querySelector(`#${field.id}`);
    requireCondition(element, `Python 분석 입력 control이 없습니다: ${field.id}`);
    requestedInputs[field.key] = parseInputValue(field, element.value);
  });
  if (
    !Number.isInteger(Number(requestedInputs.evaluation_window_days))
      || Number(requestedInputs.evaluation_window_days) < 21
      || Number(requestedInputs.evaluation_window_days) > 2520
  ) {
    throw new Error('평가 기간(거래일)은 21–2520 정수여야 합니다.');
  }
  if (Number(requestedInputs.top_n) < 1 || Number(requestedInputs.top_n) > 50) {
    throw new Error('Top-N은 1–50 정수여야 합니다.');
  }
  applyResearchInputDependencies(requestedInputs);
  return {
    baseEntry,
    requestedInputs,
    entry: resolveExactEntry(state.manifest, requestedInputs),
  };
}

function updateLocation(mode, resultKey, normalizedInputs) {
  const presetId = entryByResultKey(state.manifest, resultKey)?.presetId || null;
  const next = `${window.location.pathname}${searchForRequest(
    resultKey,
    normalizedInputs,
    presetId,
  )}${window.location.hash}`;
  if (mode === 'push') window.history.pushState({ resultKey }, '', next);
  if (mode === 'replace') window.history.replaceState({ resultKey }, '', next);
}

function setInputStatus(message, tone = 'ok') {
  const status = document.querySelector('#input-status');
  if (!status) return;
  status.textContent = message;
  status.dataset.tone = tone;
}

function renderResearchDraftState() {
  const badge = document.querySelector('#research-draft-status');
  const submit = document.querySelector('#analysis-submit-button');
  if (!badge || !submit || !state.entry) return;
  let request;
  try {
    request = readResearchFormRequest();
  } catch (error) {
    badge.dataset.state = 'invalid';
    badge.textContent = '입력 확인 필요';
    submit.disabled = true;
    setInputStatus(`입력 확인 필요 · 현재 결과 유지 · ${error.message}`, 'error');
    return;
  }
  const dirty = !sameJson(request.requestedInputs, state.entry.normalizedInputs);
  badge.dataset.state = dirty ? 'draft' : 'applied';
  badge.textContent = dirty ? '미적용 변경' : '현재 결과와 동일';
  submit.disabled = !dirty;
  if (!dirty) {
    submit.textContent = '현재 결과';
    setInputStatus('현재 결과에 적용된 입력과 동일합니다.', 'ok');
    return;
  }
  if (request.entry) {
    submit.textContent = '저장 결과 열기';
    setInputStatus('미적용 변경 · 저장 결과를 열기 전까지 현재 결과를 유지합니다.', 'pending');
    return;
  }
  if (state.controlCapabilities) {
    submit.disabled = false;
    submit.textContent = '원격 API로 분석';
    setInputStatus('미적용 변경 · 원격 API 실행 전까지 현재 결과를 유지합니다.', 'pending');
    return;
  }
  if (isLoopbackOrFilePreview(window.location)) {
    submit.disabled = false;
    submit.textContent = '로컬 API로 분석';
    setInputStatus('미적용 변경 · 로컬 Python API 실행 필요 · 현재 결과를 유지합니다.', 'pending');
    return;
  }
  submit.disabled = true;
  submit.textContent = '분석 API 연결 필요';
  setInputStatus(
    `미적용 변경 · 원격 API 연결이 확인되지 않아 현재 결과를 유지합니다.${state.controlApiError ? ` ${state.controlApiError}` : ''}`,
    'error',
  );
}

function resultSourceLabel(source) {
  if (source === 'local_api') return '로컬 API 계산 결과';
  if (source === 'remote_api') return '원격 API 검증 결과';
  if (source === 'static_grid') return '검증된 정적 preset';
  return '결과 없음';
}

function setResultSource(source, resultKey = null) {
  state.resultSource = source;
  const sourceElement = document.querySelector('#result-source');
  const keyElement = document.querySelector('#result-key');
  if (sourceElement) {
    sourceElement.textContent = resultSourceLabel(source);
    sourceElement.dataset.source = source || 'none';
  }
  if (keyElement) {
    keyElement.textContent = resultKey || '-';
    keyElement.title = resultKey || '';
  }
}

function showUnavailable(message, requestedInputs = null, baseEntry = null) {
  state.loadToken += 1;
  document.body.classList.add('result-unavailable');
  state.data = null;
  state.payload = null;
  state.summary = null;
  state.entry = null;
  state.baseEntry = baseEntry || state.baseEntry;
  setResultSource(null);
  setInputStatus(message, 'error');
  if (baseEntry && requestedInputs) fillResearchForm(baseEntry, requestedInputs);
  const statusCard = document.querySelector('#run-status');
  if (statusCard) {
    statusCard.replaceChildren();
    statusCard.textContent = `검증 실패 · 이전 결과를 숨겼습니다. ${message}`;
    statusCard.removeAttribute('aria-busy');
    statusCard.classList.remove('is-updating');
  }
}

function showLoading(message) {
  setStatusMessage(message);
  setInputStatus(message, 'pending');
}

function showResult() {
  document.body.classList.remove('result-unavailable');
}

function installValidatedPayload({
  entry,
  baseEntry = entry,
  payload,
  summary = null,
  source,
}) {
  const adapted = adaptSchemaV5Payload(payload);
  requireCondition(
    adapted?.schema_version === 1 && Array.isArray(adapted.runs) && adapted.runs.length === 1,
    '지원하지 않는 대시보드 adapter 결과입니다.',
  );
  state.entry = entry;
  state.baseEntry = baseEntry;
  state.summary = summary;
  state.payload = payload;
  state.data = adapted;
  state.activeRunIndex = Number.isInteger(adapted.latest_run_index)
    ? adapted.latest_run_index
    : 0;
  state.hasUserSelectedFactor = false;
  fillControls();
  populateFixedPolicyView(payload);
  bindFactorAnalysisControls();
  fillResearchForm(baseEntry, entry.normalizedInputs);
  setResultSource(source, entry.resultKey);
  renderResearchDraftState();
  renderAll();
  showResult();
}

async function loadEntry(entry, options = {}) {
  const token = ++state.loadToken;
  showLoading('manifest의 선택된 Python detail/summary를 검증해 불러오는 중입니다...');
  try {
    const loaded = await loadStaticEntryData(entry, {
      manifestUrl: state.manifestUrl,
      pageUrl: window.location.href,
    });
    if (token !== state.loadToken) return;
    installValidatedPayload({
      entry,
      payload: loaded.payload,
      summary: loaded.summary,
      source: 'static_grid',
    });
    if (options.historyMode) {
      updateLocation(options.historyMode, entry.resultKey, entry.normalizedInputs);
    }
    const sidecarNote = loaded.payload.__factorHoldingHistorySidecarError
      ? ` · 팩터별 보유 이력 검증 실패로 최고 팩터 이력만 표시: ${loaded.payload.__factorHoldingHistorySidecarError}`
      : '';
    setInputStatus(
      `정확히 일치하는 검증된 정적 preset을 열었습니다: ${entry.resultKey.slice(0, 12)}…${sidecarNote}`,
      loaded.payload.__factorHoldingHistorySidecarError ? 'pending' : 'ok',
    );
  } catch (error) {
    if (token !== state.loadToken) return;
    showUnavailable(
      `결과를 표시할 수 없습니다: ${error.message}`,
      entry.normalizedInputs,
      entry,
    );
    console.error(error);
  }
}

async function loadLocalApiResult(requestedInputs, baseEntry, options = {}) {
  const token = ++state.loadToken;
  const researchInputs = researchInputsFromNormalizedInputs(requestedInputs);
  if (options.historyMode) {
    updateLocation(options.historyMode, baseEntry.resultKey, requestedInputs);
  }
  showLoading('로컬 Python API에서 실제시장 2,700개 이상 전체 grid를 계산하는 중입니다...');
  setInputStatus(
    `로컬 API(${LOCAL_API_BASE_URL})에 현재 ResearchInputs를 제출하는 중입니다.`,
    'pending',
  );
  try {
    const submission = await fetchLocalApiJson('/api/runs', {
      method: 'POST',
      body: researchInputs,
    });
    const payload = await resolveLocalApiResult(submission, token);
    if (token !== state.loadToken) return;
    const identity = payload.resultIdentity;
    const normalizedInputs = identity?.keyParts?.normalizedInputs;
    requireCondition(
      isRecord(identity) && isRecord(normalizedInputs),
      '로컬 API 결과 identity가 없습니다.',
    );
    const entry = {
      resultKey: payload.resultKey,
      normalizedInputs,
      identity,
    };
    await validateIdentityDigest(identity, 'local API detail');
    await validateResult(entry, payload, null, {
      source: 'local_api',
      expectedResearchInputs: researchInputs,
    });
    await attachFactorHoldingHistorySidecar(payload, {
      pageUrl: window.location.href,
    });
    if (token !== state.loadToken) return;
    installValidatedPayload({
      entry,
      baseEntry,
      payload,
      source: 'local_api',
    });
    updateLocation('replace', baseEntry.resultKey, normalizedInputs);
    setInputStatus(
      `로컬 API가 검증된 새 Python 결과를 열었습니다: ${payload.resultKey.slice(0, 12)}…`,
      'ok',
    );
  } catch (error) {
    if (token !== state.loadToken) return;
    if (state.payload) {
      fillResearchForm(baseEntry, requestedInputs);
      renderResearchDraftState();
      setInputStatus(`로컬 분석을 실행하지 못했습니다. 현재 검증 결과 유지 · ${error.message}`, 'error');
    } else {
      showUnavailable(`${error.message} ${LOCAL_API_REQUIRED}`, requestedInputs, baseEntry);
    }
    console.error(error);
  }
}

async function loadRemoteControlResult(requestedInputs, baseEntry, options = {}) {
  const capabilities = state.controlCapabilities;
  if (!capabilities) {
    setInputStatus('원격 API 연결이 확인되지 않아 현재 정적 결과를 유지합니다.', 'error');
    return;
  }
  const tokenValue = String(document.querySelector('#remote-control-token')?.value || '').trim();
  if (!tokenValue) {
    setInputStatus('세션 액세스 토큰을 입력해야 원격 분석을 요청할 수 있습니다.', 'error');
    return;
  }
  const loadToken = ++state.loadToken;
  const request = buildControlRunSubmission(requestedInputs);
  if (options.historyMode) {
    updateLocation(options.historyMode, baseEntry.resultKey, requestedInputs);
  }
  setInputStatus('원격 Python 분석을 요청했습니다. 검증된 현재 결과는 계속 표시합니다.', 'pending');
  try {
    const submissionResponse = await fetchControlApiJson(
      `/v1/projects/${CONTROL_PROJECT_ID}/runs`,
      {
        method: 'POST',
        body: request,
        token: tokenValue,
        headers: { 'Idempotency-Key': controlIdempotencyKey() },
      },
    );
    requireCondition(submissionResponse.statusCode === 202, '원격 API가 202 응답을 반환하지 않았습니다.');
    const submitted = normalizeControlRunEnvelope(
      submissionResponse.body,
      { inputs: request.inputs },
      capabilities,
    );
    const resultEnvelope = await resolveControlRun(
      submitted,
      loadToken,
      { capabilities },
    );
    if (loadToken !== state.loadToken) return;
    const payload = await fetchVerifiedControlArtifact(resultEnvelope);
    if (loadToken !== state.loadToken) return;
    const identity = payload?.resultIdentity;
    const normalizedResultInputs = identity?.keyParts?.normalizedInputs;
    requireCondition(
      isRecord(identity) && isRecord(normalizedResultInputs),
      '원격 artifact result identity가 없습니다.',
    );
    requireCondition(
      sameJson(
        controlRunInputsFromNormalizedInputs(normalizedResultInputs),
        resultEnvelope.effectiveInputs,
      ),
      '원격 artifact의 실제 ResearchInputs가 실행 결과 binding과 다릅니다.',
    );
    requireCondition(
      sameJson(resultEnvelope.payload?.resultIdentity, identity),
      '원격 결과 요약의 result identity가 artifact와 다릅니다.',
    );
    const entry = {
      resultKey: payload.resultKey,
      normalizedInputs: normalizedResultInputs,
      identity,
    };
    await validateIdentityDigest(identity, 'remote API detail');
    await validateResult(entry, payload, null, {
      source: 'remote_api',
      expectedResearchInputs: researchInputsFromNormalizedInputs(normalizedResultInputs),
    });
    await attachFactorHoldingHistorySidecar(payload, {
      pageUrl: window.location.href,
    });
    if (loadToken !== state.loadToken) return;
    let preservedDraft = null;
    try {
      const currentDraft = readResearchFormRequest().requestedInputs;
      if (!sameJson(currentDraft, normalizedResultInputs)) preservedDraft = currentDraft;
    } catch (error) {
      preservedDraft = null;
    }
    installValidatedPayload({
      entry,
      baseEntry,
      payload,
      source: 'remote_api',
    });
    if (preservedDraft) fillResearchForm(baseEntry, preservedDraft);
    renderResearchDraftState();
    state.pendingControlRun = null;
    updateLocation('replace', baseEntry.resultKey, normalizedResultInputs);
    setInputStatus(
      preservedDraft
        ? `원격 Python 결과를 열었고, 실행 중 편집한 초안은 입력칸에 유지했습니다: ${payload.resultKey.slice(0, 12)}…`
        : `원격 API의 새 Python 결과를 검증해 열었습니다: ${payload.resultKey.slice(0, 12)}…`,
      preservedDraft ? 'pending' : 'ok',
    );
  } catch (error) {
    if (loadToken !== state.loadToken) return;
    state.pendingControlRun = {
      ...(state.pendingControlRun || {}),
      status: 'failed',
      errorMessage: error.message,
    };
    fillResearchForm(baseEntry, requestedInputs);
    setInputStatus(
      `원격 분석 결과를 채택하지 않았습니다. 현재 결과를 유지합니다. ${error.message}`,
      'error',
    );
    console.error(error);
  }
}

function bindBrowserContractControls() {
  if (state.browserControlsBound) return;
  state.browserControlsBound = true;
  document.querySelector('#run-select').addEventListener('change', (event) => {
    const entry = entryByResultKey(state.manifest, event.target.value);
    if (!entry) {
      showUnavailable('선택한 정적 preset이 manifest에 없습니다.');
      return;
    }
    state.hasUserSelectedFactor = false;
    fillResearchForm(entry);
    loadEntry(entry, { historyMode: 'push' });
  });
  const researchForm = document.querySelector('#research-input-form');
  researchForm.addEventListener('input', renderResearchDraftState);
  researchForm.addEventListener('change', renderResearchDraftState);
  researchForm.addEventListener('invalid', (event) => {
    const details = event.target?.closest?.('details');
    if (details) details.open = true;
  }, true);
  researchForm.addEventListener('submit', (event) => {
    event.preventDefault();
    try {
      const request = readResearchFormRequest();
      if (request.entry) {
        loadEntry(request.entry, { historyMode: 'push' });
        return;
      }
      const apiRequest = localApiRequestFromStaticState(
        state.manifest,
        request.requestedInputs,
      );
      const executionRoute = analysisExecutionRoute(state.controlApiBase, window.location);
      if (executionRoute === 'remote') {
        loadRemoteControlResult(apiRequest.requestedInputs, apiRequest.baseEntry, {
          historyMode: 'push',
        });
      } else if (executionRoute === 'local') {
        loadLocalApiResult(apiRequest.requestedInputs, apiRequest.baseEntry, {
          historyMode: 'push',
        });
      } else {
        setInputStatus(
          '원격 API 연결이 확인되지 않아 분석을 시작하지 않았습니다. 현재 검증 결과를 유지합니다.',
          'error',
        );
      }
    } catch (error) {
      const executionRoute = analysisExecutionRoute(state.controlApiBase, window.location);
      if (executionRoute === 'remote') {
        setInputStatus(
          `원격 분석을 요청하지 않았습니다. 현재 결과를 유지합니다. ${error.message}`,
          'error',
        );
      } else if (executionRoute === 'local') {
        setInputStatus(`분석을 요청하지 않았습니다. 현재 결과 유지 · ${error.message}`, 'error');
      } else {
        setInputStatus(
          `원격 분석을 요청하지 않았습니다. 현재 결과를 유지합니다. ${error.message}`,
          'error',
        );
      }
    }
  });
  document.querySelector('#reset-default-inputs').addEventListener('click', () => {
    const entry = entryByResultKey(state.manifest, state.manifest.defaultResultKey);
    requireCondition(entry, 'manifest 기본 entry가 없습니다.');
    fillResearchForm(entry);
    loadEntry(entry, { historyMode: 'push' });
  });
  window.addEventListener('popstate', () => loadFromLocation());
}

function bindDashboardControls() {
  if (state.dashboardControlsBound) return;
  state.dashboardControlsBound = true;
  document.querySelector('#factor-select').addEventListener('change', () => {
    state.hasUserSelectedFactor = true;
    syncFactorDependentControls(currentRun(), selectedFactor(), selectedDate());
    renderExploration();
  });
  ['#date-select'].forEach((selector) => {
    document.querySelector(selector)?.addEventListener('input', () => {
      syncDefaultFactorToCurrentBasis();
      renderExploration();
    });
    document.querySelector(selector)?.addEventListener('change', () => {
      syncDefaultFactorToCurrentBasis();
      renderExploration();
    });
  });
}

async function loadFromLocation(options = {}) {
  const request = requestFromSearch(state.manifest, window.location.search);
  if (!request.baseEntry) {
    showUnavailable(request.error);
    return;
  }
  if (!request.entry) {
    const apiRequest = localApiRequestFromStaticState(state.manifest, request.requestedInputs);
    const executionRoute = analysisExecutionRoute(state.controlApiBase, window.location);
    if (executionRoute === 'remote') {
      await loadEntry(apiRequest.baseEntry, { historyMode: 'replace' });
      fillResearchForm(apiRequest.baseEntry, apiRequest.requestedInputs);
      setInputStatus(
        'URL의 입력값을 초안으로 열었습니다. 원격 분석은 버튼을 눌러야 시작됩니다.',
        'pending',
      );
      return;
    }
    if (executionRoute === 'local') {
      await loadLocalApiResult(apiRequest.requestedInputs, apiRequest.baseEntry, {
        historyMode: 'replace',
      });
      return;
    }
    await loadEntry(apiRequest.baseEntry, { historyMode: 'replace' });
    fillResearchForm(apiRequest.baseEntry, apiRequest.requestedInputs);
    setInputStatus(
      'URL의 입력값을 초안으로 열었지만 원격 API 연결이 확인되지 않았습니다. 현재 검증 결과를 유지합니다.',
      'error',
    );
    return;
  }
  await loadEntry(request.entry, {
    historyMode: options.replaceHistory || request.recoveredFromRotatedResult
      ? 'replace'
      : null,
  });
}

async function loadBrowserDashboard() {
  showLoading('bounded static-grid manifest를 검증하는 중입니다...');
  try {
    state.manifestUrl = new URL(MANIFEST_URL, window.location.href);
    const rawManifest = await fetchJson(state.manifestUrl.href, 'manifest');
    state.manifest = validateManifest(rawManifest);
    await Promise.all(
      state.manifest.entries.map((entry, index) => (
        validateIdentityDigest(entry.identity, `manifest.entries[${index}]`)
      )),
    );
    populateResultOptions(state.manifest);
    bindBrowserContractControls();
    bindDashboardControls();
    const automationInitialization = loadAutomationState(state.manifest);
    const controlApiInitialization = initializeControlApi();
    await loadFromLocation({ replaceHistory: !window.location.search });
    state.automation = await automationInitialization;
    if (state.data) renderSummary();
    const controlCapabilities = await controlApiInitialization;
    renderResearchDraftState();
    if (!controlCapabilities && state.controlApiError) {
      setInputStatus(
        `원격 API를 사용할 수 없습니다. 현재 정적 결과를 유지합니다. ${state.controlApiError}`,
        'error',
      );
    }
  } catch (error) {
    showUnavailable(`정적 grid를 사용할 수 없습니다: ${error.message}`);
    console.error(error);
  }
}

if (typeof globalThis !== 'undefined') {
  globalThis.__MFL_WEB_TESTS__ = {
    INPUT_FIELDS,
    LOCAL_API_REQUIRED,
    LOCAL_API_BASE_URL,
    canonicalString,
    serializeInputValue,
    validateIdentity,
    validateManifest,
    validateAutomationStatus,
    automationStatusView,
    loadAutomationState,
    resolveExactEntry,
    requestFromSearch,
    searchForRequest,
    researchInputsFromNormalizedInputs,
    validateResearchInputsPayload,
    controlRunInputsFromNormalizedInputs,
    localApiRequestFromStaticState,
    validateTargetAllocation,
    validateFactorHoldingHistorySidecarManifest,
    validateFactorHoldingHistorySidecarData,
    validateResult,
    sha256Hex,
    validateIdentityDigest,
    fetchJson,
    fetchLocalApiJson,
    resolveLocalApiResult,
    normalizeControlApiBase,
    isLoopbackOrFilePreview,
    analysisExecutionRoute,
    normalizeControlCapabilities,
    buildControlRunSubmission,
    normalizeControlRunEnvelope,
    fetchControlApiJson,
    resolveControlRun,
    fetchVerifiedControlArtifact,
    controlRunStatusText,
    loadStaticEntryData,
    attachFactorHoldingHistorySidecar,
    resultSourceLabel,
    portfolioHoldingsFromPayload,
    rowReasonCodes,
    adaptSchemaV5Payload,
    pythonBenchmarkCurves,
    curveReturn,
    commonEvaluationPeriodFromPayload,
    periodFactorStatsIncludingDiagnostic,
    seriesPointsThroughDate,
    commonEvaluationSeriesPoints,
    commonEvaluationSeriesSegments,
    dateTickMarks,
    niceReturnTicks,
    nearestChartDate,
    chartPointAtDate,
    clientPointToSvg,
    svgPointToClient,
    scrollLeftToReveal,
    chartIndexForPointer,
    formatChartReturn,
    compactChartSeriesLabel,
    layoutChartEndLabels,
    pythonPerformanceMetric,
    renderPythonPerformanceMetricsTable,
    renderBacktestComparisonSummary,
    factorSelectionEligibility,
    bestFactorHoldingHistoryView,
    factorHoldingHistoryView,
    loadFactorHoldingHistorySidecar,
    selectedDailyWeightRows,
    dailyWeightSymbols,
    renderDailyWeightsTable,
    portfolioViewFromPython,
    factorDiagnosticsView,
    appendFactorHoldingHistoryLoadStatus,
    factorOptionLabel,
    defaultFactorForRun,
    factorComparisonBarClass,
    benchmarkPaletteClass,
    fixedPolicyClass,
    factorSelectionStatusClass,
    factorSelectionStatusLabel,
    factorExclusionReasonLabel,
    factorRankingStatusText,
    factorRiskQualityText,
    factorScoreMethodDescription,
    factorGridAccounting,
    appendBarRow,
    appendFactorRankingBar,
    formatSourceHealth,
    storedScenarioRowLimit,
    syncFactorDependentControls,
    requestedThroughText,
    analysisCountDefinitions,
    universeScopeEvidence,
    CHART_PALETTE_CLASS_MAP,
    THEME_STORAGE_KEY,
    LEGACY_THEME_STORAGE_KEYS,
    EXPLORATION_PERIODS,
    BENCHMARK_LABELS,
  };
}

if (typeof document !== 'undefined') {
  bindThemeToggle();
  bindManualUpdateControls();
  loadBrowserDashboard();
}
