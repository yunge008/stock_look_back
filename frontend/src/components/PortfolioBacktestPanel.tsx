import { FormEvent, useState } from 'react';
import Plot from 'react-plotly.js';
import { postJson } from '../api';
import { PercentInput } from './PercentInput';

type PortfolioLot = {
  symbol: string; lot_id: string; round_no: number; layer_no: number; buy_date: string;
  buy_price: number; quantity: number; cost: number; status: string; sell_date?: string;
  sell_price?: number; realized_pnl?: number; return_pct?: number; exit_reason?: string; holding_days: number;
};
type SymbolResult = {
  symbol: string; name?: string; allocation: number; ending_equity: number; total_return: number;
  annualized_return: number; win_rate?: number; max_drawdown: number; max_capital_used: number;
  lot_count: number; trade_count: number;
};
type EquityRow = {
  date: string; equity: number; cash: number; market_value: number; invested_cost: number;
  drawdown: number; holding_ratio: number; holding_drawdown: number | null;
};
type BenchmarkDaily = { date: string; close: number; normalized_equity: number; drawdown: number };
type BenchmarkResult = {
  key: string; name: string; symbol: string; source?: string; start_date: string; end_date: string;
  starting_close: number; ending_close: number; ending_equity: number; total_return: number;
  annualized_return: number; max_drawdown: number; max_drawdown_start: string; max_drawdown_end: string;
  daily: BenchmarkDaily[];
};
type PortfolioResult = {
  metrics: Record<string, number | string | null>; symbol_results: SymbolResult[]; lots: PortfolioLot[];
  trades: Array<Record<string, unknown>>; daily_equity: EquityRow[]; benchmark: BenchmarkResult | null;
  warnings: string[]; execution: string;
};
type PortfolioBacktestPanelProps = { initialSymbols: string[] };
const today = new Date().toISOString().slice(0, 10);
const money = (value: unknown) => value == null ? '—' : Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 });
const pct = (value: unknown) => value == null ? '—' : `${(Number(value) * 100).toFixed(2)}%`;
const BENCHMARK_OPTIONS = [
  { value: "none", label: "不显示参考基准" },
  { value: "csi300", label: "沪深300指数" },
  { value: "nasdaq100", label: "纳斯达克100" },
  { value: "sp500", label: "标普500" },
  { value: "csi1000", label: "中证1000" },
  { value: "sse50", label: "上证50" },
  { value: "star50", label: "科创50" },
  { value: "chinext", label: "创业板指" },
] as const;

const parseList = (value: string, divideBy100 = false) => value.split(/[\s,，;；]+/).map(Number).filter(Number.isFinite).map(item => divideBy100 ? item / 100 : item);

function lotAnnualizedReturn(lot: PortfolioLot, rows: EquityRow[]) {
  if (lot.return_pct == null) return null;
  const endDate = lot.sell_date || rows[rows.length - 1]?.date || lot.buy_date;
  const tradingDays = rows.filter(row => row.date >= lot.buy_date && row.date <= endDate).length;
  return tradingDays > 0 && 1 + lot.return_pct > 0 ? (1 + lot.return_pct) ** (245 / tradingDays) - 1 : null;
}

export function PortfolioBacktestPanel({ initialSymbols }: PortfolioBacktestPanelProps) {
  const [symbolsText, setSymbolsText] = useState(initialSymbols.join('\n') || '600519\n513500');
  const [startDate, setStartDate] = useState('2018-01-01');
  const [endDate, setEndDate] = useState(today);
  const [totalCash, setTotalCash] = useState(200000);
  const [benchmark, setBenchmark] = useState('none');
  const [lookbackDays, setLookbackDays] = useState(360);
  const [maWindow, setMaWindow] = useState(120);
  const [entryDrawdownPct, setEntryDrawdownPct] = useState(30);
  const [maDiscountPct, setMaDiscountPct] = useState(15);
  const [gridDrops, setGridDrops] = useState('10, 20, 30, 40, 50');
  const [gridMultipliers, setGridMultipliers] = useState('1, 2, 2, 3, 3');
  const [lotTakeProfitPct, setLotTakeProfitPct] = useState(10);
  const [holdingDecayDays, setHoldingDecayDays] = useState(365);
  const [holdingDecayPct, setHoldingDecayPct] = useState(1);
  const [commissionRatePct, setCommissionRatePct] = useState(5);
  const [minCommission, setMinCommission] = useState(5);
  const [sellTaxRatePct, setSellTaxRatePct] = useState(0.1);
  const [slippagePctValue, setSlippagePctValue] = useState(5);
  const [result, setResult] = useState<PortfolioResult | null>(null);
  const [selectedSymbol, setSelectedSymbol] = useState('');
  const [chartTab, setChartTab] = useState<'equity' | 'holding_drawdown'>('equity');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function submit(event: FormEvent) {
    event.preventDefault(); setLoading(true); setError('');
    const symbols = symbolsText.split(/[\s,，;；]+/).map(value => value.trim()).filter(Boolean);
    try {
      const body = await postJson<PortfolioResult>('/portfolio-backtests', {
        symbols, start_date: startDate, end_date: endDate, total_cash: totalCash, benchmark,
        quality_confirmed: true, lookback_days: lookbackDays, ma_window: maWindow,
        entry_drawdown_pct: entryDrawdownPct / 100, ma_discount_pct: maDiscountPct / 100,
        entry_condition_mode: 'all', grid_drop_pcts: parseList(gridDrops, true),
        grid_cash_multipliers: parseList(gridMultipliers), lot_take_profit_pct: lotTakeProfitPct / 100,
        holding_profit_decay_days: holdingDecayDays, holding_profit_decay_pct: holdingDecayPct / 100,
        basket_take_profit_enabled: false, basket_take_profit_pct: 0.10, reentry_drop_pct: 0,
        commission_rate: commissionRatePct / 100, min_commission: minCommission,
        sell_tax_rate: sellTaxRatePct / 100, slippage_pct: slippagePctValue / 100,
        force_close_at_end: true, enforce_board_lot: true, allow_fractional_etf: false,
      });
      setResult(body);
      setSelectedSymbol(body.symbol_results.find(item => item.lot_count > 0)?.symbol || body.symbol_results[0]?.symbol || '');
      setChartTab('equity');
    } catch (reason) { setError(reason instanceof Error ? reason.message : '组合回测失败'); }
    finally { setLoading(false); }
  }

  const metricCards = result ? [
    ['期末权益', money(result.metrics.ending_equity)], ['总收益率', pct(result.metrics.total_return)],
    ['年化收益率', pct(result.metrics.annualized_return)], ['Lot 胜率', pct(result.metrics.win_rate)],
    ['最大资金使用', money(result.metrics.max_capital_used)], ['总权益最大回撤', pct(result.metrics.max_drawdown)],
    ['持仓金额最大回撤', pct(result.metrics.max_holding_drawdown)], ['平均持仓比例', pct(result.metrics.average_holding_ratio)],
    ['最大持仓比例', pct(result.metrics.max_holding_ratio)], ['Lot 总数', money(result.metrics.lot_count)],
    ...(result.benchmark ? [
      [`${result.benchmark.name}总收益`, pct(result.benchmark.total_return)],
      [`${result.benchmark.name}年化`, pct(result.benchmark.annualized_return)],
      ['相对基准年化超额', pct(result.metrics.benchmark_annualized_excess)],
      [`${result.benchmark.name}最大回撤`, pct(result.benchmark.max_drawdown)],
    ] : []),
  ] : [];
  const selectedLots = result?.lots.filter(lot => lot.symbol === selectedSymbol) || [];
  const equityChartData: any[] = result ? [
    { x: result.daily_equity.map(row => row.date), y: result.daily_equity.map(row => row.equity), type: 'scatter', mode: 'lines', name: '组合权益', line: { color: '#2563eb', width: 2 } },
    { x: result.daily_equity.map(row => row.date), y: result.daily_equity.map(row => row.market_value), type: 'scatter', mode: 'lines', name: '股票持仓金额', visible: 'legendonly', line: { color: '#16a34a' } },
    { x: result.daily_equity.map(row => row.date), y: result.daily_equity.map(row => row.cash), type: 'scatter', mode: 'lines', name: '现金金额', visible: 'legendonly', line: { color: '#f59e0b' } },
    { x: result.daily_equity.map(row => row.date), y: result.daily_equity.map(row => row.holding_ratio), type: 'scatter', mode: 'lines', name: '持仓比例', yaxis: 'y2', line: { color: '#7c3aed', dash: 'dot' } },
    ...(result.benchmark ? [{
      x: result.benchmark.daily.map(row => row.date), y: result.benchmark.daily.map(row => row.normalized_equity),
      type: 'scatter', mode: 'lines', name: `${result.benchmark.name}（同本金）`,
      line: { color: '#475569', width: 2, dash: 'dash' },
    }] : []),
  ] : [];
  const drawdownChartData: any[] = result ? [{
    x: result.daily_equity.map(row => row.date), y: result.daily_equity.map(row => row.holding_drawdown),
    type: 'scatter', mode: 'lines', name: '持仓金额回撤', fill: 'tozeroy', line: { color: '#dc2626' },
  }] : [];

  return <div className="mx-auto max-w-[1500px]">
    <header className="mb-7"><p className="mb-1 text-sm font-semibold text-blue-600">MULTI-SYMBOL QUALITY GRID</p><h1 className="m-0 text-3xl font-bold">一揽子标的网格组合回测</h1><p className="text-slate-500">每个标的独立运行同一套本地质量网格参数 · 组合层汇总实际现金和持仓</p></header>
    <div className="grid gap-6 xl:grid-cols-[430px_1fr]">
      <form onSubmit={submit} className="h-fit rounded-2xl bg-white p-5 shadow-sm xl:max-h-[calc(100vh-4rem)] xl:overflow-y-auto">
        <div className="grid gap-4">
          <div><label>证券代码（换行、逗号或空格分隔）</label><textarea rows={7} value={symbolsText} onChange={event => setSymbolsText(event.target.value)} placeholder="600519&#10;513500&#10;AAPL"/><p className="hint">每个代码分配总资金 ÷ N，并分别执行网格，不是买入持有。</p></div>
          <div className="grid grid-cols-2 gap-3"><div><label>开始日期</label><input type="date" value={startDate} onChange={event => setStartDate(event.target.value)}/></div><div><label>结束日期</label><input type="date" max={today} value={endDate} onChange={event => setEndDate(event.target.value)}/></div></div>
          <div><label>组合总金额</label><input type="number" min="1" value={totalCash} onChange={event => setTotalCash(Number(event.target.value))}/></div>
          <div><label>参考基准</label><select value={benchmark} onChange={event => setBenchmark(event.target.value)}>{BENCHMARK_OPTIONS.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select><p className="hint">基准按同一回测区间归一到组合初始金额，不计交易费用。</p></div>

          <div className="section-title">与本地回测一致的入场和网格参数</div>
          <div className="grid grid-cols-2 gap-3"><div><label>高点回看交易日</label><input type="number" min="1" value={lookbackDays} onChange={event => setLookbackDays(Number(event.target.value))}/></div><div><label>MA 周期</label><input type="number" min="1" value={maWindow} onChange={event => setMaWindow(Number(event.target.value))}/></div></div>
          <div className="grid grid-cols-2 gap-3"><PercentInput label="最高收盘回撤" value={entryDrawdownPct} onChange={setEntryDrawdownPct}/><PercentInput label="低于 MA 幅度" value={maDiscountPct} onChange={setMaDiscountPct}/></div>
          <div><label>补仓跌幅（输入百分数，逗号分隔）</label><div className="relative"><input className="pr-9" value={gridDrops} onChange={event => setGridDrops(event.target.value)}/><span className="suffix">%</span></div></div>
          <div><label>各层补仓倍数（逗号分隔）</label><input value={gridMultipliers} onChange={event => setGridMultipliers(event.target.value)}/></div>
          <div className="grid grid-cols-2 gap-3"><PercentInput label="每个 lot 独立止盈" value={lotTakeProfitPct} onChange={setLotTakeProfitPct}/><PercentInput label="每周期止盈减少" value={holdingDecayPct} onChange={setHoldingDecayPct}/></div>
          <div><label>止盈递减周期（自然日）</label><input type="number" min="1" value={holdingDecayDays} onChange={event => setHoldingDecayDays(Number(event.target.value))}/></div>

          <div className="section-title">费用与成交</div>
          <div className="grid grid-cols-2 gap-3"><PercentInput label="佣金率" value={commissionRatePct} onChange={setCommissionRatePct}/><div><label>最低佣金</label><input type="number" value={minCommission} onChange={event => setMinCommission(Number(event.target.value))}/></div></div>
          <div className="grid grid-cols-2 gap-3"><PercentInput label="A股卖出税费" value={sellTaxRatePct} onChange={setSellTaxRatePct}/><PercentInput label="单边滑点" value={slippagePctValue} onChange={setSlippagePctValue}/></div>
          <div className="notice-blue">组合内每个标的独立产生首仓、补仓和止盈 lot；组合最大资金使用按所有标的的实际并发占用计算。</div>
          <div className="notice-amber"><strong>固定口径：</strong>期末全部强制平仓；年化按每年 245 个交易日；佣金和滑点框输入 5 即表示 5%。</div>
          <button className="rounded-lg bg-blue-600 px-4 py-3 font-semibold text-white disabled:bg-slate-400" disabled={loading}>{loading ? '正在逐标的执行网格并汇总…' : '开始组合网格回测'}</button>
        </div>
      </form>
      <section className="min-w-0">
        {error && <div className="mb-4 rounded-xl bg-red-50 p-4 text-red-700">{error}</div>}
        {!result ? <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-16 text-center text-slate-500">输入标的和统一网格参数，查看组合权益、持仓金额回撤、持仓比例及逐标的 lot。</div> : <>
          {result.warnings.map(warning => <div key={warning} className="mb-3 rounded-xl bg-amber-50 p-4 text-sm text-amber-800">{warning}</div>)}
          <div className="notice-blue mb-4">{result.execution}</div>
          {result.benchmark && <div className="mb-4 rounded-xl bg-slate-100 p-4 text-sm text-slate-700"><strong>{result.benchmark.name}</strong>（{result.benchmark.symbol}）按首个可交易日归一到组合初始金额；数据源：{result.benchmark.source || '—'}。</div>}
          <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-5">{metricCards.map(([label, value]) => <div key={label} className="rounded-xl bg-white p-4 shadow-sm"><p className="m-0 text-xs text-slate-500">{label}</p><p className="mb-0 mt-2 text-xl font-bold">{value}</p>{label === '总权益最大回撤' && <p className="hint">{result.metrics.max_drawdown_start} → {result.metrics.max_drawdown_end}</p>}{label === '持仓金额最大回撤' && <p className="hint">{result.metrics.max_holding_drawdown_start} → {result.metrics.max_holding_drawdown_end}</p>}</div>)}</div>
          <div className="mb-5 rounded-2xl bg-white p-5 shadow-sm">
            <div className="mb-3 flex gap-2 border-b"><button type="button" onClick={() => setChartTab('equity')} className={`border-b-2 px-3 py-2 text-sm ${chartTab === 'equity' ? 'border-blue-600 text-blue-600' : 'border-transparent text-slate-500'}`}>组合收益与持仓比例</button><button type="button" onClick={() => setChartTab('holding_drawdown')} className={`border-b-2 px-3 py-2 text-sm ${chartTab === 'holding_drawdown' ? 'border-blue-600 text-blue-600' : 'border-transparent text-slate-500'}`}>持仓金额回撤</button></div>
            <Plot data={chartTab === 'equity' ? equityChartData : drawdownChartData} layout={chartTab === 'equity' ? { autosize: true, title: '组合权益与参考基准（持仓金额和现金默认隐藏）', margin: { l: 65, r: 65, t: 55, b: 40 }, yaxis: { title: '金额' }, yaxis2: { title: '持仓比例', tickformat: '.0%', overlaying: 'y', side: 'right', range: [0, 1] } } : { autosize: true, title: '按股票持仓金额计算的回撤', margin: { l: 65, r: 20, t: 55, b: 40 }, yaxis: { tickformat: '.1%', title: '回撤比例' } }} config={{ responsive: true, displaylogo: false }} style={{ width: '100%', height: '450px' }}/>
          </div>
          <div className="mb-5 max-h-[420px] overflow-auto rounded-2xl bg-white p-5 shadow-sm"><h2 className="mt-0 text-lg">逐标的网格结果</h2><table><thead><tr><th>代码 / 名称</th><th>分配资金</th><th>期末权益</th><th>收益率</th><th>年化</th><th>Lot 胜率</th><th>最大资金占用</th><th>Lot 数</th></tr></thead><tbody>{result.symbol_results.map(item => <tr key={item.symbol}><td className="font-semibold">{item.symbol}<br/><span className="font-normal text-slate-400">{item.name || '—'}</span></td><td>{money(item.allocation)}</td><td>{money(item.ending_equity)}</td><td>{pct(item.total_return)}</td><td>{pct(item.annualized_return)}</td><td>{pct(item.win_rate)}</td><td>{money(item.max_capital_used)}</td><td>{item.lot_count}</td></tr>)}</tbody></table></div>
          <div className="rounded-2xl bg-white p-5 shadow-sm">
            <div className="mb-4 flex flex-wrap items-end justify-between gap-3"><div><label>筛选标的 Lot 明细</label><select value={selectedSymbol} onChange={event => setSelectedSymbol(event.target.value)}>{result.symbol_results.map(item => <option key={item.symbol} value={item.symbol}>{item.symbol} {item.name || ''}（{item.lot_count}）</option>)}</select></div><p className="m-0 text-sm text-slate-500">当前 {selectedLots.length} 个 Lot</p></div>
            <div className="max-h-[520px] overflow-auto"><table><thead><tr><th>Lot</th><th>轮次 / 层</th><th>买入日</th><th>持有自然日</th><th>买入价</th><th>数量</th><th>成本</th><th>卖出日</th><th>卖出价</th><th>收益率</th><th>245日年化</th><th>状态</th><th>退出原因</th></tr></thead><tbody>{selectedLots.map(lot => <tr key={`${lot.symbol}-${lot.lot_id}`}><td>{lot.lot_id}</td><td>R{lot.round_no} / L{lot.layer_no}</td><td>{lot.buy_date}</td><td>{lot.holding_days}</td><td>{money(lot.buy_price)}</td><td>{money(lot.quantity)}</td><td>{money(lot.cost)}</td><td>{lot.sell_date || '—'}</td><td>{money(lot.sell_price)}</td><td>{pct(lot.return_pct)}</td><td>{pct(lotAnnualizedReturn(lot, result.daily_equity))}</td><td>{lot.status === 'OPEN' ? '未平仓' : '已平仓'}</td><td>{lot.exit_reason || '—'}</td></tr>)}</tbody></table></div>
          </div>
        </>}
      </section>
    </div>
  </div>;
}