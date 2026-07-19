import { FormEvent, useState } from 'react';
import { postJson } from '../api';
import { PercentInput } from './PercentInput';

type ScreenerRow = {
  symbol: string; name?: string; industry?: string; report_period: string; announcement_date: string;
  market_cap_usd: number; pe_ttm: number; net_margin_pct: number; roe_pct: number;
  revenue_growth_pct: number; eps_growth_pct: number; close: number;
  high_window_days: number; period_high: number; drawdown_from_high_pct: number; sma: number; below_sma_pct: number;
};
type ScreenerResult = {
  as_of_date: string; universe_count: number; fundamental_candidate_count: number; matched_count: number;
  results: ScreenerRow[]; warnings: string[]; methodology: string;
};
type StockScreenerPanelProps = { onUseSymbols: (symbols: string[]) => void };

const today = new Date().toISOString().slice(0, 10);
const initial = {
  as_of_date: today, market_cap_min_usd: 2_000_000_000, usd_cny_rate: 7,
  pe_min: 0, pe_max: 30, net_margin_min_pct: 5, roe_min_pct: 5,
  revenue_growth_min_pct: 5, eps_growth_min_pct: 5, high_window_days: 252, high_drawdown_min_pct: 30,
  sma_window: 120, below_sma_min_pct: 15,
};
const number = (value: number, digits = 2) => Number(value).toLocaleString('zh-CN', { maximumFractionDigits: digits });

export function StockScreenerPanel({ onUseSymbols }: StockScreenerPanelProps) {
  const [form, setForm] = useState(initial);
  const [result, setResult] = useState<ScreenerResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function submit(event: FormEvent) {
    event.preventDefault(); setLoading(true); setError(''); setResult(null);
    try { setResult(await postJson<ScreenerResult>('/stock-screener', form)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '选股失败'); }
    finally { setLoading(false); }
  }
  const set = (key: keyof typeof initial, value: string) => setForm(current => ({
    ...current, [key]: key === 'as_of_date' ? value : Number(value),
  }));

  return <div className="mx-auto max-w-[1500px]">
    <header className="mb-7"><p className="mb-1 text-sm font-semibold text-blue-600">POINT-IN-TIME A-SHARE SCREENER</p><h1 className="m-0 text-3xl font-bold">历史基本面选股器</h1><p className="text-slate-500">按所选日期已公告财务数据与当时估值筛选 · 明确排除 ETF</p></header>
    <div className="grid gap-6 xl:grid-cols-[390px_1fr]">
      <form onSubmit={submit} className="h-fit rounded-2xl bg-white p-5 shadow-sm">
        <div className="notice-blue mb-4">历史财务按公告日截断；价格、PE、市值、可选交易日区间高点与 SMA 均不使用所选日期之后的数据。</div>
        <div className="grid gap-4">
          <div><label>选股日期</label><input type="date" value={form.as_of_date} max={today} onChange={event => set('as_of_date', event.target.value)}/></div>
          <div className="grid grid-cols-2 gap-3"><div><label>总市值下限（USD）</label><input type="number" value={form.market_cap_min_usd} onChange={event => set('market_cap_min_usd', event.target.value)}/></div><div><label>USD/CNY 换算</label><input type="number" step="0.01" value={form.usd_cny_rate} onChange={event => set('usd_cny_rate', event.target.value)}/></div></div>
          <div className="grid grid-cols-2 gap-3"><div><label>PE(TTM) 下限</label><input type="number" value={form.pe_min} onChange={event => set('pe_min', event.target.value)}/></div><div><label>PE(TTM) 上限</label><input type="number" value={form.pe_max} onChange={event => set('pe_max', event.target.value)}/></div></div>
          <div className="grid grid-cols-2 gap-3"><PercentInput label="净利率 ≥" value={form.net_margin_min_pct} step={0.1} onChange={value => set('net_margin_min_pct', String(value))}/><PercentInput label="ROE ≥" value={form.roe_min_pct} step={0.1} onChange={value => set('roe_min_pct', String(value))}/></div>
          <div className="grid grid-cols-2 gap-3"><PercentInput label="营收同比 ≥" value={form.revenue_growth_min_pct} step={0.1} onChange={value => set('revenue_growth_min_pct', String(value))}/><PercentInput label="每股收益同比 ≥" value={form.eps_growth_min_pct} step={0.1} onChange={value => set('eps_growth_min_pct', String(value))}/></div>
          <div className="grid grid-cols-2 gap-3"><div><label>高点回看（交易日）</label><input type="number" min="2" value={form.high_window_days} onChange={event => set('high_window_days', event.target.value)}/></div><PercentInput label="距区间高点下跌 ≥" value={form.high_drawdown_min_pct} step={0.1} onChange={value => set('high_drawdown_min_pct', String(value))}/></div>
          <div className="grid grid-cols-2 gap-3"><div><label>SMA 周期（交易日）</label><input type="number" min="2" value={form.sma_window} onChange={event => set('sma_window', event.target.value)}/></div><PercentInput label="低于 SMA ≥" value={form.below_sma_min_pct} step={0.1} onChange={value => set('below_sma_min_pct', String(value))}/></div>
          <button className="rounded-lg bg-blue-600 px-4 py-3 font-semibold text-white disabled:bg-slate-400" disabled={loading}>{loading ? '正在读取历史报表与估值（首次较慢）…' : '按选定日期开始筛选'}</button>
        </div>
      </form>
      <section className="min-w-0">
        {error && <div className="mb-4 rounded-xl bg-red-50 p-4 text-red-700">{error}</div>}
        {!result ? <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-16 text-center text-slate-500">设置条件后执行。首次运行会缓存历史报表与逐股估值，后续相同日期明显更快。</div> : <>
          {result.warnings.map(warning => <div key={warning} className="mb-3 rounded-xl bg-amber-50 p-4 text-sm text-amber-800">{warning}</div>)}
          <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">{[
            ['历史股票池', result.universe_count], ['基本面初筛', result.fundamental_candidate_count], ['最终符合', result.matched_count], ['选股日期', result.as_of_date],
          ].map(([label, value]) => <div key={label} className="rounded-xl bg-white p-4 shadow-sm"><p className="m-0 text-xs text-slate-500">{label}</p><p className="mb-0 mt-2 text-xl font-bold">{value}</p></div>)}</div>
          <div className="mb-4 flex items-center justify-between rounded-2xl bg-white p-4 shadow-sm"><p className="m-0 text-sm text-slate-600">{result.methodology}</p><button type="button" disabled={!result.results.length} onClick={() => onUseSymbols(result.results.map(row => row.symbol))} className="ml-4 whitespace-nowrap rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:bg-slate-300">送入组合回测</button></div>
          {!result.results.length && <div className="mb-4 rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-600">本次运行已完成，但没有股票同时符合全部筛选条件。可适当降低市值、基本面或价格偏离门槛后重试。</div>}
          <div className="max-h-[680px] overflow-auto rounded-2xl bg-white p-5 shadow-sm"><table><thead><tr><th>代码</th><th>名称</th><th>报告期 / 公告日</th><th>市值(USD)</th><th>PE</th><th>净利率</th><th>ROE</th><th>营收同比</th><th>EPS同比</th><th>现价</th><th>区间高点回撤</th><th>低于SMA</th></tr></thead><tbody>{result.results.map(row => <tr key={row.symbol}><td className="font-semibold">{row.symbol}</td><td>{row.name || '—'}</td><td>{row.report_period}<br/><span className="text-slate-400">{row.announcement_date}</span></td><td>${number(row.market_cap_usd / 1e9)}B</td><td>{number(row.pe_ttm)}</td><td>{number(row.net_margin_pct)}%</td><td>{number(row.roe_pct)}%</td><td>{number(row.revenue_growth_pct)}%</td><td>{number(row.eps_growth_pct)}%</td><td>{number(row.close)}</td><td>{number(row.drawdown_from_high_pct)}%</td><td>{number(row.below_sma_pct)}%</td></tr>)}</tbody></table></div>
        </>}
      </section>
    </div>
  </div>;
}