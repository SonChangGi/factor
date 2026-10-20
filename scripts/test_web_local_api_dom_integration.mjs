import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const payload = JSON.parse(readFileSync(process.env.MFL_TEST_PAYLOAD, "utf8"));
const source = readFileSync("factor_lab/web/dashboard.js", "utf8");
const context = vm.createContext({ console, setTimeout, TextDecoder, TextEncoder, URL, URLSearchParams });
vm.runInContext(source, context, { filename: "dashboard.js" });
const api = context.__MFL_WEB_TESTS__;
const normalized = structuredClone(payload.resultIdentity.keyParts.normalizedInputs);
normalized.top_n = Math.min(50, normalized.top_n + 1);
normalized.max_extreme_daily_return = 0.8;
normalized.evaluation_window_days = 126;

const research = api.researchInputsFromNormalizedInputs(normalized);
assert.equal(research.version, "research-inputs-v2");
assert.equal(research.topN, normalized.top_n);
assert.equal(research.maxExtremeDailyReturn, 0.8);
assert.equal(research.evaluationWindowDays, normalized.evaluation_window_days);
assert.equal("evaluationYears" in research, false);
assert.equal(
  JSON.stringify(api.validateResearchInputsPayload(research, normalized)),
  JSON.stringify(research),
);

const legacyNormalized = structuredClone(payload.resultIdentity.keyParts.normalizedInputs);
const legacyResearch = {
  ...api.researchInputsFromNormalizedInputs(legacyNormalized),
  version: "research-inputs-v1",
  evaluationYears: legacyNormalized.evaluation_window_days / 252,
};
assert.equal(
  JSON.stringify(api.validateResearchInputsPayload(legacyResearch, legacyNormalized)),
  JSON.stringify(legacyResearch),
);
assert.throws(
  () => api.validateResearchInputsPayload(
    { ...legacyResearch, evaluationYears: legacyResearch.evaluationYears + 1 },
    legacyNormalized,
  ),
  /legacy researchInputs/,
);
assert.equal(api.serializeInputValue({ kind: "percent" }, 0.8), "80");
assert.equal(api.resultSourceLabel("local_api"), "로컬 API 계산 결과");
assert.match(api.LOCAL_API_REQUIRED, /Python API/);

const baseEntry = {
  resultKey: payload.resultKey,
  normalizedInputs: payload.resultIdentity.keyParts.normalizedInputs,
  identity: payload.resultIdentity,
};
const request = api.localApiRequestFromStaticState({ defaultResultKey: payload.resultKey, entries: [baseEntry] }, normalized);
assert.equal(request.baseEntry.resultKey, payload.resultKey);
assert.equal(request.requestedInputs.top_n, normalized.top_n);
assert.equal(request.requestedInputs.min_evaluation_observations, 126);
assert.equal(request.requestedInputs.min_daily_risk_observations, 126);

console.log("PASS arbitrary form inputs serialize to canonical Python API request");
