import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const html = readFileSync("momentum_factor_lab/web/index.html", "utf8");
const css = readFileSync("momentum_factor_lab/web/styles.css", "utf8");
const sharedNav = readFileSync("momentum_factor_lab/web/shared-nav.css", "utf8");
const source = readFileSync("momentum_factor_lab/web/dashboard.js", "utf8");
const publishedHtml = readFileSync("docs/index.html", "utf8");
assert.equal(readFileSync("docs/assets/styles.css", "utf8"), css);
assert.equal(readFileSync("docs/assets/dashboard.js", "utf8"), source);
const assetVersion = createHash("sha256").update(css).update(source).digest("hex").slice(0, 12);
assert.equal((publishedHtml.match(new RegExp(`\\?v=${assetVersion}`, "g")) || []).length, 2);
const context = vm.createContext({ console, setTimeout, TextDecoder, TextEncoder, URL, URLSearchParams });
vm.runInContext(source, context, { filename: "dashboard.js" });
const api = context.__MFL_WEB_TESTS__;

assert(api, "web test API must be exported without a DOM");
assert.equal(api.THEME_STORAGE_KEY, "quant-research-theme");
assert.deepEqual(
  Array.from(api.LEGACY_THEME_STORAGE_KEYS),
  [
    "quant-dashboard-theme",
    "quant-calm-theme",
    "dram-price-theme",
    "etf-tracking-theme",
    "momentum-factor-theme",
    "sox-theme",
  ],
);

const expectedNavigation = [
  ["Quant Research Hub", "https://sonchanggi.github.io/quant-dashboard/"],
  ["Fear &amp; Greed", "https://sonchanggi.github.io/fearNgreed/"],
  ["Momentum", "https://sonchanggi.github.io/momentum-factor-lab/"],
  ["DRAM", "https://sonchanggi.github.io/dram-price/"],
  ["Best Factor", "https://sonchanggi.github.io/best-factor/"],
  ["ETF", "https://sonchanggi.github.io/etf-tracking/"],
  ["SOX", "https://sonchanggi.github.io/sox/"],
  ["Regime", "https://sonchanggi.github.io/regime/"],
  ["News", "https://sonchanggi.github.io/news/"],
];
let previousIndex = -1;
for (const [label, href] of expectedNavigation) {
  const index = html.indexOf(`href="${href}"`);
  assert(index > previousIndex, `${label} must follow the canonical project navigation order`);
  previousIndex = index;
}
const navigation = html.match(/<nav class="site-nav quant-shared-nav"[\s\S]*?<\/nav>/)?.[0] || "";
assert.match(html, /<body id="top" class="has-quant-shared-nav">/);
assert.match(html, /assets\/shared-nav\.css\?v=__SHARED_NAV_VERSION__/);
assert.equal((navigation.match(/href="https:\/\/sonchanggi\.github\.io\//g) || []).length, 9);
assert.equal((navigation.match(/aria-current="page"/g) || []).length, 1);
assert.match(navigation, /quant-shared-nav__brand[^>]*href="https:\/\/sonchanggi\.github\.io\/quant-dashboard\/"/);
assert.doesNotMatch(navigation, />Hub<\/a>/);
assert.match(sharedNav, /position:\s*fixed\s*!important/);
assert.match(sharedNav, /--quant-shared-nav-height:\s*59px/);
assert.match(sharedNav, /--quant-shared-nav-height:\s*101px/);
assert.match(sharedNav, /grid-template-rows:\s*50px 44px/);

for (const id of [
  "backtest-series-controls",
  "backtest-date-input",
  "backtest-date-reset",
  "backtest-value-card",
  "backtest-active-date",
  "backtest-active-series",
  "backtest-active-value",
  "backtest-chart",
]) {
  assert.match(html, new RegExp(`id="${id}"`));
}
assert.match(html, /id="backtest-chart"[\s\S]*tabindex="0"/);
assert.match(html, /id="backtest-chart"[\s\S]*aria-describedby="backtest-chart-help"/);
assert.match(html, /id="backtest-chart"[\s\S]*aria-keyshortcuts="ArrowLeft ArrowRight Home End"/);
assert.match(html, /id="analysis-settings" class="dashboard-disclosure/);
assert.doesNotMatch(html, /id="analysis-settings"[^>]*\bopen\b/);
assert.doesNotMatch(html, /자동 예약 실행(?:과 watchdog 예약)?은 현재 중지/);
assert.match(html, /데이터 · 출처 · 운영 상세/);
assert.doesNotMatch(html, /현재 입력에서 64개 모멘텀 팩터를 비교해/);
assert.doesNotMatch(html, /현재 입력의 Python 팩터 랭킹/);
assert.doesNotMatch(html, /핵심 조건과 고급 가드레일을 설정합니다/);
assert.doesNotMatch(html, /같은 입력과 70\/30 고정 비중으로 비교한 전체 랭킹/);
assert.doesNotMatch(html, /계열과 날짜를 탐색해도 공식 결과와 분석 입력은 바뀌지 않습니다/);
assert.doesNotMatch(html, /비교 팩터만 바뀌며 Python 최고 팩터는 유지됩니다/);
assert.doesNotMatch(html, /<section class="disclaimer">/);
assert(
  html.indexOf('class="operations-note"') > html.indexOf('class="supporting-detail-stack"'),
  "the single research-use note belongs inside the closed operations detail",
);

assert.equal(api.nearestChartDate(["2026-07-17", "2026-07-20", "2026-07-21"], "2026-07-19"), "2026-07-20");
assert.equal(api.nearestChartDate(["2026-07-17", "2026-07-20"], null), "2026-07-20");
assert.deepEqual(
  api.chartPointAtDate([{ date: "2026-07-21", normalized: 1.25 }], "2026-07-21"),
  { date: "2026-07-21", normalized: 1.25 },
);
assert.equal(api.chartPointAtDate([{ date: "2026-07-21", normalized: 1.25 }], "2026-07-20"), null);
assert.equal(api.formatChartReturn(0.1234), "+12.34%");
assert.equal(api.formatChartReturn(-0.2), "-20.00%");
assert.equal(api.formatChartReturn(null), "관측 없음");
assert.equal(api.compactChartSeriesLabel("123456789", 6), "12345…");
assert.deepEqual(
  Array.from(
    api.layoutChartEndLabels(
      [{ key: "a", y: 95 }, { key: "b", y: 96 }, { key: "c", y: 97 }],
      { minY: 20, maxY: 100, gap: 20 },
    ),
    ({ key, labelY }) => ({ key, labelY }),
  ),
  [
    { key: "a", labelY: 60 },
    { key: "b", labelY: 80 },
    { key: "c", labelY: 100 },
  ],
);

assert.match(source, /previewSeriesKey/);
assert.match(source, /previewDate/);
assert.match(source, /event\.pointerType === 'touch'/);
assert.match(source, /event\.key === 'ArrowLeft'/);
assert.match(source, /event\.key === 'ArrowRight'/);
assert.match(source, /event\.key === 'Home'/);
assert.match(source, /event\.key === 'End'/);
assert.match(source, /date === allDates\.at\(-1\) \? width : xForDate\(date\)/);
assert.match(
  html,
  /평가 기간\(거래일\)[\s\S]*id="input-evaluation-window-days"[^>]*min="21"[^>]*max="2520"[^>]*step="1"/,
);
assert.doesNotMatch(html, /id="input-evaluation-years"/);
assert.doesNotMatch(html, /id="input-evaluation-window-days"[^>]*(?:readonly|aria-readonly)/);
assert.match(html, /id="research-draft-status"[^>]*data-state="applied"/);
assert.doesNotMatch(source, /syncEvaluationWindowFromYears/);
assert.doesNotMatch(source, /function renderWithBusy/);

const fakeSvg = {
  createSVGPoint() {
    return {
      x: 0,
      y: 0,
      matrixTransform(matrix) {
        return matrix.map(this.x, this.y);
      },
    };
  },
  getScreenCTM() {
    return {
      map(x, y) {
        return { x: 240 + x * 0.82, y: 30 + y * 0.82 };
      },
      inverse() {
        return {
          map(x, y) {
            return { x: (x - 240) / 0.82, y: (y - 30) / 0.82 };
          },
        };
      },
    };
  },
};
for (const svgX of [70, 404, 738]) {
  const client = api.svgPointToClient(fakeSvg, svgX, 110);
  const restored = api.clientPointToSvg(fakeSvg, client.x, client.y);
  assert.ok(Math.abs(restored.x - svgX) < 1e-9);
}
assert.equal(api.scrollLeftToReveal({
  scrollLeft: 0,
  clientWidth: 390,
  scrollWidth: 720,
  targetX: 70,
}), 0);
assert.equal(api.scrollLeftToReveal({
  scrollLeft: 0,
  clientWidth: 390,
  scrollWidth: 720,
  targetX: 690,
}), 330);
const pointerBase = {
  plotLeft: 78,
  plotWidth: 897,
  count: 757,
  hitLeft: 100,
  hitRight: 997,
};
assert.equal(api.chartIndexForPointer({ ...pointerBase, clientX: 102, svgX: 80 }), 0);
assert.equal(api.chartIndexForPointer({ ...pointerBase, clientX: 548.5, svgX: 526.5 }), 378);
assert.equal(api.chartIndexForPointer({ ...pointerBase, clientX: 995, svgX: 973 }), 756);

assert.match(css, /\.chart-series-button/);
assert.match(css, /\.chart-series-value/);
assert.match(css, /\.chart-date-guide/);
assert.match(css, /\.chart-active-point/);
assert.match(css, /\.chart-series-point/);
assert.match(css, /\.chart-end-label/);
assert.match(css, /\.interactive-line-chart svg\s*\{[\s\S]*?min-width:\s*980px;[\s\S]*?height:\s*auto;/);
assert.match(css, /min-height:\s*44px/);
assert.match(css, /font-size:\s*max\(\.75rem,\s*12px\)/);
assert.match(css, /@media \(max-width: 640px\)/);
assert.match(css, /Quant Research common design v1\.2/);
assert.match(css, /body\s*\{[\s\S]*?font-size:\s*15px;[\s\S]*?line-height:\s*1\.55;/);
assert.match(css, /\.site-nav\s*\{[\s\S]*?min-height:\s*58px;/);
assert.match(css, /\.site-nav-links a,[\s\S]*?font-size:\s*12px;[\s\S]*?font-weight:\s*650;/);
assert.match(css, /\.result-cards\s*\{[\s\S]*?grid-auto-flow:\s*column;[\s\S]*?overflow-x:\s*auto;/);
assert.match(css, /\.chart-series-controls\s*\{[\s\S]*?flex-wrap:\s*nowrap;[\s\S]*?overflow-x:\s*auto;/);
assert.match(css, /\.chart-inspector > div\s*\{\s*min-width:\s*0;\s*\}/);
assert.match(css, /\.chart-series-controls\s*\{[\s\S]*?width:\s*100%;[\s\S]*?max-width:\s*100%;[\s\S]*?overflow-x:\s*auto;/);

console.log("PASS Quant Research common design v1.2 Momentum contract");
