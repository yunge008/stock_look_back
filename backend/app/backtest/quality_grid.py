"""Quality Grid: quality-gated, finite grid with independent lot exits."""
from datetime import date
import math

import numpy as np
import pandas as pd

from app.core.config import RISK_FREE_RATE, TRADING_DAYS_PER_YEAR
from app.domain.models import BacktestRequest, LotRecord, Trade


def _commission(notional: float, req: BacktestRequest) -> float:
    return max(notional * req.commission_rate, req.min_commission) if notional > 0 else 0.0


def _buy_quantity(target: float, cash: float, price: float, lot_size: int, req: BacktestRequest) -> tuple[float, float]:
    if target <= 0 or cash <= 0 or price <= 0:
        return 0.0, 0.0
    # The configured amount is normally the order notional plus its fee.  For
    # board-lot instruments, raise an undersized order to exactly one lot when
    # the strategy cash pool can pay for it; never exceed available cash.
    budget_total = min(cash, target + max(req.min_commission, 1e-9))
    if lot_size > 1:
        one_lot_notional = price * lot_size
        one_lot_total = one_lot_notional + _commission(one_lot_notional, req)
        if budget_total < one_lot_total <= cash:
            budget_total = one_lot_total
        qty = math.floor(budget_total / price / lot_size) * lot_size
    else:
        qty = math.floor((budget_total / price) * 1_000_000) / 1_000_000
    while qty > 0:
        notional = qty * price
        fee = _commission(notional, req)
        if notional + fee <= budget_total + 1e-9 and notional + fee <= cash + 1e-9:
            return float(qty), float(fee)
        qty = qty - lot_size if lot_size > 1 else math.floor((qty - 0.000001) * 1_000_000) / 1_000_000
    return 0.0, 0.0


def _entry_signal(row: pd.Series, req: BacktestRequest) -> bool:
    drawdown_ok = pd.notna(row["rolling_high"]) and row["price"] <= row["rolling_high"] * (1 - req.entry_drawdown_pct)
    ma_ok = pd.notna(row["ma"]) and row["price"] <= row["ma"] * (1 - req.ma_discount_pct)
    return (drawdown_ok and ma_ok) if req.entry_condition_mode == "all" else (drawdown_ok or ma_ok)


def _calculate_metrics(curve: pd.DataFrame, realized: float, completed_rounds: int, has_open_round: bool,
                       max_layers: int, last_final_exit_price: float | None, initial_cash: float,
                       lots: list[dict]) -> dict:
    values = curve["equity"].astype(float)
    drawdown = values / values.cummax() - 1
    daily = values.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    years = max((len(curve) - 1) / TRADING_DAYS_PER_YEAR, 1 / TRADING_DAYS_PER_YEAR)
    ending = float(values.iloc[-1])
    total_return = ending / initial_cash - 1 if initial_cash else 0.0
    cagr = (ending / initial_cash) ** (1 / years) - 1 if initial_cash > 0 and ending > 0 else -1.0
    volatility = float(daily.std(ddof=1) * math.sqrt(TRADING_DAYS_PER_YEAR)) if len(daily) > 1 else 0.0
    sharpe = (float(daily.mean()) * TRADING_DAYS_PER_YEAR - RISK_FREE_RATE) / volatility if volatility > 0 else None
    trough_pos = int(np.argmin(drawdown.to_numpy()))
    peak_pos = int(np.argmax(values.iloc[:trough_pos + 1].to_numpy()))
    last = curve.iloc[-1]
    max_used = float(curve["invested_cost"].max())
    total_profit = realized + float(last["unrealized_profit"])
    # Count only daily bars that end with open lots. Empty waiting periods do not
    # dilute this return, while an exit executed at the next open ends occupancy.
    invested_occupied_days = int((curve["invested_cost"] > 1e-9).sum())
    invested_years = max(invested_occupied_days / TRADING_DAYS_PER_YEAR, 1 / TRADING_DAYS_PER_YEAR) if max_used > 0 else 0.0
    invested_annualized = (
        (1 + total_profit / max_used) ** (1 / invested_years) - 1
        if max_used > 0 and 1 + total_profit / max_used > 0
        else -1.0 if max_used > 0 else 0.0
    )
    holding_days = [lot["holding_days"] for lot in lots]
    closed_pnls = [float(lot["realized_pnl"]) for lot in lots if lot["status"] == "CLOSED"]
    open_pnls = [float(last["price"] * lot["quantity"] - lot["cost"]) for lot in lots if lot["status"] == "OPEN"]
    all_pnls = closed_pnls + open_pnls
    return {
        "realized_profit": float(realized),
        "unrealized_profit": float(last["unrealized_profit"]),
        "ending_equity": ending,
        "total_return": float(total_return),
        "annualized_return": float(cagr),
        "cagr": float(cagr),
        "max_drawdown": float(drawdown.iloc[trough_pos]),
        "max_drawdown_start": str(curve["date"].iloc[peak_pos]),
        "max_drawdown_end": str(curve["date"].iloc[trough_pos]),
        "annual_volatility": volatility,
        "sharpe_ratio": None if sharpe is None else float(sharpe),
        "max_strategy_cash_used": max_used,
        "invested_capital_return": float(total_profit / max_used) if max_used > 0 else 0.0,
        "invested_capital_annualized_return": float(invested_annualized),
        "invested_capital_occupied_days": invested_occupied_days,
        "max_holding_days": max(holding_days, default=0),
        "min_holding_days": min(holding_days, default=0),
        "average_holding_days": float(np.mean(holding_days)) if holding_days else 0.0,
        "win_rate_closed_only": sum(pnl > 0 for pnl in closed_pnls) / len(closed_pnls) if closed_pnls else None,
        "win_rate_all_lots": sum(pnl > 0 for pnl in all_pnls) / len(all_pnls) if all_pnls else None,
        "open_lot_count": len(open_pnls),
        "open_lot_ratio": len(open_pnls) / len(lots) if lots else 0.0,
        "max_concurrent_layers": int(max_layers),
        "completed_rounds": int(completed_rounds),
        "incomplete_rounds": 1 if has_open_round else 0,
        "current_cash": float(last["cash"]),
        "current_market_value": float(last["market_value"]),
        "current_quantity": float(last["shares"]),
        "last_final_exit_price": last_final_exit_price,
    }


def run_quality_grid(data: pd.DataFrame, req: BacktestRequest, instrument_kind: str) -> tuple[dict, list[Trade], list[LotRecord], pd.DataFrame, list[str]]:
    raw = data.copy().sort_values("date").reset_index(drop=True)
    raw["price"] = pd.to_numeric(raw["close"], errors="coerce")
    raw["ma"] = raw["price"].rolling(req.ma_window, min_periods=req.ma_window).mean()
    raw["rolling_high"] = raw["price"].rolling(req.lookback_days, min_periods=req.lookback_days).max()
    frame = raw[raw["date"] >= req.start_date].reset_index(drop=True)
    if frame.empty:
        raise ValueError("回测区间没有交易日。")
    if not req.quality_confirmed:
        quality_warning = "尚未确认质量筛选，本策略不会建立首仓。个股基本面需按公告日对齐，不能前视。"
    else:
        quality_warning = None

    lot_size = 100 if (instrument_kind == "a_stock" and req.enforce_a_share_board_lot) or (instrument_kind == "etf" and not req.allow_fractional_etf) else 1
    cash = float(req.max_strategy_cash)
    realized = 0.0
    trades: list[Trade] = []
    lots: list[dict] = []
    rows: list[dict] = []
    warnings: list[str] = [quality_warning] if quality_warning else []
    pending: list[dict] = []
    current_round: int | None = None
    next_round = 1
    anchor_price: float | None = None
    triggered_layers: set[int] = set()
    last_final_exit_price: float | None = None
    completed_rounds = 0
    max_layers = 0

    def open_lots() -> list[dict]:
        return [lot for lot in lots if lot["status"] == "OPEN"]

    for _, bar in frame.iterrows():
        day: date = bar["date"]
        open_price = float(bar["open"] if pd.notna(bar["open"]) and bar["open"] > 0 else bar["price"])

        # Execute only orders generated from the previous trading day's close.
        if pending:
            closing_before = bool(open_lots())
            exit_prices: list[float] = []
            for order in pending:
                if order["side"] == "BUY":
                    actual_price = open_price * (1 + req.slippage_pct)
                    qty, fee = _buy_quantity(order["target_cash"], cash, actual_price, lot_size, req)
                    if qty <= 0:
                        reason = f'{order["reason"]}（资金不足或整手约束，未成交）'
                        trades.append(Trade(date=day, signal_date=order["signal_date"], side="BUY", price=actual_price,
                                            quantity=0, notional=0, reason=reason, status="SKIPPED",
                                            round_no=order["round_no"], layer_no=order["layer_no"]))
                        warnings.append(f"{day} {reason}")
                        continue
                    notional = qty * actual_price
                    cost = notional + fee
                    cash -= cost
                    round_no, layer_no = order["round_no"], order["layer_no"]
                    lot_id = f"R{round_no}-L{layer_no}"
                    lots.append({
                        "lot_id": lot_id, "round_no": round_no, "layer_no": layer_no, "buy_date": day,
                        "buy_price": actual_price, "quantity": qty, "cost": cost, "buy_commission": fee, "status": "OPEN",
                        "sell_date": None, "sell_price": None, "sell_commission": 0.0, "sell_tax": 0.0,
                        "realized_pnl": None, "return_pct": None, "exit_reason": None, "holding_days": 0,
                    })
                    if layer_no == 0:
                        current_round = round_no
                        next_round = max(next_round, round_no + 1)
                        anchor_price = actual_price
                        triggered_layers = {0}
                    else:
                        triggered_layers.add(layer_no)
                    trades.append(Trade(date=day, signal_date=order["signal_date"], side="BUY", price=actual_price,
                                        quantity=qty, notional=notional, reason=order["reason"], lot_id=lot_id,
                                        round_no=round_no, layer_no=layer_no, commission=fee, cash_flow=-cost))
                else:
                    lot = next((x for x in lots if x["lot_id"] == order["lot_id"] and x["status"] == "OPEN"), None)
                    if lot is None:
                        continue
                    actual_price = open_price * (1 - req.slippage_pct)
                    notional = lot["quantity"] * actual_price
                    fee = _commission(notional, req)
                    tax = notional * req.sell_tax_rate
                    proceeds = notional - fee - tax
                    pnl = proceeds - lot["cost"]
                    cash += proceeds
                    realized += pnl
                    lot.update({
                        "status": "CLOSED", "sell_date": day, "sell_price": actual_price,
                        "sell_commission": fee, "sell_tax": tax, "realized_pnl": pnl,
                        "return_pct": pnl / lot["cost"] if lot["cost"] else 0.0, "exit_reason": order["reason"],
                        "holding_days": (day - lot["buy_date"]).days,
                    })
                    exit_prices.append(actual_price)
                    trades.append(Trade(date=day, signal_date=order["signal_date"], side="SELL", price=actual_price,
                                        quantity=lot["quantity"], notional=notional, reason=order["reason"], lot_id=lot["lot_id"],
                                        round_no=lot["round_no"], layer_no=lot["layer_no"], commission=fee, tax=tax,
                                        cash_flow=proceeds, realized_pnl=pnl))
            pending = []
            if closing_before and not open_lots():
                completed_rounds += 1
                last_final_exit_price = exit_prices[-1] if exit_prices else last_final_exit_price
                current_round, anchor_price, triggered_layers = None, None, set()

        price = float(bar["price"])
        active = open_lots()
        max_layers = max(max_layers, len(active))

        # Generate close-based signals. They are filled at the next bar's open.
        if active:
            qty_total = sum(x["quantity"] for x in active)
            weighted_cost = sum(x["cost"] for x in active) / qty_total
            basket_hit = req.basket_take_profit_enabled and price + 1e-10 >= weighted_cost * (1 + req.basket_take_profit_pct)
            if basket_hit:
                pct = req.basket_take_profit_pct * 100
                pending = [{"side": "SELL", "lot_id": x["lot_id"], "signal_date": day, "reason": f"组合+{pct:g}%清仓"} for x in active]
            else:
                hit_lots: list[tuple[dict, float]] = []
                for lot in active:
                    holding_days = max((day - lot["buy_date"]).days, 0)
                    decay_periods = holding_days // req.holding_profit_decay_days
                    required_profit_pct = max(
                        req.lot_take_profit_pct - decay_periods * req.holding_profit_decay_pct,
                        0.0,
                    )
                    if price + 1e-10 >= (lot["cost"] / lot["quantity"]) * (1 + required_profit_pct):
                        hit_lots.append((lot, required_profit_pct))
                if hit_lots:
                    pending = [{"side": "SELL", "lot_id": lot["lot_id"], "signal_date": day,
                                "reason": f'Lot {lot["lot_id"]} +{required_pct * 100:g}%止盈'}
                               for lot, required_pct in hit_lots]
                elif anchor_price is not None:
                    for layer_no, drop in enumerate(req.grid_drop_pcts, start=1):
                        if layer_no not in triggered_layers and price <= anchor_price * (1 - drop):
                            pending = [{
                                "side": "BUY", "signal_date": day, "round_no": current_round, "layer_no": layer_no,
                                "target_cash": req.base_cash * req.grid_cash_multipliers[layer_no - 1],
                                "reason": f"第{layer_no}层补仓",
                            }]
                            break
        elif req.quality_confirmed and _entry_signal(bar, req):
            # A zero threshold explicitly disables the price-vs-last-exit restriction.
            reentry_ok = (
                last_final_exit_price is None
                or req.reentry_drop_pct == 0
                or price <= last_final_exit_price * (1 - req.reentry_drop_pct)
            )
            if reentry_ok:
                pending = [{
                    "side": "BUY", "signal_date": day, "round_no": next_round, "layer_no": 0,
                    "target_cash": req.base_cash, "reason": "首仓",
                }]

        active = open_lots()
        shares = sum(x["quantity"] for x in active)
        market_value = shares * price
        invested_cost = sum(x["cost"] for x in active)
        unrealized = market_value - invested_cost
        next_grid = None
        if anchor_price is not None:
            next_layer = next((i for i in range(1, len(req.grid_drop_pcts) + 1) if i not in triggered_layers), None)
            if next_layer is not None:
                next_grid = anchor_price * (1 - req.grid_drop_pcts[next_layer - 1])
        rows.append({
            "date": day, "price": price, "ma": None if pd.isna(bar["ma"]) else float(bar["ma"]),
            "rolling_high": None if pd.isna(bar["rolling_high"]) else float(bar["rolling_high"]),
            "cash": cash, "shares": shares, "market_value": market_value, "holding_market_value": market_value, "equity": cash + market_value,
            "realized_profit": realized, "unrealized_profit": unrealized, "invested_cost": invested_cost,
            "active_layers": len(active), "anchor_price": anchor_price, "next_grid_price": next_grid,
        })

    # Signals on the final bar intentionally remain unfilled; record why instead of forcing a close.
    for order in pending:
        trades.append(Trade(
            date=order["signal_date"], signal_date=order["signal_date"], side=order["side"], price=0,
            quantity=0, notional=0, status="SKIPPED", lot_id=order.get("lot_id"), round_no=order.get("round_no"),
            layer_no=order.get("layer_no"), reason=f'{order["reason"]}（无下一交易日，未成交）',
        ))
        warnings.append(f'{order["signal_date"]} {order["reason"]}：无下一交易日，未成交。')

    final_day = frame["date"].iloc[-1]
    if req.force_close_at_end and open_lots():
        final_close = float(frame["price"].iloc[-1]) * (1 - req.slippage_pct)
        for lot in list(open_lots()):
            notional = lot["quantity"] * final_close
            fee = _commission(notional, req)
            tax = notional * req.sell_tax_rate
            proceeds = notional - fee - tax
            pnl = proceeds - lot["cost"]
            cash += proceeds
            realized += pnl
            lot.update({
                "status": "CLOSED", "sell_date": final_day, "sell_price": final_close,
                "sell_commission": fee, "sell_tax": tax, "realized_pnl": pnl,
                "return_pct": pnl / lot["cost"] if lot["cost"] else 0.0,
                "exit_reason": "回测到期强制平仓", "holding_days": (final_day - lot["buy_date"]).days,
            })
            trades.append(Trade(
                date=final_day, signal_date=final_day, side="SELL", price=final_close,
                quantity=lot["quantity"], notional=notional, reason="回测到期强制平仓",
                lot_id=lot["lot_id"], round_no=lot["round_no"], layer_no=lot["layer_no"],
                commission=fee, tax=tax, cash_flow=proceeds, realized_pnl=pnl,
            ))
        completed_rounds += 1
        last_final_exit_price = final_close
        current_round, anchor_price, triggered_layers = None, None, set()
        rows[-1].update({
            "cash": cash, "shares": 0.0, "market_value": 0.0, "equity": cash,
            "realized_profit": realized, "unrealized_profit": 0.0, "invested_cost": 0.0,
            "active_layers": 0, "anchor_price": None, "next_grid_price": None,
        })

    curve = pd.DataFrame(rows)
    curve["drawdown"] = curve["equity"] / curve["equity"].cummax() - 1
    for lot in open_lots():
        lot["holding_days"] = (final_day - lot["buy_date"]).days
    metrics = _calculate_metrics(curve, realized, completed_rounds, bool(open_lots()), max_layers,
                                 last_final_exit_price, req.max_strategy_cash, lots)
    return metrics, trades, [LotRecord.model_validate(x) for x in lots], curve, list(dict.fromkeys(warnings))
