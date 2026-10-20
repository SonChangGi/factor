import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const html = readFileSync("factor_lab/web/index.html", "utf8");
const css = readFileSync("factor_lab/web/styles.css", "utf8");

assert.match(html, /Factor/);
assert.match(html, /팩터 점수 70% · 후행 거래대금 30%/);
assert.match(html, /class="core-research-inputs"/);
assert.match(html, /<details id="advanced-research-inputs"/);
assert.match(html, /최대 일간 절대 수익률[\s\S]*max="10000"/);
assert.match(html, /<form id="research-input-form"[^>]*novalidate>/);
assert.match(html, /선택 팩터 · 최고 팩터 · 시장/);
assert.match(html, /사용자 선택 팩터[\s\S]*선택 종목 비중/);
assert.match(html, /동일 입력 최고 팩터[\s\S]*최고 팩터 선택 종목 비중/);
assert.doesNotMatch(html, /현재 canonical 목표|동일가중|기간 수익률 1위/);
assert.match(css, /\.core-research-inputs/);
assert.match(css, /\.advanced-research-input-grid/);
assert.match(css, /@media \(max-width: 720px\)/);
assert(
  html.indexOf('class="cards result-cards"') < html.indexOf('id="visual-dashboard"'),
  'core result cards must precede the primary chart',
);
assert(
  html.indexOf('id="visual-dashboard"') < html.indexOf('class="controls controls-enhanced"'),
  'primary chart must precede comparison and analysis controls',
);

console.log("PASS result-first fixed-method design contract");
