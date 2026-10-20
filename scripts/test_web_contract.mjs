import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const payload = JSON.parse(readFileSync(process.env.MFL_TEST_PAYLOAD, "utf8"));
const source = readFileSync("factor_lab/web/dashboard.js", "utf8");
const context = vm.createContext({ console, setTimeout, TextDecoder, TextEncoder, URL, URLSearchParams });
vm.runInContext(source, context, { filename: "dashboard.js" });
const api = context.__MFL_WEB_TESTS__;

assert(api, "web test API must be exported without a DOM");
assert.equal(payload.schemaVersion, 5);
assert.equal(payload.weightingPolicy, "score_liquidity_rank");
assert.equal(payload.weightingMethodology.optimized, false);
assert.equal(payload.factorRanking.length, 64);
assert.equal(payload.factorAccounting.expectedIndependentFactorCount, 61);
assert.equal(payload.factorAccounting.evaluatedIndependentFactorCount, 61);
assert.equal(payload.factorAccounting.diagnosticAliasFactorCount, 3);
assert.equal(Object.keys(payload.factorPortfolios).length, 64);
assert.deepEqual(payload.bestFactorPortfolio, payload.factorPortfolios[payload.bestFactor]);
assert.equal(payload.performance.dates.length, payload.config.evaluation_window_days + 1);
assert.equal(payload.performance.factorCurves[payload.bestFactor][0], 1);

for (const removed of [
  "currentResearchTarget",
  "selectedFactor",
  "selectedWeightingPolicy",
  "factorPolicyRanking",
  "gridAccounting",
  "policyDiagnostics",
]) {
  assert.equal(Object.hasOwn(payload, removed), false, `removed schema field leaked: ${removed}`);
}

const best = api.portfolioHoldingsFromPayload(payload, payload.bestFactor);
const comparisonFactor = Object.keys(payload.factorPortfolios).find((factor) => factor !== payload.bestFactor);
const comparison = api.portfolioHoldingsFromPayload(payload, comparisonFactor);
assert.equal(best.selectedFactor, payload.bestFactor);
assert.equal(comparison.selectedFactor, comparisonFactor);
assert.equal(best.weightingPolicyId, payload.weightingPolicy);
assert.equal(comparison.weightingPolicyId, payload.weightingPolicy);
assert.deepEqual(
  comparison.weighted.map((row) => row.symbol),
  payload.factorPortfolios[comparisonFactor].weights.map((row) => row.symbol),
  "the selected-factor portfolio must come from its own Python factor key",
);

const accounting = api.factorGridAccounting(payload);
assert.equal(accounting.totalOutputRowCount, 64);
assert.equal(accounting.expectedIndependentFactorCount, 61);
assert.match(api.factorScoreMethodDescription(payload), /5%~95%/);
assert.match(api.factorScoreMethodDescription(payload), /3개/);
const customMethodPayload = structuredClone(payload);
customMethodPayload.config.score_winsor_lower = 0.1;
customMethodPayload.config.score_winsor_upper = 0.9;
customMethodPayload.config.stability_periods = 5;
assert.match(api.factorScoreMethodDescription(customMethodPayload), /10%~90%/);
assert.match(api.factorScoreMethodDescription(customMethodPayload), /5개/);
const incompleteRisk = { observations: 756, daily_risk_observations: 752, quote_gap_observations: 4, valuation_coverage_ratio: 0.99, risk_metrics_exact: false };
assert.match(api.factorRiskQualityText(incompleteRisk), /불완전/);
assert.match(api.factorRiskQualityText(incompleteRisk), /quote gap 4/);
assert.match(api.factorRiskQualityText(incompleteRisk), /MDD는 관측 종가 기준 하한/);

console.log("PASS schema-v5 fixed-method selected-vs-best web contract");
