import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const js = readFileSync("factor_lab/web/dashboard.js", "utf8");
const css = readFileSync("factor_lab/web/styles.css", "utf8");

assert.match(js, /const CHART_PALETTE_CLASS_MAP = Object\.freeze/);
assert.match(js, /bars: Object\.freeze\([\s\S]*focal:[\s\S]*best:/);
assert.match(js, /policies: Object\.freeze\([\s\S]*score_liquidity_rank/);
assert.match(js, /benchmarkPaletteClass\(series\.symbol\)/);
assert.match(css, /\.line-path\.selected/);
assert.match(css, /\.line-path\.best/);
assert.match(css, /\.line-path\.benchmark-spy/);
assert.match(css, /\.line-path\.benchmark-ixic/);
assert.match(css, /\.line-path\.benchmark-qqq/);
assert.match(js, /layoutChartEndLabels/);
assert.match(js, /chart-series-value/);
assert.match(css, /\.chart-end-label\.benchmark-spy/);
assert.match(css, /\.chart-series-point\.benchmark-qqq/);
assert.match(css, /\.policy-score-liquidity-rank/);
assert.match(css, /\[data-theme="dark"\]/);

console.log("PASS fixed-method chart palette contract");
