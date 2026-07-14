import json
import math
import sqlite3
import uuid
from datetime import datetime

from app.core.config import DATABASE_PATH


def _conn():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _columns(conn, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _ensure_column(conn, table: str, column: str, definition: str):
    if column not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db():
    with _conn() as c:
        c.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS backtest_runs (
            id TEXT PRIMARY KEY, created_at TEXT NOT NULL, symbol TEXT NOT NULL, strategy_type TEXT NOT NULL,
            start_date TEXT NOT NULL, end_date TEXT NOT NULL, parameters_json TEXT NOT NULL,
            metrics_json TEXT NOT NULL, chart_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS backtest_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, backtest_id TEXT NOT NULL, trade_date TEXT NOT NULL,
            side TEXT NOT NULL, price REAL NOT NULL, quantity REAL NOT NULL, notional REAL NOT NULL, reason TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS backtest_metrics (
            backtest_id TEXT NOT NULL, metric_name TEXT NOT NULL, metric_value REAL, metric_text TEXT,
            PRIMARY KEY(backtest_id, metric_name)
        );
        CREATE TABLE IF NOT EXISTS backtest_lots (
            id INTEGER PRIMARY KEY AUTOINCREMENT, backtest_id TEXT NOT NULL, lot_id TEXT NOT NULL,
            round_no INTEGER NOT NULL, layer_no INTEGER NOT NULL, buy_date TEXT NOT NULL, buy_price REAL NOT NULL,
            quantity REAL NOT NULL, cost REAL NOT NULL, buy_commission REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL, sell_date TEXT, sell_price REAL, sell_commission REAL NOT NULL DEFAULT 0,
            sell_tax REAL NOT NULL DEFAULT 0, realized_pnl REAL, return_pct REAL, exit_reason TEXT,
            UNIQUE(backtest_id, lot_id)
        );
        CREATE TABLE IF NOT EXISTS backtest_daily_equity (
            id INTEGER PRIMARY KEY AUTOINCREMENT, backtest_id TEXT NOT NULL, trade_date TEXT NOT NULL,
            price REAL NOT NULL, ma REAL, rolling_high REAL, cash REAL NOT NULL, shares REAL NOT NULL,
            market_value REAL NOT NULL, equity REAL NOT NULL, realized_profit REAL NOT NULL,
            unrealized_profit REAL NOT NULL, invested_cost REAL NOT NULL, active_layers INTEGER NOT NULL,
            drawdown REAL NOT NULL, anchor_price REAL, next_grid_price REAL,
            UNIQUE(backtest_id, trade_date)
        );
        CREATE INDEX IF NOT EXISTS idx_runs_created ON backtest_runs(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_trades_run ON backtest_trades(backtest_id);
        CREATE INDEX IF NOT EXISTS idx_lots_run ON backtest_lots(backtest_id);
        CREATE INDEX IF NOT EXISTS idx_equity_run ON backtest_daily_equity(backtest_id, trade_date);
        ''')
        _ensure_column(c, "backtest_runs", "data_metadata_json", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(c, "backtest_runs", "warnings_json", "TEXT NOT NULL DEFAULT '[]'")
        for name, definition in {
            "status": "TEXT NOT NULL DEFAULT 'FILLED'", "signal_date": "TEXT", "lot_id": "TEXT",
            "round_no": "INTEGER", "layer_no": "INTEGER", "commission": "REAL NOT NULL DEFAULT 0",
            "tax": "REAL NOT NULL DEFAULT 0", "cash_flow": "REAL NOT NULL DEFAULT 0", "realized_pnl": "REAL",
        }.items():
            _ensure_column(c, "backtest_trades", name, definition)


def _clean_number(value):
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def save_run(req, metrics, chart, trades, data_info=None, lots=None, curve=None, warnings=None) -> str:
    run_id = str(uuid.uuid4())
    data_info, lots, warnings = data_info or {}, lots or [], warnings or []
    with _conn() as c:
        c.execute('''
            INSERT INTO backtest_runs(
                id, created_at, symbol, strategy_type, start_date, end_date, parameters_json,
                metrics_json, chart_json, data_metadata_json, warnings_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ''', (
            run_id, datetime.now().isoformat(timespec="seconds"), req.symbol, req.strategy.value,
            str(req.start_date), str(req.end_date), req.model_dump_json(),
            json.dumps(metrics, ensure_ascii=False), json.dumps(chart, ensure_ascii=False),
            json.dumps(data_info, ensure_ascii=False), json.dumps(warnings, ensure_ascii=False),
        ))
        c.executemany('''
            INSERT INTO backtest_trades(
                backtest_id, trade_date, side, price, quantity, notional, reason, status, signal_date,
                lot_id, round_no, layer_no, commission, tax, cash_flow, realized_pnl
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ''', [(
            run_id, str(t.date), t.side, t.price, t.quantity, t.notional, t.reason, t.status,
            str(t.signal_date) if t.signal_date else None, t.lot_id, t.round_no, t.layer_no,
            t.commission, t.tax, t.cash_flow, t.realized_pnl,
        ) for t in trades])
        c.executemany('''
            INSERT INTO backtest_metrics(backtest_id, metric_name, metric_value, metric_text)
            VALUES (?,?,?,?)
        ''', [(
            run_id, key, float(value) if isinstance(value, (int, float)) and value is not None else None,
            None if isinstance(value, (int, float)) or value is None else str(value),
        ) for key, value in metrics.items()])
        if lots:
            c.executemany('''
                INSERT INTO backtest_lots(
                    backtest_id, lot_id, round_no, layer_no, buy_date, buy_price, quantity, cost,
                    buy_commission, status, sell_date, sell_price, sell_commission, sell_tax,
                    realized_pnl, return_pct, exit_reason
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''', [(
                run_id, lot.lot_id, lot.round_no, lot.layer_no, str(lot.buy_date), lot.buy_price,
                lot.quantity, lot.cost, lot.buy_commission, lot.status, str(lot.sell_date) if lot.sell_date else None,
                lot.sell_price, lot.sell_commission, lot.sell_tax, lot.realized_pnl, lot.return_pct, lot.exit_reason,
            ) for lot in lots])
        if curve is not None and not curve.empty:
            c.executemany('''
                INSERT INTO backtest_daily_equity(
                    backtest_id, trade_date, price, ma, rolling_high, cash, shares, market_value,
                    equity, realized_profit, unrealized_profit, invested_cost, active_layers,
                    drawdown, anchor_price, next_grid_price
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''', [(
                run_id, str(row["date"]), float(row["price"]), _clean_number(row.get("ma")),
                _clean_number(row.get("rolling_high")), float(row["cash"]), float(row["shares"]),
                float(row["market_value"]), float(row["equity"]), float(row.get("realized_profit", 0)),
                float(row.get("unrealized_profit", 0)), float(row.get("invested_cost", 0)),
                int(row.get("active_layers", 0)), float(row["drawdown"]), _clean_number(row.get("anchor_price")),
                _clean_number(row.get("next_grid_price")),
            ) for _, row in curve.iterrows()])
    return run_id


def list_runs(limit: int = 50):
    with _conn() as c:
        rows = c.execute('''
            SELECT id,created_at,symbol,strategy_type,start_date,end_date,metrics_json,data_metadata_json
            FROM backtest_runs ORDER BY created_at DESC LIMIT ?
        ''', (limit,)).fetchall()
    return [{**dict(row), "metrics": json.loads(row["metrics_json"]),
             "data_info": json.loads(row["data_metadata_json"] or "{}")} for row in rows]


def get_run(run_id: str):
    with _conn() as c:
        row = c.execute("SELECT * FROM backtest_runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            return None
        trades = c.execute('''
            SELECT trade_date AS date,signal_date,side,status,price,quantity,notional,commission,tax,
                   cash_flow,realized_pnl,lot_id,round_no,layer_no,reason
            FROM backtest_trades WHERE backtest_id=? ORDER BY trade_date,id
        ''', (run_id,)).fetchall()
        lots = c.execute('''
            SELECT lot_id,round_no,layer_no,buy_date,buy_price,quantity,cost,buy_commission,status,
                   sell_date,sell_price,sell_commission,sell_tax,realized_pnl,return_pct,exit_reason
            FROM backtest_lots WHERE backtest_id=? ORDER BY round_no,layer_no
        ''', (run_id,)).fetchall()
        equity = c.execute('''
            SELECT trade_date AS date,price,ma,rolling_high,cash,shares,market_value,equity,
                   realized_profit,unrealized_profit,invested_cost,active_layers,drawdown,anchor_price,next_grid_price
            FROM backtest_daily_equity WHERE backtest_id=? ORDER BY trade_date
        ''', (run_id,)).fetchall()
    result = dict(row)
    result["parameters"] = json.loads(result.pop("parameters_json"))
    result["metrics"] = json.loads(result.pop("metrics_json"))
    result["charts"] = json.loads(result.pop("chart_json"))
    result["data_info"] = json.loads(result.pop("data_metadata_json") or "{}")
    result["warnings"] = json.loads(result.pop("warnings_json") or "[]")
    result["trades"] = [dict(t) for t in trades]
    result["lots"] = [dict(x) for x in lots]
    result["daily_equity"] = [dict(x) for x in equity]
    return result
