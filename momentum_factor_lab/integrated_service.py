"""One execution path for CLI and loopback research API."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
import hashlib
import json
import math
import shutil
import threading
import uuid


def code_fingerprint():
    source = Path(__file__).parent
    names = ('integrated_data.py', 'integrated_factors.py', 'integrated_engine.py',
             'integrated_research.py', 'integrated_service.py', 'backtest.py',
             'portfolio.py', 'metrics.py', 'config.py', 'integrated_variants.py',
             'integrated_legacy_best.py', 'integrated_repairs.py', 'factors.py',
             'advanced_factors.py', 'universe.py', 'resources/integrated_legacy_map.json',
             'resources/integrated_universe.json')
    records = {name: hashlib.sha256((source / name).read_bytes()).hexdigest()
               for name in names if (source / name).exists()}
    return hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest(), records


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    temporary = path.with_suffix(path.suffix + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(body, encoding='utf-8')
    temporary.replace(path)


def normalize_settings(settings):
    from .integrated_engine import IntegratedConfig
    if not isinstance(settings, dict):
        raise ValueError('settings must be an object')
    allowed = {f.name for f in fields(IntegratedConfig)}
    unknown = set(settings) - allowed
    if unknown:
        raise ValueError('Unknown settings: ' + ', '.join(sorted(unknown)))
    for name, value in settings.items():
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f'{name} must be finite')
    for name, low, high in [('top_n', 1, 100), ('max_weight', 0.01, 1),
                            ('transaction_cost_bps', 0, 1000), ('slippage_bps', 0, 1000),
                            ('execution_delay_sessions', 1, 20)]:
        if name in settings and (isinstance(settings[name], bool) or not isinstance(settings[name], (float, int)) or not low <= settings[name] <= high):
            raise ValueError(f'{name} outside supported range [{low}, {high}]')
    for name in ('top_n', 'execution_delay_sessions'):
        if name in settings and not isinstance(settings[name], int):
            raise ValueError(f'{name} must be an integer')
    for name in ('evaluation_window_days', 'bootstrap_repetitions'):
        if name in settings and (type(settings[name]) is not int or settings[name] < 0):
            raise ValueError(f'{name} must be a nonnegative integer')
    if settings.get('bootstrap_repetitions', 2000) > 10000:
        raise ValueError('bootstrap_repetitions must not exceed 10000')
    for name in ('start_date', 'end_date'):
        value = settings.get(name)
        if value is not None:
            if not isinstance(value, str):
                raise ValueError(f'{name} must be an ISO date')
            try:
                datetime.strptime(value, '%Y-%m-%d')
            except ValueError as exc:
                raise ValueError(f'{name} must be an ISO date') from exc
    if settings.get('end_date') and settings.get('end_date') < settings.get('start_date', '2016-01-01'):
        raise ValueError('end_date precedes start_date')
    if settings.get('evaluation_window_days', 756) != 756:
        raise ValueError('Monthly selection requires the fixed 756-session window')
    if settings.get('weighting', 'score_liquidity_rank') not in {'score_liquidity_rank', 'equal'}:
        raise ValueError('Unsupported weighting')
    for name in ('common_universe', 'run_stress'):
        if name in settings and type(settings[name]) is not bool:
            raise ValueError(f'{name} must be boolean')
    if 'comparison_factors' in settings:
        from .integrated_factors import factor_registry
        ids = {r['id'] for r in factor_registry()}
        if not isinstance(settings['comparison_factors'], (tuple, list)) or any(v not in ids for v in settings['comparison_factors']):
            raise ValueError('Unknown comparison definition')
    if settings.get('common_universe') and not settings.get('comparison_factors'):
        raise ValueError('Select factors for a common-universe comparison')
    return IntegratedConfig(**settings)


def validate_result(result):
    if not isinstance(result, dict) or result.get('schemaVersion') != 'integrated-factor/v1':
        raise ValueError('Unsupported integrated result schema')
    if not isinstance(result, dict) or not result.get('selection') or not result.get('factors'):
        raise ValueError('Incomplete integrated result')
    if not result.get('registry') or not result.get('resultIdentity'):
        raise ValueError('Missing registry or reproducibility identity')
    json.dumps(result, allow_nan=False)


def data_inventory(market):
    from .integrated_data import integrated_universe
    origins = {row['symbol']: row for row in integrated_universe()['symbols']}
    collected = {}
    for receipt in market.metadata.get('receipts', []):
        for symbol in receipt.get('symbols', []):
            collected[symbol] = receipt.get('retrievedAt')
    rows = []
    quarantines = {r['symbol']: r for r in market.metadata.get('amendments', [])
                   if r['kind'] == 'unverified_input_quarantine'}
    exchanges = {r['symbol']: r for r in market.metadata.get('corporateActions', [])}
    alternate = {r['symbol']: r for r in market.metadata.get('amendments', [])
                 if r['kind'] == 'observed_quote'}
    observed = market.prices.notna() & market.prices.gt(0)
    volume_ok = market.volumes.notna() & market.volumes.gt(0)
    dollar_volume = (market.raw_close * market.volumes).where(volume_ok)
    checks = {
        '종가 없음': observed.iloc[-1],
        '거래량 없음': volume_ok.iloc[-1],
        '가격 $5 미만': market.raw_close.iloc[-1].ge(5),
        '252거래일 이력 부족': observed.sum().ge(252),
        '가격 관측 부족': observed.tail(252).mean().ge(.95),
        '거래량 관측 부족': volume_ok.tail(252).mean().ge(.90),
        '극단 수익 관측': market.prices.pct_change(fill_method=None).tail(252).abs().gt(.8).sum().eq(0),
        '거래대금 관측 42개 미만': dollar_volume.tail(63).count().ge(42),
        '평균 거래대금 $5M 미만': dollar_volume.tail(63).mean().ge(5_000_000),
    }
    for symbol in market.metadata['requestedSymbols']:
        source = origins.get(symbol, {})
        observations = market.prices[symbol].dropna()
        eligible = bool(market.eligibility[symbol].iloc[-1])
        failure = market.metadata.get('failedSymbols', {}).get(symbol)
        reasons = [label for label, passed in checks.items() if not bool(passed[symbol])]
        if symbol in quarantines:
            failure = None
            reasons = ['원자료 조정 기준 불일치 · 분석 입력 제외']
        elif symbol in exchanges:
            action = exchanges[symbol]
            reasons = ([f"{action['date']} · 주당 ${action['cashPerShare']:.2f} 현금 수취권 전환"]
                       if action.get('targetSymbol') is None else
                       [f"{action['date']} · {action['targetSymbol']} {action['shareRatio']}주로 전환"])
        provenance = 'Yahoo Finance'
        if symbol in alternate:
            provenance += ' · ' + alternate[symbol]['sourceUrl'].split('/')[2]
        rows.append({**source, 'symbol': symbol, 'source': provenance,
                     'observedAt': str(observations.index[-1].date()) if len(observations) else None,
                     'firstObservation': str(observations.index[0].date()) if len(observations) else None,
                     'collectedAt': collected.get(symbol), 'observations': len(observations),
                     'status': 'failed' if failure else 'eligible' if eligible else 'excluded',
                     'reason': failure or (' · '.join(reasons) if not eligible else ''), 'exclusionReasons': reasons})
    return rows


def effective_settings(settings, comparison_factors=None, common_universe=None):
    if not isinstance(settings, dict):
        raise ValueError('settings must be an object')
    effective = dict(settings)
    if comparison_factors is not None:
        if not isinstance(comparison_factors, (tuple, list)):
            raise ValueError('comparisonFactors must be an array')
        effective['comparison_factors'] = tuple(comparison_factors)
    if common_universe is not None:
        effective['common_universe'] = common_universe
    normalize_settings(effective)
    return effective


def execute_run(market, settings, directory, comparison_factors=None, common_universe=None, experiment_definition=None):
    from .integrated_engine import run_integrated_analysis
    if (Path(directory) / 'result.json').exists():
        raise FileExistsError('A completed run is immutable; choose a new output directory')
    effective = effective_settings(settings, comparison_factors, common_universe)
    config = normalize_settings(effective)
    code_hash, code_files = code_fingerprint()
    if experiment_definition is not None:
        from .integrated_variants import run_legacy_experiment
        result = run_legacy_experiment(market, config, experiment_definition)
    else:
        result = run_integrated_analysis(market, config, progress_callback=lambda event: print(json.dumps(event), flush=True))
        result['resultIdentity']['strategyType'] = 'monthly_selection'
    result['data']['symbols'] = data_inventory(market)
    if code_fingerprint()[0] != code_hash:
        raise RuntimeError('Calculation code changed during execution; result was not published')
    result['resultIdentity']['codeHash'] = code_hash
    result['resultIdentity']['codeHashFiles'] = code_files
    result['resultIdentity']['resultId'] = hashlib.sha256(json.dumps(result['resultIdentity'], sort_keys=True).encode()).hexdigest()[:24]
    validate_result(result)
    atomic_json(Path(directory) / 'result.json', result)
    return result


def build_site(directory, result):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    web = Path(__file__).parent / 'web'
    (directory / 'assets').mkdir(exist_ok=True)
    for source, target in [('integrated.html', 'index.html'), ('integrated.css', 'assets/integrated.css'), ('integrated.js', 'assets/integrated.js'), ('styles.css', 'assets/styles.css'), ('shared-nav.css', 'assets/shared-nav.css')]:
        shutil.copyfile(web / source, directory / target)
    atomic_json(directory / 'data' / 'integrated-result.json', result)
    shutil.copyfile(Path(__file__).parent / 'resources' / 'integrated_legacy_map.json', directory / 'data' / 'legacy-definitions.json')


class ResearchRuns:
    def __init__(self, snapshot, directory):
        from .integrated_data import load_integrated_market
        self.market = load_integrated_market(snapshot)
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.lock = threading.Lock()
        self.code_hash = code_fingerprint()[0]
        # An interrupted process is never presented as still computing.
        for path in self.directory.glob('*/status.json'):
            status = json.loads(path.read_text())
            if status['status'] in {'queued', 'running', 'validating'}:
                status.update(status='failed', error='이전 실행이 중단되었습니다.')
                atomic_json(path, status)

    def list(self):
        return sorted([json.loads(p.read_text()) for p in self.directory.glob('*/status.json')], key=lambda r: r['createdAt'], reverse=True)

    def submit(self, request):
        if not isinstance(request, dict) or set(request) - {'settings', 'comparisonFactors', 'commonUniverse', 'hypothesis', 'experimentDefinition'}:
            raise ValueError('Invalid request fields')
        if code_fingerprint()[0] != getattr(self, 'code_hash', code_fingerprint()[0]):
            raise ValueError('계산 코드가 변경되었습니다. 로컬 서버를 재시작하세요.')
        effective_settings(request.get('settings', {}), request.get('comparisonFactors'), request.get('commonUniverse'))
        if not isinstance(request.get('commonUniverse', False), bool):
            raise ValueError('commonUniverse must be boolean')
        if request.get('experimentDefinition') is not None:
            from .integrated_variants import resolve_experiment
            resolve_experiment(request['experimentDefinition'])
        if not isinstance(request.get('hypothesis', ''), str):
            raise ValueError('hypothesis must be text')
        key = hashlib.sha256(json.dumps({'request': request, 'snapshot': self.market.metadata['snapshotId']}, sort_keys=True, allow_nan=False).encode()).hexdigest()
        with self.lock:
            for status in self.list():
                if status.get('requestHash') == key and status['status'] in {'queued', 'running', 'validating'}:
                    return status
            run_id = uuid.uuid4().hex
            status = {'runId': run_id, 'status': 'queued', 'requestHash': key,
                      'createdAt': datetime.now(timezone.utc).isoformat(), 'request': request}
            atomic_json(self.directory / run_id / 'status.json', status)
            self.executor.submit(self._run, status)
            return status

    def _run(self, status):
        directory = self.directory / status['runId']
        try:
            status['status'] = 'running'
            atomic_json(directory / 'status.json', status)
            request = status['request']
            execute_run(self.market, request.get('settings', {}), directory,
                        request.get('comparisonFactors'), request.get('commonUniverse'), request.get('experimentDefinition'))
            status.update(status='completed', resultUrl=f"/api/integrated/runs/{status['runId']}/result")
        except Exception as exc:
            status.update(status='failed', error=str(exc))
        status['finishedAt'] = datetime.now(timezone.utc).isoformat()
        atomic_json(directory / 'status.json', status)


def serve(snapshot, site, runs, port=8766):
    manager = ResearchRuns(snapshot, runs)

    class Handler(SimpleHTTPRequestHandler):
        def json_response(self, status, body):
            data = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = urlparse(self.path).path
            prefix = '/api/integrated/runs'
            if path == prefix:
                return self.json_response(200, {'runs': manager.list()})
            if path.startswith(prefix + '/'):
                pieces = path[len(prefix) + 1:].split('/')
                if len(pieces) > 2 or len(pieces[0]) != 32 or any(c not in '0123456789abcdef' for c in pieces[0]):
                    return self.json_response(404, {'error': 'Unknown run'})
                filename = 'result.json' if len(pieces) == 2 and pieces[1] == 'result' else 'status.json'
                target = manager.directory / pieces[0] / filename
                if not target.exists():
                    return self.json_response(404, {'error': 'Unknown run'})
                return self.json_response(200, json.loads(target.read_text()))
            return super().do_GET()

        def do_POST(self):
            expected = f'http://{self.headers.get("Host", "")}'
            host = urlparse(expected).hostname
            if host not in {'127.0.0.1', 'localhost', '::1'} or self.headers.get('Origin', expected) != expected:
                return self.json_response(403, {'error': 'Local same-origin requests only'})
            if self.path != '/api/integrated/runs':
                return self.json_response(404, {'error': 'Unknown endpoint'})
            try:
                length = int(self.headers.get('Content-Length', 0))
                if not 0 < length <= 65536:
                    raise ValueError('Invalid request size')
                request = json.loads(self.rfile.read(length))
                status = manager.submit(request)
            except (ValueError, TypeError) as exc:
                return self.json_response(400, {'error': str(exc)})
            self.json_response(202, status)

    server = ThreadingHTTPServer(('127.0.0.1', port), partial(Handler, directory=str(Path(site).resolve())))
    print(f'http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        manager.executor.shutdown(wait=True)
