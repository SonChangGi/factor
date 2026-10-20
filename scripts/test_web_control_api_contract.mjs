import assert from 'node:assert/strict';
import { createHash, webcrypto } from 'node:crypto';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const payloadPath = process.env.MFL_TEST_PAYLOAD || 'docs/data/grid/v1/latest.json';
const payload = JSON.parse(readFileSync(payloadPath, 'utf8'));
const source = readFileSync('factor_lab/web/dashboard.js', 'utf8');
const html = readFileSync('factor_lab/web/index.html', 'utf8');
const workflow = readFileSync('.github/workflows/controlled-analysis.yml', 'utf8');
const context = vm.createContext({
  console,
  crypto: webcrypto,
  setTimeout,
  TextDecoder,
  TextEncoder,
  URL,
  URLSearchParams,
});
vm.runInContext(source, context, { filename: 'dashboard.js' });
const api = context.__MFL_WEB_TESTS__;

const normalized = structuredClone(payload.resultIdentity.keyParts.normalizedInputs);
const request = JSON.parse(JSON.stringify(api.buildControlRunSubmission(normalized)));
assert.equal(request.inputSchemaVersion, 'momentum/v3');
assert.equal(request.allowFallback, false);
assert.equal(Object.keys(request.inputs).length, 26);
assert.equal('version' in request.inputs, false);
assert.equal('evaluationYears' in request.inputs, false);
assert.equal(request.inputs.evaluationWindowDays, normalized.evaluation_window_days);
assert.equal(request.inputs.topN, normalized.top_n);

const shortWindowRequest = JSON.parse(JSON.stringify(api.buildControlRunSubmission({
  ...normalized,
  evaluation_window_days: 126,
})));
assert.equal(shortWindowRequest.inputSchemaVersion, 'momentum/v3');
assert.equal(shortWindowRequest.inputs.evaluationWindowDays, 126);

const inputFields = Object.keys(request.inputs).sort().map((key) => ({ key }));
const capabilities = JSON.parse(JSON.stringify(api.normalizeControlCapabilities({
  projectId: 'momentum',
  projectName: 'Momentum Factor',
  inputSchemaVersion: 'momentum/v3',
  inputSchemaHash: 'a'.repeat(64),
  configHashAlgorithm: 'momentum-research-inputs-rfc8785-v1',
  acceptsRuns: true,
  inputs: inputFields,
})));
assert.throws(
  () => api.normalizeControlCapabilities({
    projectId: 'momentum',
    projectName: 'Momentum Factor',
    inputSchemaVersion: 'momentum/v2',
    inputSchemaHash: 'a'.repeat(64),
    configHashAlgorithm: 'momentum-research-inputs-rfc8785-v1',
    acceptsRuns: true,
    inputs: inputFields,
  }),
  /schema version/,
);

const observedControlRequests = [];
const controlResponseBytes = new TextEncoder().encode(JSON.stringify({ status: 'ok' }));
const controlFetch = async (url, init) => {
  observedControlRequests.push({
    url,
    init: JSON.parse(JSON.stringify(init)),
  });
  return {
    ok: true,
    status: 200,
    arrayBuffer: async () => controlResponseBytes.buffer,
  };
};
await api.fetchControlApiJson('/v1/runs/momentum-run-0001', {
  base: 'https://api.example.com',
  fetchImpl: controlFetch,
});
await api.fetchControlApiJson('/v1/projects/momentum/runs', {
  base: 'https://api.example.com',
  fetchImpl: controlFetch,
  method: 'POST',
  body: request,
  token: 'owner-session-token',
});
assert.equal(observedControlRequests[0].init.headers.Authorization, undefined);
assert.equal(
  observedControlRequests[1].init.headers.Authorization,
  'Bearer owner-session-token',
);

const envelope = {
  projectId: 'momentum',
  runId: 'momentum-run-0001',
  status: 'queued',
  inputSchemaVersion: capabilities.inputSchemaVersion,
  inputSchemaHash: capabilities.inputSchemaHash,
  configHashAlgorithm: capabilities.configHashAlgorithm,
  configHash: 'b'.repeat(64),
  effectiveConfigHash: 'b'.repeat(64),
  requestedInputs: request.inputs,
  normalizedInputs: request.inputs,
  effectiveInputs: request.inputs,
  ignoredInputs: [],
  allowFallback: false,
  fallbacks: [],
  fallbackUsed: false,
  fallbackReason: null,
};
const queued = JSON.parse(JSON.stringify(api.normalizeControlRunEnvelope(
  envelope,
  { inputs: request.inputs },
  capabilities,
)));
for (const status of ['dispatched', 'running', 'validating', 'published']) {
  const next = api.normalizeControlRunEnvelope({ ...envelope, status }, queued, capabilities);
  assert.equal(next.status, status);
}
assert.throws(
  () => api.normalizeControlRunEnvelope(
    { ...envelope, configHash: 'c'.repeat(64) },
    queued,
    capabilities,
  ),
  /configHash/i,
);
assert.throws(
  () => api.normalizeControlRunEnvelope(
    {
      ...envelope,
      effectiveInputs: { ...request.inputs, topN: request.inputs.topN + 1 },
    },
    queued,
    capabilities,
  ),
  /effectiveInputs/,
);
assert.throws(
  () => api.normalizeControlRunEnvelope(
    {
      ...envelope,
      ignoredInputs: ['topN'],
    },
    queued,
    capabilities,
  ),
  /무시/,
);
assert.throws(
  () => api.normalizeControlRunEnvelope(
    {
      ...envelope,
      fallbackUsed: true,
      fallbackReason: 'unexpected',
      fallbacks: [{ input: 'topN' }],
    },
    queued,
    capabilities,
  ),
  /fallback/,
);
assert.throws(
  () => api.normalizeControlRunEnvelope(
    { ...envelope, status: 'queued' },
    { ...queued, status: 'running' },
    capabilities,
  ),
  /되돌아/,
);

assert.equal(api.normalizeControlApiBase('https://api.example.com/'), 'https://api.example.com');
assert.equal(api.normalizeControlApiBase('http://127.0.0.1:8000/'), 'http://127.0.0.1:8000');
assert.throws(() => api.normalizeControlApiBase('http://api.example.com'), /HTTPS/);
assert.throws(() => api.normalizeControlApiBase('https://token@example.com'), /인증정보/);
assert.throws(() => api.normalizeControlApiBase('https://api.example.com?token=x'), /쿼리/);
assert.equal(api.isLoopbackOrFilePreview({ protocol: 'https:', hostname: 'sonchanggi.github.io' }), false);
assert.equal(api.isLoopbackOrFilePreview({ protocol: 'http:', hostname: '127.0.0.1' }), true);
assert.equal(api.isLoopbackOrFilePreview({ protocol: 'file:', hostname: '' }), true);
assert.equal(
  api.analysisExecutionRoute(
    'https://quant-control-api.onrender.com',
    { protocol: 'https:', hostname: 'sonchanggi.github.io' },
  ),
  'remote',
);
assert.equal(
  api.analysisExecutionRoute(null, { protocol: 'https:', hostname: 'sonchanggi.github.io' }),
  'blocked',
);
assert.equal(
  api.analysisExecutionRoute(null, { protocol: 'http:', hostname: '127.0.0.1' }),
  'local',
);

const artifactBytes = new TextEncoder().encode(JSON.stringify(payload));
const artifactSha = createHash('sha256').update(artifactBytes).digest('hex');
const sourceHash = createHash('sha256')
  .update(api.canonicalString(payload.data.inputSha256))
  .digest('hex');
const published = {
  ...envelope,
  status: 'published',
  dataAsOf: payload.data.asOf,
  calculatedAt: payload.generatedAtUtc,
  codeVersion: `github:SonChangGi/momentum-factor-lab@${'1'.repeat(40)}`,
  dataIdentity: {
    source: 'momentum-live-market-input-hashes',
    sourceHash,
    dataAsOf: payload.data.asOf,
  },
  artifact: {
    url: (
      'https://sonchanggi.github.io/factor/data/control-runs/v1/'
      + `momentum-run-0001/${payload.resultKey}.json`
    ),
    sha256: artifactSha,
    byteSize: artifactBytes.byteLength,
    contractVersion: 'momentum/schema-v5-control-result-v1',
  },
  payload: {
    schemaVersion: payload.schemaVersion,
    resultKey: payload.resultKey,
    resultIdentity: payload.resultIdentity,
    researchInputs: payload.researchInputs,
    dataIdentity: {
      source: 'momentum-live-market-input-hashes',
      sourceHash,
      dataAsOf: payload.data.asOf,
    },
  },
};
let observedArtifactRequest = null;
const fetched = await api.fetchVerifiedControlArtifact(published, {
  fetchImpl: async (url, init) => {
    observedArtifactRequest = {
      url,
      init: JSON.parse(JSON.stringify(init)),
    };
    return {
      ok: true,
      status: 200,
      arrayBuffer: async () => artifactBytes.buffer,
    };
  },
});
assert.equal(fetched.resultKey, payload.resultKey);
assert.equal(observedArtifactRequest.url, published.artifact.url);
assert.deepEqual(observedArtifactRequest.init, {
  cache: 'no-store',
  credentials: 'omit',
  referrerPolicy: 'no-referrer',
  redirect: 'error',
});
for (const forbiddenUrl of [
  published.artifact.url.replace('sonchanggi.github.io', 'artifacts.example.com'),
  published.artifact.url.replace('https://', 'http://'),
  published.artifact.url.replace('sonchanggi.github.io', 'token@sonchanggi.github.io'),
  published.artifact.url.replace('sonchanggi.github.io', 'sonchanggi.github.io:4443'),
  published.artifact.url.replace('momentum-run-0001', 'momentum-run-0002'),
  published.artifact.url.replace(payload.resultKey, 'e'.repeat(64)),
  `${published.artifact.url}?download=1`,
  `${published.artifact.url}#result`,
]) {
  let forbiddenFetchCalled = false;
  await assert.rejects(
    api.fetchVerifiedControlArtifact(
      {
        ...published,
        artifact: { ...published.artifact, url: forbiddenUrl },
      },
      {
        fetchImpl: async () => {
          forbiddenFetchCalled = true;
          throw new Error('forbidden artifact URL reached fetch');
        },
      },
    ),
    /artifact URL/,
  );
  assert.equal(forbiddenFetchCalled, false);
}
await assert.rejects(
  api.fetchVerifiedControlArtifact(
    {
      ...published,
      artifact: { ...published.artifact, sha256: 'd'.repeat(64) },
    },
    {
      fetchImpl: async () => ({
        ok: true,
        status: 200,
        arrayBuffer: async () => artifactBytes.buffer,
      }),
    },
  ),
  /SHA-256/,
);

assert.match(
  html,
  /<meta name="quant-run-api-base" content="https:\/\/quant-control-api\.onrender\.com"\s*\/>/,
);
assert.match(html, /id="remote-control-token"[\s\S]*?autocomplete="off"/);
assert.match(html, /id="analysis-settings"[^>]*>/);
assert.doesNotMatch(html, /id="analysis-settings"[^>]*\sopen(?:\s|>)/);
assert.doesNotMatch(source, /localStorage[^;]*(?:token|bearer)|sessionStorage[^;]*(?:token|bearer)/i);
assert.match(source, /Authorization = `Bearer \$\{options\.token\}`/);
assert.match(source, /'Idempotency-Key': controlIdempotencyKey\(\)/);
const resolveControlRunSource = source.slice(
  source.indexOf('async function resolveControlRun'),
  source.indexOf('async function fetchVerifiedControlArtifact'),
);
assert.match(
  resolveControlRunSource,
  /async function resolveControlRun\(submission, loadToken, options = \{\}\)/,
);
assert.doesNotMatch(resolveControlRunSource, /\btoken\b|Authorization/);
const loadRemoteControlResultSource = source.slice(
  source.indexOf('async function loadRemoteControlResult'),
  source.indexOf('function bindBrowserContractControls'),
);
assert.match(loadRemoteControlResultSource, /method: 'POST'[\s\S]*token: tokenValue/);
assert.match(source, /if \(!sameJson\(currentDraft, normalizedResultInputs\)\) preservedDraft = currentDraft/);
assert.match(source, /if \(preservedDraft\) fillResearchForm\(baseEntry, preservedDraft\)/);
assert.match(source, /const CONTROL_API_POLL_INTERVAL_MS = 5000;/);
assert.match(source, /const CONTROL_API_MAX_POLLS = 2880;/);
assert.match(source, /submit\.textContent = '분석 API 연결 필요'/);
assert.match(source, /const controlCapabilities = await controlApiInitialization;[\s\S]*renderResearchDraftState\(\);/);

assert.match(workflow, /research_inputs_json:/);
assert.match(workflow, /control_run_id:/);
assert.match(workflow, /control_input_schema_version:/);
assert.match(workflow, /control_input_schema_hash:/);
assert.match(workflow, /control_config_hash_algorithm:/);
assert.match(workflow, /control_config_hash:/);
assert.match(workflow, /python -m factor_lab\.control_run/);
assert.match(workflow, /--allow-fallback "\$\{ALLOW_FALLBACK\}"/);
assert.match(workflow, /result-manifest/);
assert.match(workflow, /QUANT_CONTROL_WORKER_CALLBACK_TOKEN/);
assert.match(workflow, /timeout-minutes: 210/);
assert.match(workflow, /always\(\) && failure\(\)/);
assert.match(workflow, /\/v1\/internal\/runs\/\$\{CONTROL_RUN_ID\}\/failure/);
assert.match(workflow, /"providerRunId": f"github-actions:\{run_id\}"/);
assert.match(workflow, /"errorCode": "worker_workflow_failed"/);
assert.equal((workflow.match(/from urllib\.parse import urlsplit, urlunsplit/g) || []).length, 2);
assert.equal((workflow.match(/parsed(?:_callback_base)?\.scheme != "https"/g) || []).length, 2);
assert.equal((workflow.match(/parsed(?:_callback_base)?\.username/g) || []).length, 2);
assert.equal((workflow.match(/parsed(?:_callback_base)?\.password/g) || []).length, 2);
assert.equal((workflow.match(/parsed(?:_callback_base)?\.query/g) || []).length, 2);
assert.equal((workflow.match(/parsed(?:_callback_base)?\.fragment/g) || []).length, 2);
assert.equal((workflow.match(/--proto '=https'/g) || []).length, 2);

console.log('PASS common remote control API and immutable artifact binding contract');
