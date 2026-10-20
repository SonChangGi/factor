#!/usr/bin/env python3
"""Replay fixed factors only, verify their parent result, export immutable history.

Example: python scripts/export_fixed_factor_history.py --snapshot SNAPSHOT \
  --result site/data/integrated-result.json --output outputs/fixed-history.json \
  --calculation-source /path/to/exact/calculation/checkout
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile

# Set before importing numpy/pandas or the selected calculation package.
for name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
             'VECLIB_MAXIMUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'


def require_equal(actual, expected, location):
    """Exact serialized financial regression, including null and observation dates."""
    if actual != expected:
        raise ValueError(f'Parent result regression mismatch: {location}')


def write_immutable(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + '.', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        # Atomic create-if-absent: unlike replace(), this never overwrites a result.
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', required=True, type=Path)
    parser.add_argument('--result', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--calculation-source', type=Path,
                        default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    if args.output.exists():
        raise FileExistsError('History output is immutable; choose a new path')
    parent_bytes = args.result.read_bytes()
    parent = json.loads(parent_bytes)
    identity = parent['resultIdentity']
    source = args.calculation_source.resolve()
    sys.path.insert(0, str(source))
    from momentum_factor_lab.integrated_service import code_fingerprint
    code_hash, code_files = code_fingerprint()
    require_equal(code_hash, identity['codeHash'], 'calculation codeHash')
    require_equal(code_files, identity['codeHashFiles'], 'calculation source files')

    # Load this new read-only presentation helper without replacing the exact
    # calculation package selected above.
    spec = importlib.util.spec_from_file_location(
        '_fixed_history_export_helper', Path(__file__).resolve().parents[1] /
        'momentum_factor_lab' / 'integrated_history.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    import pandas as pd
    from momentum_factor_lab.integrated_data import load_integrated_market
    from momentum_factor_lab.integrated_engine import (
        IntegratedConfig, completed_monthends, _allocation, performance, metrics,
        next_execution, clean,
    )
    from momentum_factor_lab.integrated_factors import factor_registry, iter_integrated_factors
    from momentum_factor_lab.config import RunConfig, FIXED_WEIGHTING_POLICY
    from momentum_factor_lab.backtest import run_factor_backtest
    from momentum_factor_lab.integrated_repairs import backtest_inputs

    market = load_integrated_market(args.snapshot)
    require_equal(market.metadata['snapshotId'], identity['inputHash'], 'snapshot inputHash')
    config = IntegratedConfig(**parent['settings'])
    if config.common_universe:
        raise ValueError('Common-universe parent replay is not supported by this exporter')
    rc = RunConfig(start_date=config.start_date, end_date=config.end_date,
                   top_n=config.top_n, max_weight=config.max_weight,
                   transaction_cost_bps=config.transaction_cost_bps,
                   slippage_bps=config.slippage_bps,
                   evaluation_window_days=config.evaluation_window_days,
                   score_cagr_weight=.25, score_sharpe_weight=0.)
    full_index = market.prices.index
    index = full_index[(full_index >= pd.Timestamp(config.start_date)) &
                       (full_index <= pd.Timestamp(config.end_date) if config.end_date else True)]
    dates = completed_monthends(index)
    adv = (market.raw_close * market.volumes).rolling(63, min_periods=42).mean()
    definitions = {definition['id']: definition for definition in factor_registry()}
    parents = {row['id']: row for row in parent['factors']}
    require_equal(set(definitions), set(parents), 'factor catalog')
    factors = {}
    for key, raw_panel in iter_integrated_factors(market):
        definition = definitions[key]
        if not definition['selectionEligible']:
            factors[key] = dict(status='research_only', history=[], latest=None,
                                reason='No fixed portfolio defined for this research signal')
            continue
        panel = raw_panel.where(market.eligibility)
        allocations = {date: _allocation(date, panel, market, adv, config, rc) for date in dates}
        result = run_factor_backtest(
            key, FIXED_WEIGHTING_POLICY, market.prices.loc[index], panel.loc[index], rc,
            eligibility_mask=market.eligibility.loc[index],
            trailing_dollar_volume=adv.loc[index], signal_targets=allocations,
            execution_delay_sessions=config.execution_delay_sessions,
            **backtest_inputs(market, index))
        nav, drawdown = performance(result.returns)
        old = parents[key]
        for field, actual in [('nav', clean(nav)), ('drawdown', clean(drawdown)),
                              ('metrics', clean(metrics(result.returns, result.return_interval_sessions))),
                              ('cashWeight', result.ending_cash_weight),
                              ('receivableWeight', result.ending_receivable_weight),
                              ('liquidCashWeight', result.ending_cash_weight - result.ending_receivable_weight)]:
            require_equal(actual, old[field], key + '.' + field)
        require_equal({r['symbol']: r['weight'] for r in helper.holding_rows(result.ending_weights)},
                      {r['symbol']: r['weight'] for r in old['holdings']}, key + '.holdings')
        factors[key] = dict(status=old['status'], **helper.fixed_factor_history(
            result, allocations, index, config.execution_delay_sessions,
            next_execution=next_execution))
        print(json.dumps(dict(stage='fixed_history', factorId=key, completed=len(factors),
                              total=len(definitions)), ensure_ascii=False), flush=True)
        del result, panel, raw_panel
    require_equal(code_fingerprint(), (code_hash, code_files), 'source changed during replay')
    require_equal(args.result.read_bytes(), parent_bytes, 'parent changed during replay')
    payload = dict(schemaVersion='fixed-factor-history/v1', parentResultId=identity['resultId'],
                   parentSha256=hashlib.sha256(parent_bytes).hexdigest(),
                   inputHash=identity['inputHash'], codeHash=code_hash,
                   dataAsOf=parent['data']['asOf'], factors=factors,
                   validation=dict(status='passed', fixedFactorsReplayed=sum(
                       value['status'] != 'research_only' for value in factors.values()),
                       financialComparison='exact_parent_nav_drawdown_metrics_ending_holdings_cash'))
    write_immutable(args.output, clean(payload))
    print(json.dumps(dict(status='passed', output=str(args.output)), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
