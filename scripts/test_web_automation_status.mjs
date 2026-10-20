import assert from 'node:assert/strict';
import { webcrypto, createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync('factor_lab/web/dashboard.js', 'utf8');
const now = Date.parse('2026-09-18T03:00:00Z');
class FixedDate extends Date { static now() { return now; } }
const context = vm.createContext({
  console, setTimeout, TextDecoder, TextEncoder, URL, URLSearchParams,
  Date: FixedDate, crypto: webcrypto,
});
vm.runInContext(source, context, { filename: 'dashboard.js' });
const api = context.__MFL_WEB_TESTS__;
const reference = {
  resultKey: 'a'.repeat(64), dataAsOf: '2026-09-16',
  generatedAtUtc: '2026-09-17T00:08:47Z', path: 'data/dashboard.json',
};
const payload = {
  resultKey: reference.resultKey, generatedAtUtc: reference.generatedAtUtc,
  data: { asOf: reference.dataAsOf },
};
const identity = { keyParts: { marketSnapshot: { dataAsOf: reference.dataAsOf } } };
const defaultEntry = { resultKey: reference.resultKey, identity };
const manifest = { defaultResultKey: reference.resultKey, entries: [defaultEntry] };
const available = {
  schemaVersion: 1, contract: 'momentum-dashboard-automation-status',
  project: 'momentum-factor-lab', state: 'available', reasonCode: 'published',
  attemptedAtUtc: '2026-09-18T02:00:00Z', targetDataAsOf: reference.dataAsOf,
  publication: { updated: true, lastGoodPreserved: false }, lastGood: reference,
};
const degraded = {
  ...available, state: 'degraded', reasonCode: 'no_comparable_factor',
  targetDataAsOf: '2026-09-17',
  publication: { updated: false, lastGoodPreserved: true },
};
const view = (automation, options = {}) => api.automationStatusView({
  automation, payload, manifest, source: 'static_grid',
  summary: { recommendation_output_label: 'Research signals (not tradable)' }, ...options,
});
const loaded = (status) => ({ phase: 'loaded', status, reference });

assert.equal(view({ phase: 'loading' }).title, '자동화 상태 확인 중');
assert.equal(view(loaded(available)).title, '수집·검증 완료');
assert.equal(view(loaded(available)).tone, 'ok');
assert.equal(view(loaded(degraded)).title, '갱신 보류');
assert.match(view(loaded(degraded)).detail, /마지막 검증 기준일 2026-09-16.*목표일 2026-09-17.*공통 평가기간/);
assert.equal(view(loaded({ ...degraded, state: 'failed', reasonCode: 'execution_failed' })).title, '갱신 실패');
assert.match(view(loaded({ ...degraded, reasonCode: 'stale_market_data' })).detail, /시장 데이터 미확보/);
assert.match(view(loaded({ ...degraded, reasonCode: 'incomplete_market_session' })).detail, /완료되지 않은 시장 거래일/);
assert.equal(view(loaded({ ...degraded, state: 'unavailable' })).title, '갱신 실패');

for (const mutation of [
  null,
  { ...available, schemaVersion: 999 },
  { ...available, state: 'unexpected' },
  { ...available, attemptedAtUtc: '2026-09-16T02:00:00Z' },
  { ...available, attemptedAtUtc: '2026-09-18T04:00:00Z' },
  { ...available, attemptedAtUtc: '2026-09-18T02:00:00' },
  { ...available, attemptedAtUtc: '2026-02-30T02:00:00Z' },
  { ...available, targetDataAsOf: '2026-09-17' },
  { ...available, lastGood: { ...reference, resultKey: 'b'.repeat(64) } },
  { ...available, lastGood: { ...reference, dataAsOf: '2026-09-15' } },
  { ...available, lastGood: { ...reference, generatedAtUtc: '2026-09-17T01:00:00Z' } },
  { ...available, lastGood: { ...reference, path: 'unrelated.json' } },
  { ...available, publication: { updated: false } },
  { ...degraded, publication: { updated: true, lastGoodPreserved: true } },
]) {
  const result = view(loaded(mutation));
  assert.equal(result.title, '자동화 상태 확인 불가');
  assert.notEqual(result.tone, 'ok');
  assert.equal(result.attemptedAtUtc, null);
}
assert.equal(view({ phase: 'error' }).title, '자동화 상태 확인 불가');
assert.equal(view(loaded(available), { payload: null }).title, '검증 결과 없음');
assert.equal(view(loaded(available), {
  payload: { ...payload, generatedAtUtc: '2026-09-18T01:00:00Z' },
}).title, '자동화 상태 확인 불가');

const historical = { ...payload, resultKey: 'b'.repeat(64), data: { asOf: '2026-09-04' } };
const historicalView = view(loaded(degraded), { payload: historical });
assert.equal(historicalView.title, '과거 기준 조회');
assert.match(historicalView.detail, /조회 기준일 2026-09-04/);
assert.equal(historicalView.automationTitle, '갱신 보류');
assert.match(historicalView.automationDetail, /마지막 검증 기준일 2026-09-16/);
assert.equal(view(loaded(available), { payload: { ...payload, resultKey: 'c'.repeat(64) } }).title, '수집·검증 완료');
assert.equal(view(loaded(degraded), { source: 'local_api' }).title, '개별 검증 결과');
assert.equal(view(loaded(degraded), { source: 'remote_api' }).automationTitle, '갱신 보류');
const unknownReason = view(loaded({ ...degraded, reasonCode: '<script>secret</script>', message: 'PRIVATE' }));
assert.doesNotMatch(unknownReason.detail, /script|secret|PRIVATE/);

const summary = {
  resultKey: reference.resultKey, dataAsOf: reference.dataAsOf,
  generatedAt: reference.generatedAtUtc, resultIdentity: identity,
};
const summaryBytes = new TextEncoder().encode(JSON.stringify(summary));
defaultEntry.summary = {
  path: `summaries/${reference.resultKey}.json`, bytes: summaryBytes.length,
  sha256: createHash('sha256').update(summaryBytes).digest('hex'),
};
const calls = [];
const response = (value) => ({ ok: true, arrayBuffer: async () => new TextEncoder().encode(JSON.stringify(value)).buffer });
const options = {
  pageUrl: 'https://example.test/momentum-factor-lab/',
  manifestUrl: 'https://example.test/momentum-factor-lab/data/grid/v1/manifest.json',
  fetchImpl: async (url, config) => {
    calls.push({ url, config });
    return response(url.endsWith('automation-status.json') ? degraded : summary);
  },
};
const state = await api.loadAutomationState(manifest, options);
assert.equal(state.phase, 'loaded');
assert.equal(view(state).title, '갱신 보류');
assert.equal(calls.length, 2);
assert(calls.every(({ config }) => config.cache === 'no-store'));
assert(calls.some(({ url }) => url === 'https://example.test/momentum-factor-lab/data/automation-status.json'));

for (const fetchImpl of [
  async () => { throw new Error('offline'); },
  async () => ({ ok: false, status: 404 }),
  async () => ({ ok: true, arrayBuffer: async () => new TextEncoder().encode('not json').buffer }),
  async (url) => response(url.endsWith('automation-status.json') ? degraded : { ...summary, dataAsOf: '2026-09-15' }),
]) {
  const failed = await api.loadAutomationState(manifest, { ...options, fetchImpl });
  assert.equal(failed.phase, 'error');
  assert.equal(view(failed).title, '자동화 상태 확인 불가');
}

console.log('PASS automation status binding, preserved results, historical presets, and fail-closed loading');
