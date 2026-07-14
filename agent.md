# AI 维护说明：stock_look_back

## 项目边界

- `frontend/`：Vite + React + TypeScript + Tailwind + Plotly 的中文界面。
- `backend/`：FastAPI、AkShare、Pandas、SQLite 的本地回测 API。
- `backend/app/backtest/quality_grid.py`：质量过滤逐笔网格的唯一策略实现。
- `backend/app/data/provider.py`：行情适配、缓存、数据源元数据、代码简称查询。
- `backend/app/db/repository.py`：SQLite 兼容迁移与明确列名写入。

AkShare、回测和 SQLite 均在本地 FastAPI 中运行；前端仅调用 `http://127.0.0.1:8000/api/v1`。不要将该项目改为 Vercel、Lovable 或公网部署架构，除非用户明确提出新的部署需求。

## 目标买点功能

- 接口：`POST /api/v1/target-entry`。
- 使用最新可用日线的收盘价、过去 `lookback_days` 的最高收盘和 `ma_window` 均线。
- `target_buy_price` 必须是回撤阈值价和 MA 阈值价的较低者，不能取平均或较高者。
- 仅供决策辅助，不会创建订单或写入回测记录。

## 关键策略规则

1. 信号用当日收盘价，成交用下一交易日开盘价。
2. 首仓须经 `quality_confirmed` 明确确认，价格数据不能代替财务质量筛选。
3. 四层补仓锚定本轮首仓实际成交价；单日最多一层。
4. 每个 lot 独立全量止盈；禁止把一个 lot 拆成两笔卖出。
5. 组合清仓仅处理剩余 lot；期末不可强制平仓。再入场跌幅为 `0` 时，取消相对最终清仓价的价格限制。
6. `max_strategy_cash` 是硬上限。整手标的在订单金额不足一手、但资金池充足时，自动提升到一手实际成本；绝不融资。

## 数据约定

- 标准行情列：`date, symbol, open, high, low, close, adj_close, volume`。
- A 股：东方财富 qfq → 新浪 qfq 回退。
- ETF：东方财富 qfq → 新浪未复权回退；必须保留醒目警告。
- 美股：Yahoo Finance 自动复权 OHLC；代码支持 AAPL、MSFT、BRK.B。
- 缓存的 `.meta.json` 要保留 `source`、`price_type`、`warning`、`last_updated` 和请求覆盖区间，避免 IPO 前无数据时反复联网。

## 数据库

必须使用明确列名的 INSERT。涉及表：

- `backtest_runs`
- `backtest_metrics`
- `backtest_trades`
- `backtest_lots`
- `backtest_daily_equity`

修改 schema 时要兼容已有 SQLite 文件，并新增对应持久化与读取测试。

## 修改前检查

- 先执行 `python -m unittest discover -s backend\tests -v`。
- 前端修改后执行 `cd frontend; npm run build`。
- 数据源调整时至少验证一个真实 ETF 和一个真实 A 股；网络失败要返回明确错误，不可静默空结果。
- 当前仓库可能没有 `.git`；初始化、同步或覆盖远端前必须先检查远端引用。

## 修改历史

- 2026-07-11：建立 FastAPI + React + SQLite + AkShare 回测骨架。
- 2026-07-14：加入 Quality Grid 独立 lot、下一开盘成交、SQLite 明细、ETF 新浪回退与可视化。
- 2026-07-14：加入 A 股新浪回退、缓存覆盖元数据、代码简称显示和核心/设置参数分层。
- 2026-07-14：默认资金池改为 100 万、首仓 2 万、质量确认默认勾选、360 日回撤/MA120，并加入一手资金自动补足规则。
- 2026-07-14：新增最新目标买点接口和页面卡片；目标价取回撤价与 MA 阈值价的较低者。
- 2026-07-14：移除 Vercel 配置，明确项目仅通过 GitHub 同步并在本地运行。
- 2026-07-14：美股历史日线改用 Yahoo Finance 自动复权数据源。
