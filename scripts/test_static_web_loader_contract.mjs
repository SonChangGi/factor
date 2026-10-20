import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const payload = JSON.parse(readFileSync(process.env.MFL_TEST_PAYLOAD, "utf8"));
const source = readFileSync("factor_lab/web/dashboard.js", "utf8");
const context = vm.createContext({ console, setTimeout, TextDecoder, TextEncoder, URL, URLSearchParams });
vm.runInContext(source, context, { filename: "dashboard.js" });
const api = context.__MFL_WEB_TESTS__;
const identity = structuredClone(payload.resultIdentity);
identity.canonicalKeyPartsJson = api.canonicalString(identity.keyParts);
const digest = "a".repeat(64);
const entry = {
  presetId: "latest-top20",
  resultKey: identity.resultKey,
  normalizedInputs: identity.keyParts.normalizedInputs,
  identity,
  detail: { path: `results/${identity.resultKey}.json`, sha256: digest, bytes: 100 },
  summary: { path: `summaries/${identity.resultKey}.json`, sha256: digest, bytes: 100 },
};
const manifest = api.validateManifest({
  schemaVersion: 1,
  contract: "momentum-static-result-grid",
  gridVersion: "v1",
  bounded: true,
  maxEntries: 64,
  entryCount: 1,
  defaultResultKey: identity.resultKey,
  entries: [entry],
});
assert.equal(api.resolveExactEntry(manifest, entry.normalizedInputs).resultKey, identity.resultKey);
const changed = structuredClone(entry.normalizedInputs);
changed.top_n += 1;
assert.equal(api.resolveExactEntry(manifest, changed), null, "nearest preset fallback is forbidden");

const request = api.requestFromSearch(manifest, `?preset=latest-top20&top_n=${changed.top_n}`);
assert.equal(request.entry, null);
assert.equal(request.baseEntry.resultKey, identity.resultKey);
assert.equal(request.requestedInputs.top_n, changed.top_n);

const explicitDays = structuredClone(entry.normalizedInputs);
explicitDays.evaluation_window_days = 126;
const explicitDaysSearch = api.searchForRequest(entry.resultKey, explicitDays, entry.presetId);
assert.match(explicitDaysSearch, /evaluation_window_days=126/);
assert.doesNotMatch(explicitDaysSearch, /evaluationYears/);

const legacyYears = entry.normalizedInputs.evaluation_window_days / 252;
assert.equal(Number.isInteger(legacyYears), true);
const legacyRequest = api.requestFromSearch(
  manifest,
  `?result=${entry.resultKey}&evaluationYears=${legacyYears}`,
);
assert.equal(legacyRequest.requestedInputs.evaluation_window_days, legacyYears * 252);

console.log("PASS exact static preset resolution and arbitrary-input handoff");
