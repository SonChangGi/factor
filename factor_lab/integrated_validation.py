"""Publication invariants for new daily runs; historical releases retain their proofs."""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache
import hashlib
import json
import math
import re
from pathlib import Path
import subprocess


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_runtime_lock(identity, lock):
    runtime = identity.get('runtime', {})
    require(runtime.get('dependencyLockHash') == hashlib.sha256(lock).hexdigest(), 'Runtime dependency lock differs')
    require(re.fullmatch(r'\d+\.\d+\.\d+', runtime.get('pythonVersion', '')) is not None, 'Missing Python version')
    packages = runtime.get('packageVersions', {})
    require(set(packages) == {'numpy', 'pandas', 'exchange-calendars', 'rfc8785', 'yfinance', 'finance-datareader'}, 'Runtime package catalog')
    locked = dict(re.findall(r'\[\[package\]\]\s+name = "([^"]+)"\s+version = "([^"]+)"', lock.decode()))
    require(all(version is not None and version == locked.get(name) for name, version in packages.items()), 'Runtime packages differ from committed lock')


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def close(actual, expected, name, tolerance=1e-8):
    require(finite(actual) and abs(actual - expected) <= tolerance * max(1, abs(expected)), name)


def iso(value):
    require(isinstance(value, str) and date.fromisoformat(value).isoformat() == value, 'Invalid date')
    return value


def check_weights(row, *, target=False):
    prefix = 'target' if target else ''
    held = row.get('targetHoldings' if target else 'holdings', [])
    cash = row.get('targetCashWeight' if target else 'cashWeight')
    require(isinstance(held, list), 'Missing holdings')
    symbols = [r['symbol'] for r in held]
    require(len(symbols) == len(set(symbols)), 'Duplicate holdings')
    require(all(isinstance(r['symbol'], str) and r['symbol'] and finite(r['weight']) and r['weight'] > 0 for r in held), 'Invalid holding')
    if not target and cash is None and row.get('valuationStatus') == 'unavailable':
        require(not held and row.get('holdingsAsOf') is None, 'Unavailable valuation has fabricated holdings')
        return
    require(finite(cash) and -1e-8 <= cash <= 1 + 1e-8, prefix + ' cash')
    close(sum(r['weight'] for r in held) + cash, 1, 'Holdings do not conserve NAV')
    if not target:
        claim, liquid = row.get('receivableWeight', 0), row.get('liquidCashWeight', cash)
        require(all(finite(v) and v >= -1e-8 for v in (claim, liquid)), 'Invalid legal claims/cash')
        close(claim + liquid, cash, 'Claims counted as liquid cash')


@lru_cache(maxsize=32)
def market_calendar(start, end):
    import exchange_calendars as calendars
    return calendars.get_calendar('XNYS', start=start, end=end)


def session_dates(start, end):
    calendar = market_calendar(str(date.fromisoformat(start) - timedelta(days=10)),
                               str(date.fromisoformat(end) + timedelta(days=65)))
    return [str(d.date()) for d in calendar.sessions_in_range(start, end)]


def candidate_metric(candidate, key):
    value = candidate['metrics'].get(key)
    state = candidate.get('metricStates', {}).get(key)
    if finite(value):
        require(state in (None, 'available'), 'Metric state contradicts finite value')
        return value
    require(value is None and state in ('positive_infinity', 'negative_infinity'), 'Candidate metric unavailable: ' + key)
    return math.inf if state == 'positive_infinity' else -math.inf


def percentile_scores(values):
    """Independent linear quantiles and average ties, without engine helpers."""
    ordered = sorted(v for v in values if math.isfinite(v))
    if not ordered:
        return [100. if v == math.inf else 0. for v in values]
    def quantile(p):
        position = (len(ordered) - 1) * p
        lower = int(position)
        fraction = position - lower
        return ordered[lower] * (1-fraction) + ordered[min(lower+1, len(ordered)-1)] * fraction
    low, high = quantile(.05), quantile(.95)
    clipped = [max(low, min(high, value)) for value in values]
    return [100. * (sum(v < value for v in clipped) + (sum(v == value for v in clipped)+1)/2) / len(clipped)
            for value in clipped]


def check_guardrails(candidate):
    m = candidate['metrics']
    require(all(finite(m.get(key)) and m[key] >= 0 for key in
                ('annualizedCostDrag','effectiveNames','hhi','maxWeight','maxSecurityDayContribution',
                 'maxSecurityContributionShare','maxLeaveOneCagrDelta')), 'Invalid guardrail diagnostic')
    require(0 < m['hhi'] <= 1 and 0 < m['maxWeight'] <= 1, 'Invalid concentration diagnostic')
    close(m['effectiveNames'], 1 / m['hhi'], 'Effective names/HHI disagree')
    limits = [('sharpe', candidate_metric(candidate, 'sharpe') < 0),
              ('drawdown', candidate_metric(candidate, 'mdd') < -.60),
              ('cost', m.get('annualizedCostDrag', math.inf) > .02),
              ('effective_names', m.get('effectiveNames', -math.inf) < 10-1e-9),
              ('hhi', m.get('hhi', math.inf) > .15),
              ('weight', m.get('maxWeight', math.inf) > .15),
              ('security_day', m.get('maxSecurityDayContribution', math.inf) > .10),
              ('security_dependence', m.get('maxSecurityContributionShare', math.inf) > .35),
              ('leave_one', m.get('maxLeaveOneCagrDelta', math.inf) > .25)]
    for key in ('annualizedCostDrag','effectiveNames','hhi','maxWeight',
                'maxSecurityDayContribution','maxSecurityContributionShare','maxLeaveOneCagrDelta'):
        require(finite(m.get(key)), 'Missing guardrail diagnostic: ' + key)
    require(m.get('calendarObservations') == m.get('observedReturnCount') == m.get('dailyRiskObservations') == 756 and
            m.get('multiSessionReturnObservations') == 0 and m.get('riskMetricsExact') is True,
            'Candidate window is not 756 complete single sessions')
    reasons = [key for key, failed in limits if failed]
    require(candidate['status'] == ('risk_rejected' if reasons else 'eligible'), 'Guardrail status contradicts metrics')
    require(candidate.get('reason', '').split(',') == reasons if reasons else candidate.get('reason', '') == '',
            'Guardrail reasons contradict metrics')


def check_curve(book, asof):
    nav, dd, metrics = book.get('nav', []), book.get('drawdown', []), book.get('metrics', {})
    require(nav and len(dd) == len(nav), 'Missing NAV/drawdown')
    dates = [iso(r['date']) for r in nav]
    require(dates == sorted(set(dates)) and dates[-1] == asof, 'NAV dates or terminal observation')
    require([r['date'] for r in dd] == dates, 'NAV/drawdown calendars differ')
    require(dates == session_dates(dates[0], asof), 'NAV omits or invents an NYSE session')
    require(finite(nav[-1]['value']) and metrics.get('endingNavAvailable') is True, 'Terminal NAV unavailable')
    peak, mdd = 1., 0.
    for point, drawdown in zip(nav, dd):
        value = point['value']
        if value is None:
            require(drawdown['value'] is None, 'Missing NAV was filled in drawdown')
            continue
        require(finite(value) and value > 0, 'Invalid NAV')
        peak = max(peak, value)
        expected = value / peak - 1
        close(drawdown['value'], expected, 'Drawdown does not match NAV')
        mdd = min(mdd, expected)
    close(metrics['mdd'], mdd, 'MDD does not match NAV')
    require(metrics.get('calendarObservations') == len(nav), 'CAGR calendar mismatch')
    expected = nav[-1]['value'] ** (252 / len(nav)) - 1
    close(metrics['cagr'], expected, 'CAGR does not match cost-inclusive NAV')
    if mdd:
        close(metrics['calmar'], expected / abs(mdd), 'Calmar does not match NAV')
    observed = sum(p['value'] is not None for p in nav)
    if 'observedReturnCount' in metrics:
        require(metrics['observedReturnCount'] == observed, 'Observed return count differs from null NAV')
        multi = metrics.get('multiSessionReturnObservations')
        require(type(multi) is int and 0 <= multi <= observed, 'Invalid multi-session accounting count')
        require(metrics.get('dailyRiskObservations') == observed - multi, 'Risk count differs from accounting intervals')
        close(metrics['valuationCoverageRatio'], observed / len(nav), 'Valuation coverage differs from null NAV')
        close(metrics['dailyRiskCoverageRatio'], (observed - multi) / len(nav), 'Risk coverage differs from accounting intervals')
        require(metrics.get('riskMetricsExact') == (observed == len(nav) and multi == 0), 'Risk exactness differs from accounting gaps')
    require(metrics.get('riskMetricsComplete') is True, 'Risk metrics unavailable')
    check_weights(book)


def check_candidates(row, ids, *, complete=False):
    candidates = row.get('candidates', [])
    require({r['id'] for r in candidates} == ids and len(candidates) == len(ids), 'Candidate catalog')
    require(all(r['status'] in ('eligible','risk_rejected','data_error','insufficient_data') for r in candidates), 'Unknown candidate status')
    comparable = [r for r in candidates if r['status'] in ('eligible', 'risk_rejected')]
    if complete:
        require(len(comparable) == len(ids), 'Not all current candidates can be evaluated')
    for candidate in comparable:
        require(finite(candidate.get('score')) and 0 <= candidate['score'] <= 100, 'Candidate score')
        components = candidate.get('components', {})
        require(set(components) == {'cagr', 'sortino', 'calmar', 'mdd', 'stability'}, 'Score components')
        close(candidate['score'], sum(components.values()), 'Score components do not sum')
        check_guardrails(candidate)
    for key, weight in dict(cagr=.25, sortino=.25, calmar=.20, mdd=.20, stability=.10).items():
        ranks = percentile_scores([candidate_metric(r, key) for r in comparable])
        for candidate_row, rank in zip(comparable, ranks):
            close(candidate_row['components'][key], rank * weight, 'Score percentile/weight mismatch: ' + key)
    eligible = [r for r in comparable if r['status'] == 'eligible']
    if row['status'] == 'selected':
        require(eligible, 'Selected without eligible candidates')
        metric = candidate_metric
        best = min(eligible, key=lambda r: tuple(-r['score'] if key == 'score' else -metric(r, key) for key in ('score','sortino','calmar','mdd','cagr','sharpe','stability')) + (r['turnover'], r['id']))
        require(best['id'] == row['factorId'], 'Selected factor violates score/tie ordering')
        close(row['score'], best['score'], 'Selected score differs')
    elif row['status'] == 'cash':
        require(not eligible and not any(r['status'] == 'data_error' for r in candidates), 'Cash caused by a data error')
        require(row['factorId'] is None, 'Cash selection has factor')
    else:
        require(row['status'] == 'deferred' and not eligible, 'Unknown selection status')


def validate_automated_result(result, target_as_of=None):
    from .integrated_data import integrated_universe
    from .integrated_factors import factor_registry
    from .integrated_service import validate_result
    validate_result(result)
    json.dumps(result, allow_nan=False)
    asof = iso(result['data']['asOf'])
    if target_as_of:
        require(asof == target_as_of, 'Result does not reach target NYSE session')
    identity = result['resultIdentity']
    require(identity.get('strategyType') == 'monthly_selection', 'Wrong daily strategy')
    require(identity['inputHash'] == result['data']['snapshotId'], 'Snapshot binding')
    require(identity['codeHash'] == hashlib.sha256(json.dumps(identity['codeHashFiles'], sort_keys=True).encode()).hexdigest(), 'Code fingerprint')
    definitions = factor_registry()
    require(result['registry'] == definitions, 'Definition version/catalog changed')
    factors = {row['id']: row for row in result['factors']}
    require(set(factors) == {r['id'] for r in definitions} and len(factors) == len(result['factors']), 'Factor catalog')
    symbols = {r['symbol'] for r in integrated_universe()['symbols']}
    require(set(result['data']['requestedSymbols']) == symbols and result['data']['requestedCount'] == len(symbols), 'Union universe contract')
    eligible = {r['id'] for r in definitions if r['selectionEligible']}
    settings = result['settings']
    sessions = session_dates(settings['start_date'], asof)
    calendar = market_calendar(str(date.fromisoformat(settings['start_date']) - timedelta(days=10)),
                               str(date.fromisoformat(asof) + timedelta(days=65)))
    import pandas as pd
    monthends = [d for d in sessions if calendar.next_session(d).month != pd.Timestamp(d).month]
    delay = settings['execution_delay_sessions']
    require(type(delay) is int and delay >= 1, 'Invalid execution delay')
    def execution(row):
        signal = iso(row['signalDate'])
        require(row['date'] == signal and signal <= asof, 'Future or inconsistent signal date')
        expected = str(calendar.session_offset(signal, delay).date())
        require(row['executionDate'] == expected, 'Execution does not match NYSE session delay')
        return expected

    for definition in definitions:
        row = factors[definition['id']]
        if not definition['selectionEligible']:
            require(row['status'] == 'research_only' and not row.get('nav'), 'Research definition fabricated a portfolio')
            continue
        require(row['status'] in ('available', 'partial_data'), 'Fixed factor unavailable: ' + row['id'])
        check_curve(row, asof)
        require(row.get('historyBasis') == 'execution_close_actual_weights' and row.get('latest'), 'Missing fixed holding history')
        check_weights(row['latest'])
        require(row['latest']['holdingsAsOf'] == asof and row['latest'].get('valuationStatus') == 'available', 'Fixed latest valuation is stale')
        for key in ('cashWeight', 'receivableWeight', 'liquidCashWeight'):
            close(row['latest'][key], row[key], 'Fixed latest cash/claim mismatch: ' + key)
        require({r['symbol']: r['weight'] for r in row['latest']['holdings']} ==
                {r['symbol']: r['weight'] for r in row['holdings']}, 'Fixed latest holdings differ')
        history = row.get('history', [])
        dates = [iso(h['date']) for h in history]
        require(dates == monthends, 'Fixed history monthly coverage')
        for h in history:
            expected = execution(h)
            require((h['status'] == 'pending') == (expected > asof), 'Fixed pending execution timing')
            if h['status'] == 'executed':
                require(h.get('holdingsAsOf') == expected and h.get('valuationStatus') == 'available', 'Executed snapshot is stale')
            if expected > asof:
                require(h.get('executionStatus') == 'pending' and h.get('cost') is None and h.get('turnover') is None, 'Pending trade was treated as executed')
            check_weights(h); check_weights(h, target=True)
            if h.get('holdingsAsOf'):
                require(h['holdingsAsOf'] <= min(h['executionDate'], asof), 'Future holding snapshot')
    selection = result['selection']
    check_curve(selection, asof)
    require(selection.get('holdingsAsOf') == asof, 'Current holdings are stale')
    require(selection['history'] and selection['current'] == selection['history'][-1], 'Current/history mismatch')
    dates = [iso(h['date']) for h in selection['history']]
    require(dates == monthends, 'Selection monthly coverage')
    pending = selection['history'][-1] if selection['history'][-1]['executionDate'] > asof else None
    require(selection.get('pending') == pending, 'Pending selection binding')
    for h in selection['history']:
        expected = execution(h)
        if h.get('holdingsAsOf'):
            require(iso(h['holdingsAsOf']) <= min(expected, asof), 'Future selection holding snapshot')
        if expected > asof:
            require(h.get('executionStatus') == 'pending' and h.get('cost') is None and h.get('turnover') is None, 'Pending selection was treated as executed')
        check_candidates(h, eligible)
        check_weights(h)
    check_candidates(selection['current'], eligible, complete=True)
    require(selection['current']['status'] in ('selected', 'cash'), 'Data error at current selection')
    require(settings.get('run_stress') is True and settings.get('bootstrap_repetitions') == 2000, 'Incomplete daily research settings')
    stresses = result['research']['stress']
    require({s['id'] for s in stresses} == {'cost20','cost40','delay2','fixed_choice_delay2','top10','top30','equal'} and len(stresses) == 7, 'Stress scenario catalog')
    for s in stresses:
        require(s['status'] == 'available' and s['inputHash'] == identity['inputHash'] and s['codeHash'] == identity['codeHash'], 'Stress version/basis mismatch')
        require(s.get('nav') and finite(s['nav'][-1]['value']) and s['nav'][-1]['date'] == asof, 'Incomplete stress NAV')
        require(s.get('sourceResultId') == identity['resultId'] and s.get('sourceEngineVersion') == identity['engineVersion'], 'Stress parent binding')
        policy = result['data'].get('automationPolicy')
        if policy:
            require(s.get('sourcePolicyHash') == policy['sha256'], 'Stress policy binding')
    for key in ('bootstrap', 'icBootstrap'):
        samples = result['research'][key]
        require(samples and all(s.get('status') == 'available' and s.get('repetitions') == 2000 for s in samples), 'Incomplete ' + key)
    return dict(status='passed', validatorVersion='factor-daily-invariants/v1', targetDataAsOf=asof,
                inputHash=identity['inputHash'], codeHash=identity['codeHash'], fixedFactors=len(eligible),
                monthlyRecords=len(selection['history']), stressScenarios=len(stresses), currentCandidates=len(eligible),
                checks=['union_universe','version_bindings','cost_inclusive_nav_metrics','drawdown','conserved_holdings_cash_claims','signal_execution_order','current_all_candidates','selection_tie_order','fixed_history','research_completeness'])


def write_automated_manifest(candidate, result, source_commit, validation, *, publication_type='automated_daily'):
    from .integrated_service import atomic_json
    require(validation.get('status') == 'passed', 'Candidate validation did not pass')
    require(publication_type in {'automated_daily', 'reviewed_definition_migration'}, 'Unknown publication type')
    if publication_type == 'reviewed_definition_migration':
        require(validation.get('definitionReview', {}).get('reviewedDefinitionIds') == ['CONSISTENCY12_1'],
                'Reviewed migration requires an explicit definition review')
    root = Path(__file__).resolve().parents[1]
    package = Path(__file__).parent.name
    lock = subprocess.check_output(['git', 'show', f'{source_commit}:uv.lock'], cwd=root)
    validate_runtime_lock(result['resultIdentity'], lock)
    for name, digest in result['resultIdentity']['codeHashFiles'].items():
        body = subprocess.check_output(['git', 'show', f'{source_commit}:{package}/{name}'], cwd=root)
        require(hashlib.sha256(body).hexdigest() == digest, 'Calculation source changed: ' + name)
    candidate = Path(candidate)
    files = {p.relative_to(candidate).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(candidate.rglob('*')) if p.is_file() and p.name != 'publication.json'}
    manifest = dict(schemaVersion='integrated-publication/v2', status='passed', publicationType=publication_type,
                    calculationSourceCommit=source_commit, calculationPackage=package,
                    calculationSourceUrl=f'https://github.com/SonChangGi/factor/tree/{source_commit}',
                    resultIdentity=result['resultIdentity'], dataAsOf=result['data']['asOf'],
                    requestedCount=result['data']['requestedCount'], files=files,
                    scheduledIntegratedRefresh='active', validation=validation)
    atomic_json(candidate / 'publication.json', manifest)
    return manifest
