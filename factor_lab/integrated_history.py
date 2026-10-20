"""Actual close holdings for each fixed factor's monthly signal.

BacktestResult.weights are *opening* weights.  A completed close therefore
uses the next row (or ending_weights), never that close's opening row.
"""
from __future__ import annotations

import math
import pandas as pd


def holding_rows(weights):
    return [dict(symbol=str(symbol), weight=float(weight))
            for symbol, weight in sorted(weights.items(), key=lambda row: (-row[1], str(row[0])))
            if math.isfinite(float(weight)) and weight > 1e-12]


def fixed_factor_history(result, targets, price_index, execution_delay_sessions=1,
                         *, next_execution=None):
    """Return monthly execution-close snapshots and a separate latest snapshot.

    Unavailable valuations point to the last complete close explicitly. Pending
    targets remain separate from the portfolio actually held. The function
    requires full retained weights and does not reconstruct shares from prices.
    """
    index = pd.DatetimeIndex(price_index)
    if index.empty or not result.weights.index.equals(index):
        raise ValueError('Full retained weight history must share the price index')
    if type(execution_delay_sessions) is not int or execution_delay_sessions < 1:
        raise ValueError('execution_delay_sessions must be a positive integer')
    if not result.cash_weights.index.equals(index):
        raise ValueError('Cash history must share the price index')
    claims = getattr(result, 'receivable_weights', pd.Series(dtype=float))
    if len(claims) and not claims.index.equals(index):
        raise ValueError('Receivable history must share the price index')

    def complete_at(date):
        flag = result.valuation_available.get(date, True)
        return bool(flag) if pd.notna(flag) else False

    complete_index = index[[complete_at(date) for date in index]]

    def snapshot(date):
        # Search one precomputed valuation calendar rather than rescanning all
        # daily flags for every monthly signal.
        complete_position = complete_index.searchsorted(date, side='right') - 1
        if complete_position < 0:
            return dict(holdings=[], holdingsAsOf=None, cashWeight=None,
                        receivableWeight=None, liquidCashWeight=None,
                        valuationStatus='unavailable')
        valued = complete_index[complete_position]
        position = index.get_loc(valued)
        if position + 1 < len(index):
            # The engine saves this opening row before applying that next
            # session's corporate actions or cash settlements.
            weights = result.weights.iloc[position + 1]
            cash = float(result.cash_weights.iloc[position + 1])
            claim = float(claims.iloc[position + 1]) if len(claims) else 0.
        else:
            weights = result.ending_weights
            cash = float(result.ending_cash_weight)
            claim = float(getattr(result, 'ending_receivable_weight', 0.))
        return dict(holdings=holding_rows(weights), holdingsAsOf=str(valued.date()),
                    cashWeight=cash, receivableWeight=claim,
                    liquidCashWeight=cash - claim,
                    valuationStatus='available' if valued == date else 'last_complete')

    history = []
    for signal, target in sorted(targets.items()):
        signal = pd.Timestamp(signal)
        if signal not in index:
            raise ValueError('Signal must be on the supplied session index')
        position = index.get_loc(signal) + execution_delay_sessions
        pending = position >= len(index)
        execution = (pd.Timestamp(next_execution(signal, execution_delay_sessions))
                     if pending and next_execution is not None else
                     None if pending else index[position])
        observed = index[-1] if pending else execution
        current = snapshot(observed)
        execution_status = 'pending' if pending else result.execution_statuses.get(execution, 'none')
        active = bool(result.strategy_active.get(observed, False))
        if pending:
            status = 'pending'
        elif execution_status.startswith('executed'):
            status = 'executed'
        elif not complete_at(observed):
            status = 'valuation_unavailable'
        elif execution_status.startswith('blocked_'):
            status = 'blocked'
        elif target.status != 'available':
            status = 'deferred' if active else 'awaiting_first_signal'
        else:
            status = 'not_executed'
        history.append(dict(date=str(signal.date()), signalDate=str(signal.date()),
                            executionDate=str(execution.date()) if execution is not None else None,
                            status=status, executionStatus=execution_status,
                            targetStatus=target.status, targetReasons=list(target.reasons),
                            targetHoldings=holding_rows(target.weights()),
                            targetCashWeight=float(target.cash_weight),
                            turnover=None if pending else float(result.turnover.get(execution, 0.)),
                            cost=None if pending else float(result.costs.get(execution, 0.)),
                            **current))
    return dict(history=history, latest=snapshot(index[-1]),
                holdingsAsOf=str(index[-1].date()),
                historyBasis='execution_close_actual_weights')
