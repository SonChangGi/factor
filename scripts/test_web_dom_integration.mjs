import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const html = readFileSync("factor_lab/web/index.html", "utf8");
const css = readFileSync("factor_lab/web/styles.css", "utf8");
const js = readFileSync("factor_lab/web/dashboard.js", "utf8");
const ids = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]));

for (const id of [
  "research-input-form",
  "advanced-research-inputs",
  "factor-select",
  "best-factor",
  "selected-factor",
  "factor-return-chart",
  "backtest-chart",
  "performance-metrics-table",
  "comparison-weight-chart",
  "weight-chart",
  "joint-ranking-chart",
  "joint-ranking-table",
  "holdings-table",
]) assert(ids.has(id), `missing render host: ${id}`);

for (const removed of [
  "canonical-factor",
  "canonical-policy",
  "canonical-target",
  "leader-trend-chart",
  "window-comparison-chart",
  "window-select",
]) assert.equal(ids.has(removed), false, `removed UI host remains: ${removed}`);

const literalSelectors = [...js.matchAll(/(?:querySelector|setText|appendEmpty)\(['"]#([A-Za-z0-9_-]+)/g)]
  .map((match) => match[1]);
const allowedOptional = new Set(["window-select"]);
const missing = [...new Set(literalSelectors)].filter((id) => !ids.has(id) && !allowedOptional.has(id));
assert.deepEqual(missing, [], "literal selectors must resolve to live HTML hosts");

assert.match(html, /<form id="research-input-form"[^>]*novalidate>/);
assert.match(html, /<details id="advanced-research-inputs"/);
assert.match(html, /사용자 선택 팩터[\s\S]*선택 종목 비중/);
assert.match(html, /동일 입력 최고 팩터[\s\S]*최고 팩터 선택 종목 비중/);
assert.doesNotMatch(html, /현재 canonical 목표|기간 수익률 1위/);
assert.doesNotMatch(html, /그래프와 성과표는 현재 입력으로 Python이 계산한 원자료/);
assert.match(js, /factorPortfolios\?\.\[factor\]/);
assert.match(js, /payload\.bestFactor/);
assert.doesNotMatch(js, /renderLeaderTrendChart\(/);
assert.match(css, /\.advanced-research-inputs/);
assert.match(css, /\.line-path\.selected/);
assert.match(css, /\.line-path\.best/);

console.log("PASS streamlined DOM and selected-vs-best portfolio hosts");
