# stock_look_back｜本地股票 / ETF 回测

一个不依赖 TradingView 的中文量化研究工具。它用 AkShare 获取 A 股和 ETF 日线，用 FastAPI 执行日频策略回测，用 React + Plotly 展示参数、权益曲线、交易流水和逐笔 lot，SQLite 保存每次回测。

> 回测不构成投资建议。个股基本面质量筛选目前由用户确认；后续接入财务数据时必须按公告日对齐，禁止前视。

## 快速使用

1. 输入 A 股或 ETF 代码，例如 `603728`、`600519`、`513500`。
2. 代码右侧会自动显示证券简称；名称查询失败不会影响回测。
3. 在主面板设置日期与四个核心低位条件，点击“开始回测”。
4. 需要调整资金、补仓、止盈、费用或质量确认时，打开“设置”TAB。

## 默认参数（质量过滤逐笔网格）

- 已通过质量筛选：默认勾选；
- 策略资金池：1,000,000 元；
- 首仓金额：20,000 元；
- 回撤回看：360 个交易日；
- MA：120 日；
- 最高收盘回撤：30%；
- 低于 MA：15%；
- 入场条件：同时满足；
- 四层补仓：相对首仓成交价下跌 5% / 10% / 15% / 20%，金额 1x / 2x / 2x / 2x；
- 单 lot 止盈：5%，组合清仓：10%，再入场回撤：5%。

A 股或关闭碎股的 ETF，若默认订单金额不足一手且资金池可覆盖，会自动提高至一手实际所需资金（含费用）；资金池仍为硬上限，不会透支或融资。

## 策略口径

- 所有信号使用当日收盘价计算，并在下一交易日开盘成交；最后一天的信号不会被强制成交。
- 每笔买入都是独立 lot；达到该 lot 实际成本 + 止盈阈值后，全量卖出，不拆单。
- 补仓只锚定本轮首仓的实际成交价，不用平均成本。
- 组合清仓只关闭剩余 lot；清仓后必须满足相对最终卖出价的再入场回撤和低位条件。
- 回测结束不强平，未平仓 lot 按最后收盘价计入未实现收益。

## 行情与缓存

- A 股：东方财富前复权优先，失败时回退新浪前复权日线。
- ETF：东方财富前复权优先，失败时回退新浪未复权日线，并在页面提示风险。
- 历史行情和数据源元数据保存在 `backend/data_cache/`。
- 数据源全部失败时会返回明确错误，绝不生成伪造回测结果。

## 本地启动

需要 Python 3.11+、Node.js 20+。

```powershell
cd "E:\OneDrive\1. AI\股票基金回测\backend"
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python main.py
```

另开 PowerShell：

```powershell
cd "E:\OneDrive\1. AI\股票基金回测\frontend"
npm install
npm run dev
```

前端：<http://localhost:5173>；API 文档：<http://127.0.0.1:8000/docs>。

## Vercel 部署说明

本仓库的 Vercel 配置部署的是 React 前端。生产环境必须提供一个公网可访问的 FastAPI 后端，并在 Vercel 配置 `VITE_API_BASE_URL=https://你的后端域名/api/v1`；否则网页只能展示界面，无法拉取 AkShare 行情或运行回测。

FastAPI + AkShare + SQLite 适合部署在 VPS、Render 或 Railway 的持久化服务中；不要将 SQLite 数据库当作 Vercel Serverless 的持久化存储。

## 验证

```powershell
cd "E:\OneDrive\1. AI\股票基金回测"
python -m unittest discover -s backend\tests -v
python -m compileall backend\app backend\main.py
cd frontend
npm run build
```
