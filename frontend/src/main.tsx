import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import Plot from 'react-plotly.js';
import './index.css';

const API = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api/v1';

type Result = {
  id?: string;
  metrics: Record<string, number | string | null>;
  charts: Record<string, any>;
  trades: any[];
  lots: any[];
  daily_equity: any[];
  symbol: string;
  strategy: string;
  execution_mode: string;
  data_info: Record<string, any>;
  warnings: string[];
};

const fmt = (v: any, pct = false) => v == null ? '—' : pct
  ? `${(Number(v) * 100).toFixed(2)}%`
  : Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 2 });

const initial = {
  symbol: '513500', strategy: 'quality_grid', start_date: '2018-01-01', end_date: new Date().toISOString().slice(0, 10),
  initial_cash: 100000, monthly_contribution: 5000, contribution_day: 1, ma_window: 120,
  lower_threshold: -0.05, upper_threshold: 0.05, extra_buy_amount: 10000, sell_ratio: 0.2,
  allow_margin: false, rebalance_tolerance: 0.01,
  max_strategy_cash: 1000000, base_cash: 20000, quality_confirmed: true, lookback_days: 360,
  entry_drawdown_pct: 0.30, ma_discount_pct: 0.15, entry_condition_mode: 'all',
  grid_drop_pcts: [0.05, 0.10, 0.15, 0.20], grid_cash_multipliers: [1, 2, 2, 2],
  lot_take_profit_pct: 0.05, basket_take_profit_enabled: true, basket_take_profit_pct: 0.10,
  reentry_drop_pct: 0.05, commission_rate: 0.0003, min_commission: 5,
  sell_tax_rate: 0.001, slippage_pct: 0.0005, enforce_a_share_board_lot: true,
  allow_fractional_etf: false, execution_mode: 'next_open',
};

function Field({ label, name, value, onChange, type = 'number', step = 'any', hint }: any) {
  return <div><label>{label}</label><input name={name} type={type} step={step} value={value} onChange={onChange}/>{hint && <p className="hint">{hint}</p>}</div>;
}

function PercentField({ label, name, value, setForm, form, hint }: any) {
  return <div><label>{label}</label><div className="relative"><input type="number" step="0.01" value={(Number(value) * 100).toFixed(3).replace(/0+$/, '').replace(/\.$/, '')} onChange={e => setForm({ ...form, [name]: Number(e.target.value) / 100 })}/><span className="suffix">%</span></div>{hint && <p className="hint">{hint}</p>}</div>;
}

function Toggle({ label, name, checked, onChange, hint }: any) {
  return <div><label className="toggle"><input type="checkbox" name={name} checked={checked} onChange={onChange}/><span>{label}</span></label>{hint && <p className="hint ml-6">{hint}</p>}</div>;
}

function App() {
  const [form, setForm] = useState<any>(initial);
  const [result, setResult] = useState<Result | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [tab, setTab] = useState('equity');
  const [tableTab, setTableTab] = useState('trades');
  const [settingsTab, setSettingsTab] = useState<'core' | 'settings'>('core');
  const [instrumentName, setInstrumentName] = useState('');
  const [targetEntry, setTargetEntry] = useState<any>(null);
  const [targetLoading, setTargetLoading] = useState(false);

  const change = (e: any) => {
    const strings = ['symbol', 'strategy', 'start_date', 'end_date', 'entry_condition_mode', 'execution_mode'];
    setForm({ ...form, [e.target.name]: e.target.type === 'checkbox' ? e.target.checked : strings.includes(e.target.name) ? e.target.value : Number(e.target.value) });
  };
  const setGrid = (key: 'grid_drop_pcts' | 'grid_cash_multipliers', index: number, value: number) => {
    const next = [...form[key]]; next[index] = value; setForm({ ...form, [key]: next });
  };
  async function lookupInstrument() {
    const symbol = String(form.symbol || '').trim().toUpperCase();
    if (!symbol) { setInstrumentName(''); return; }
    try {
      const response = await fetch(`${API}/instruments/${encodeURIComponent(symbol)}/availability`);
      const body = await response.json();
      setInstrumentName(response.ok && body.name ? body.name : '名称暂不可用');
    } catch { setInstrumentName('名称暂不可用'); }
  }
  async function fetchTargetEntry() {
    setTargetLoading(true); setError('');
    try {
      const payload = {
        symbol: form.symbol, lookback_days: form.lookback_days, ma_window: form.ma_window,
        entry_drawdown_pct: form.entry_drawdown_pct, ma_discount_pct: form.ma_discount_pct,
      };
      const response = await fetch(`${API}/target-entry`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || '目标买点计算失败');
      setTargetEntry(body.target);
    } catch (err: any) {
      setError(err.message === 'Failed to fetch' ? '无法连接回测后端。线上页面需要配置 VITE_API_BASE_URL 指向公网 FastAPI 服务；本地请先运行 backend/python main.py。' : err.message);
    } finally { setTargetLoading(false); }
  }
  async function submit(e: any) {
    e.preventDefault(); setLoading(true); setError('');
    try {
      const response = await fetch(`${API}/backtests`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(form) });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || '回测请求失败');
      setResult(body); setTab('equity');
    } catch (err: any) { setError(err.message === 'Failed to fetch' ? '无法连接回测后端。线上页面需要配置 VITE_API_BASE_URL 指向公网 FastAPI 服务；本地请先运行 backend/python main.py。' : err.message); } finally { setLoading(false); }
  }

  const quality = form.strategy === 'quality_grid';
  const cards = result && result.strategy === 'quality_grid' ? [
    { title: '已实现收益', key: 'realized_profit' }, { title: '未实现收益', key: 'unrealized_profit' },
    { title: '期末权益', key: 'ending_equity' }, { title: '总收益率', key: 'total_return', pct: true },
    { title: 'CAGR', key: 'cagr', pct: true }, { title: '最大回撤', key: 'max_drawdown', pct: true },
    { title: '夏普', key: 'sharpe_ratio' }, { title: '最大资金占用', key: 'max_strategy_cash_used' },
    { title: '已投入资金收益率', key: 'invested_capital_return', pct: true },
    { title: '投入资金年化回报率', key: 'invested_capital_annualized_return', pct: true }, { title: '已完成轮次', key: 'completed_rounds' },
    { title: '未完成轮次', key: 'incomplete_rounds' }, { title: '当前现金', key: 'current_cash' },
    { title: '当前持仓市值', key: 'current_market_value' }, { title: '当前持仓数量', key: 'current_quantity' },
  ] : result ? [
    { title: '最终资产', key: 'ending_equity' }, { title: '总收益率', key: 'total_return', pct: true },
    { title: '年化收益率', key: 'annualized_return', pct: true }, { title: '最大回撤', key: 'max_drawdown', pct: true },
    { title: '夏普比率', key: 'sharpe_ratio' }, { title: '资金利用率', key: 'capital_utilization', pct: true },
  ] : [];

  return <main className="mx-auto max-w-[1500px] p-4 md:p-8">
    <header className="mb-7">
      <p className="mb-1 text-sm font-semibold text-blue-600">LOCAL AKSHARE QUANT LAB</p>
      <h1 className="m-0 text-3xl font-bold">本地策略回测窗口</h1>
      <p className="text-slate-500">AkShare 日线 · FastAPI + SQLite · Plotly 交互图表 · 不依赖 TradingView</p>
    </header>
    <div className="grid gap-6 xl:grid-cols-[390px_1fr]">
      <form onSubmit={submit} className="h-fit rounded-2xl bg-white p-5 shadow-sm xl:max-h-[calc(100vh-4rem)] xl:overflow-y-auto">
        <h2 className="mt-0 text-lg">回测参数</h2>
        <div className="grid gap-4">
          <div><label>股票 / ETF / 美股 / 港股代码</label><div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2"><input name="symbol" type="text" value={form.symbol} onChange={change} onBlur={lookupInstrument}/><span className="instrument-name">{instrumentName || "输入后识别名称"}</span></div><p className="hint">例如：600519、513500、AAPL、MSFT、BRK.B、00700、09988（美股 / 港股使用 Yahoo Finance；港股输入 5 位纯数字）</p></div>
          <button className="rounded-lg bg-blue-600 px-4 py-3 font-semibold text-white hover:bg-blue-700 disabled:bg-slate-400" disabled={loading}>{loading ? '正在获取行情、计算并保存…' : '开始回测'}</button>
          <div className="flex border-b border-slate-200">
            <button type="button" onClick={() => setSettingsTab('core')} className={`border-b-2 px-3 py-2 text-sm ${settingsTab === 'core' ? 'border-blue-600 text-blue-600' : 'border-transparent text-slate-500'}`}>核心参数</button>
            <button type="button" onClick={() => setSettingsTab('settings')} className={`border-b-2 px-3 py-2 text-sm ${settingsTab === 'settings' ? 'border-blue-600 text-blue-600' : 'border-transparent text-slate-500'}`}>设置</button>
          </div>

          {settingsTab === 'core' ? <>
            <div className="grid grid-cols-2 gap-3"><Field label="开始日期" name="start_date" value={form.start_date} onChange={change} type="date"/><Field label="结束日期" name="end_date" value={form.end_date} onChange={change} type="date"/></div>
            <div className="grid grid-cols-2 gap-3"><Field label="回撤回看交易日" name="lookback_days" value={form.lookback_days} onChange={change}/><Field label="MA 周期" name="ma_window" value={form.ma_window} onChange={change}/></div>
            <div className="grid grid-cols-2 gap-3"><PercentField label="最高收盘回撤" name="entry_drawdown_pct" value={form.entry_drawdown_pct} setForm={setForm} form={form}/><PercentField label="低于 MA 幅度" name="ma_discount_pct" value={form.ma_discount_pct} setForm={setForm} form={form}/></div>
            <button type="button" onClick={fetchTargetEntry} className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-semibold text-blue-700 hover:bg-blue-100 disabled:text-slate-400" disabled={targetLoading}>{targetLoading ? '正在测算目标买点…' : '测算最新目标买点'}</button>
            {targetEntry && <div className="target-card"><p className="m-0 text-xs font-semibold text-blue-700">最新目标买点（{targetEntry.as_of_date}）</p><p className="my-1 text-2xl font-bold text-blue-900">{fmt(targetEntry.target_buy_price)}</p><p className="m-0 text-xs text-slate-600">最高收盘回撤价 {fmt(targetEntry.drawdown_buy_price)} · MA 下方价 {fmt(targetEntry.ma_buy_price)}</p><p className={`mb-0 mt-2 text-xs font-semibold ${targetEntry.conditions_met ? 'text-green-700' : 'text-amber-700'}`}>{targetEntry.conditions_met ? '当前收盘价已同时满足两个入场条件。' : `当前收盘价距目标买点高 ${fmt(targetEntry.distance_to_target_pct, true)}。`}</p></div>}
          </> : <>
            <div><label>策略</label><select name="strategy" value={form.strategy} onChange={change}>
              <option value="quality_grid">质量过滤逐笔网格</option><option value="dca">普通定投</option><option value="ma_band">MA 趋势策略</option><option value="dynamic">动态仓位策略</option>
            </select></div>
            {quality ? <>
              <div className="notice-blue"><strong>成交模式：下一交易日开盘价</strong><br/>信号仅使用当日收盘数据；最后一个交易日产生的信号不会成交。</div>
              <Toggle label="我已确认该标的通过质量筛选" name="quality_confirmed" checked={form.quality_confirmed} onChange={change} hint="首期不根据价格数据判断优绩股。个股财务质量需按公告日对齐，避免前视；ETF 可直接确认。"/>
              {!form.quality_confirmed && <div className="notice-amber">未确认时策略不会建立首仓。宽基、红利、低波、价值 ETF 更适合作为首期测试标的。</div>}
              <div className="section-title">资金与入场设置</div>
              <Field label="策略资金池上限（元）" name="max_strategy_cash" value={form.max_strategy_cash} onChange={change}/>
              <Field label="首仓金额（元）" name="base_cash" value={form.base_cash} onChange={change}/>
              <div><label>入场条件</label><select name="entry_condition_mode" value={form.entry_condition_mode} onChange={change}><option value="all">同时满足</option><option value="any">满足任一</option></select></div>

              <div className="section-title">四层补仓（锚定本轮首仓实际成交价）</div>
              {form.grid_drop_pcts.map((drop: number, i: number) => <div key={i} className="grid grid-cols-[1fr_1fr] gap-3 rounded-lg bg-slate-50 p-3">
                <div><label>第 {i + 1} 层跌幅</label><div className="relative"><input type="number" step="0.01" value={drop * 100} onChange={e => setGrid('grid_drop_pcts', i, Number(e.target.value) / 100)}/><span className="suffix">%</span></div></div>
                <div><label>金额倍数</label><div className="relative"><input type="number" step="0.1" value={form.grid_cash_multipliers[i]} onChange={e => setGrid('grid_cash_multipliers', i, Number(e.target.value))}/><span className="suffix">x</span></div></div>
              </div>)}
              <p className="hint -mt-2">每个交易日最多触发一层；不使用平均成本作为补仓锚点。</p>

              <div className="section-title">逐笔止盈、组合清仓与再入场</div>
              <PercentField label="每个 lot 独立全量止盈" name="lot_take_profit_pct" value={form.lot_take_profit_pct} setForm={setForm} form={form} hint="达到阈值后卖出该 lot 全部数量，不拆成两次卖。"/>
              <Toggle label="启用组合盈利清仓" name="basket_take_profit_enabled" checked={form.basket_take_profit_enabled} onChange={change}/>
              {form.basket_take_profit_enabled && <PercentField label="组合清仓阈值" name="basket_take_profit_pct" value={form.basket_take_profit_pct} setForm={setForm} form={form}/>} 
              <PercentField label="完全清仓后再入场跌幅" name="reentry_drop_pct" value={form.reentry_drop_pct} setForm={setForm} form={form} hint="设为 0 即取消相对上一轮最终清仓价的跌幅限制；仍需满足低位入场条件。"/>

              <div className="section-title">费用、滑点与最小交易单位</div>
              <PercentField label="佣金率" name="commission_rate" value={form.commission_rate} setForm={setForm} form={form}/>
              <Field label="最低佣金（元/笔）" name="min_commission" value={form.min_commission} onChange={change}/>
              <PercentField label="卖出税费率" name="sell_tax_rate" value={form.sell_tax_rate} setForm={setForm} form={form} hint="ETF 通常可按研究口径手动设为 0。"/>
              <PercentField label="单边滑点" name="slippage_pct" value={form.slippage_pct} setForm={setForm} form={form}/>
              <Toggle label="A 股执行 100 股整手限制" name="enforce_a_share_board_lot" checked={form.enforce_a_share_board_lot} onChange={change}/>
              <Toggle label="ETF / 基金允许碎股" name="allow_fractional_etf" checked={form.allow_fractional_etf} onChange={change} hint="默认关闭；关闭时 ETF 也按 100 份整数单位模拟。"/>
            </> : <>
              <Field label="初始资金" name="initial_cash" value={form.initial_cash} onChange={change}/><Field label="每月投入金额" name="monthly_contribution" value={form.monthly_contribution} onChange={change}/>
              {form.strategy !== 'dca' && <Field label="MA 周期" name="ma_window" value={form.ma_window} onChange={change}/>} 
            </>}
          </>}
        </div>
      </form>

      <section className="min-w-0">
        {error && <div className="mb-4 whitespace-pre-wrap break-all rounded-xl bg-red-50 p-4 text-red-700">{error}</div>}
        {!result ? <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-16 text-center text-slate-500">确认质量筛选、修改参数，然后运行一次可保存、可追溯的本地回测。</div> : <>
          {(result.warnings || []).map((warning, i) => <div key={i} className={`mb-3 rounded-xl p-4 ${warning.includes('新浪') ? 'bg-red-100 font-semibold text-red-800' : 'bg-amber-50 text-amber-800'}`}>{warning}</div>)}
          <div className="mb-4 rounded-2xl bg-white p-4 shadow-sm">
            <div className="grid gap-3 text-sm md:grid-cols-3 xl:grid-cols-6">
              <div><span className="meta-label">数据源</span>{result.data_info.source || '—'}</div><div><span className="meta-label">价格类型</span>{result.data_info.price_type || '—'}</div>
              <div><span className="meta-label">可用起止</span>{result.data_info.available_start} 至 {result.data_info.available_end}</div><div><span className="meta-label">数据条数</span>{result.data_info.bars || '—'}</div>
              <div><span className="meta-label">最后更新</span>{result.data_info.last_updated || '旧缓存未记录'}</div><div><span className="meta-label">成交模式</span>{result.execution_mode}</div>
            </div>
          </div>
          <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">{cards.map(card => <div key={card.key} className="rounded-xl bg-white p-4 shadow-sm"><p className="m-0 text-xs text-slate-500">{card.title}</p><p className="mb-0 mt-2 text-xl font-bold">{fmt(result.metrics[card.key], card.pct)}</p>{card.key === 'max_drawdown' && <p className="hint">{result.metrics.max_drawdown_start} → {result.metrics.max_drawdown_end}</p>}</div>)}</div>
          <div className="notice-blue mb-5">总账户收益会受到未投入现金影响。请同时查看最大资金占用和已投入资金收益率。</div>
          <div className="rounded-2xl bg-white p-5 shadow-sm">
            <div className="mb-3 flex gap-2 overflow-auto border-b">{[['equity','权益/现金/持仓'],['price','价格/MA/逐层'],['drawdown','回撤曲线']].map(([key,label]) => <button key={key} type="button" onClick={() => setTab(key)} className={`whitespace-nowrap border-b-2 px-3 py-2 text-sm ${tab === key ? 'border-blue-600 text-blue-600' : 'border-transparent text-slate-500'}`}>{label}</button>)}</div>
            <Plot data={result.charts[tab].data} layout={{ ...result.charts[tab].layout, autosize: true, margin: { l: 55, r: 15, t: 50, b: 40 } }} config={{ responsive: true, displaylogo: false }} style={{ width: '100%', height: '500px' }}/>
          </div>
          <div className="mt-5 rounded-2xl bg-white p-5 shadow-sm">
            <div className="mb-4 flex gap-2 overflow-auto border-b">{[['trades',`完整交易流水（${result.trades.length}）`],['lots',`Lot 明细（${result.lots?.length || 0}）`],['daily',`每日权益（${result.daily_equity?.length || 0}）`]].map(([key,label]) => <button key={key} type="button" onClick={() => setTableTab(key)} className={`whitespace-nowrap border-b-2 px-3 py-2 text-sm ${tableTab === key ? 'border-blue-600 text-blue-600' : 'border-transparent text-slate-500'}`}>{label}</button>)}</div>
            <div className="max-h-[520px] overflow-auto">
              {tableTab === 'trades' && <table><thead><tr><th>信号日</th><th>成交日</th><th>状态</th><th>方向</th><th>Lot</th><th>价格</th><th>数量</th><th>金额</th><th>佣金</th><th>税费</th><th>已实现盈亏</th><th>原因</th></tr></thead><tbody>{result.trades.map((t, i) => <tr key={i}><td>{t.signal_date || '—'}</td><td>{t.date}</td><td>{t.status === 'FILLED' ? '已成交' : '未成交'}</td><td className={t.side === 'BUY' ? 'text-green-600' : 'text-red-600'}>{t.side === 'BUY' ? '买入' : '卖出'}</td><td>{t.lot_id || '—'}</td><td>{fmt(t.price)}</td><td>{fmt(t.quantity)}</td><td>{fmt(t.notional)}</td><td>{fmt(t.commission)}</td><td>{fmt(t.tax)}</td><td>{fmt(t.realized_pnl)}</td><td className="min-w-52">{t.reason}</td></tr>)}</tbody></table>}
              {tableTab === 'lots' && <table><thead><tr><th>Lot</th><th>轮次/层</th><th>买入日</th><th>买入价</th><th>数量</th><th>成本</th><th>卖出日</th><th>卖出价</th><th>收益率</th><th>状态</th><th>退出原因</th></tr></thead><tbody>{(result.lots || []).map(l => <tr key={l.lot_id}><td>{l.lot_id}</td><td>R{l.round_no} / L{l.layer_no}</td><td>{l.buy_date}</td><td>{fmt(l.buy_price)}</td><td>{fmt(l.quantity)}</td><td>{fmt(l.cost)}</td><td>{l.sell_date || '—'}</td><td>{fmt(l.sell_price)}</td><td>{fmt(l.return_pct, true)}</td><td>{l.status === 'OPEN' ? '未平仓' : '已平仓'}</td><td>{l.exit_reason || '期末保留'}</td></tr>)}</tbody></table>}
              {tableTab === 'daily' && <table><thead><tr><th>日期</th><th>收盘价</th><th>MA</th><th>现金</th><th>数量</th><th>持仓市值</th><th>账户权益</th><th>已实现</th><th>未实现</th><th>资金占用</th><th>层数</th><th>回撤</th></tr></thead><tbody>{(result.daily_equity || []).map(d => <tr key={d.date}><td>{d.date}</td><td>{fmt(d.price)}</td><td>{fmt(d.ma)}</td><td>{fmt(d.cash)}</td><td>{fmt(d.shares)}</td><td>{fmt(d.market_value)}</td><td>{fmt(d.equity)}</td><td>{fmt(d.realized_profit)}</td><td>{fmt(d.unrealized_profit)}</td><td>{fmt(d.invested_cost)}</td><td>{d.active_layers}</td><td>{fmt(d.drawdown, true)}</td></tr>)}</tbody></table>}
            </div>
          </div>
          <div className="mt-5 grid gap-3 text-sm text-slate-600 md:grid-cols-3"><div className="disclaimer">回测不构成投资建议。</div><div className="disclaimer">个股基本面质量筛选尚需按公告日数据进一步实现。</div><div className="disclaimer">期末未平仓 lot 仅按最后收盘价计算浮动盈亏，不强制卖出。</div></div>
        </>}
      </section>
    </div>
  </main>;
}

createRoot(document.getElementById('root')!).render(<App/>);
