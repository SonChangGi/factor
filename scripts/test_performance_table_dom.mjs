import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const payload = JSON.parse(readFileSync(process.env.MFL_TEST_PAYLOAD, "utf8"));
const source = readFileSync("factor_lab/web/dashboard.js", "utf8");
const context = vm.createContext({ console, setTimeout, TextDecoder, TextEncoder, URL, URLSearchParams });
vm.runInContext(source, context, { filename: "dashboard.js" });
const api = context.__MFL_WEB_TESTS__;

const period = api.commonEvaluationPeriodFromPayload(payload);
assert(period);
assert.equal(period.returnObservationCount, payload.config.evaluation_window_days);
assert.equal(period.startDate, payload.performance.dates[0]);
assert.equal(period.endDate, payload.performance.dates.at(-1));

const selectedFactor = Object.keys(payload.performance.factorCurves)
  .find((factor) => factor !== payload.bestFactor);
const selectedSeries = {
  dates: payload.performance.dates,
  equity: payload.performance.factorCurves[selectedFactor],
};
const bestSeries = {
  dates: payload.performance.dates,
  equity: payload.performance.factorCurves[payload.bestFactor],
};
const selected = api.commonEvaluationSeriesSegments(selectedSeries, period);
const best = api.commonEvaluationSeriesSegments(bestSeries, period);
assert.equal(
  selected.points.length + selected.missingCount,
  period.returnObservationCount + 1,
);
assert.equal(
  best.points.length + best.missingCount,
  period.returnObservationCount + 1,
);
assert.equal(selected.points[0].normalized, 1);
assert.equal(best.points[0].normalized, 1);
assert.equal(
  best.points.at(-1).normalized - 1,
  payload.performance.periods.find((row) => row.key === "FULL").factors[payload.bestFactor].cumulativeReturn,
);
assert.doesNotMatch(source, /내부 평가 불가 \d+일/);
assert.doesNotMatch(source, /그래프 범주에 MDD/);

console.log("PASS full-period first-return and concise performance comparison contract");
