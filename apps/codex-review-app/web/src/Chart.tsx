import { useEffect, useRef, useState } from 'react';
import {
  CandlestickSeries, LineSeries, HistogramSeries, createChart, createSeriesMarkers, ColorType,
  CrosshairMode, LineStyle, type IChartApi, type ISeriesApi, type Time, type UTCTimestamp,
  type SeriesMarker, type MouseEventParams,
} from 'lightweight-charts';
import { ScenarioOverlay } from './ScenarioOverlay';
import type { Fill, Indicator, Scenario, Session } from './types';
import { indicators, money, timeLabel } from './types';
import { observations, sessionGrid } from './chartData';
import { Icon } from './ui';

type Primary = ISeriesApi<'Candlestick'> | ISeriesApi<'Line'>;
type Props = {
  session: Session; selected?: Scenario; indicator: Indicator; overlays: string[];
  onIndicator: (value: Indicator) => void; onFill: (fill: Fill) => void; onScenario: (id: string) => void;
};

function fillMarkers(session: Session, selected?: Scenario): SeriesMarker<Time>[] {
  const markers: SeriesMarker<Time>[] = session.fills.filter(fill => !selected || fill.scenario_id === selected.id).map(fill => ({
    time: (Math.floor(fill.time / 180) * 180) as UTCTimestamp, id: `fill:${fill.id}`,
    position: fill.side === 'buy' ? 'belowBar' : 'aboveBar', color: fill.side === 'buy' ? '#53dbb1' : '#b69cff',
    shape: fill.side === 'buy' ? 'arrowUp' : 'arrowDown', text: `${fill.side === 'buy' ? 'B' : 'S'} ${fill.qty}`, size: 1,
  }));
  if (selected) for (const event of selected.events) {
    if (!['created', 'triggered', 'expired', 'invalidated'].includes(event.status)) continue;
    markers.push({ time: (Math.floor(Math.max(session.open, event.time) / 180) * 180) as UTCTimestamp,
      id: `scenario:${selected.id}`, position: 'aboveBar', color: '#e1bc74', shape: 'circle',
      text: event.status === 'created' ? 'Authored' : event.status, size: .55 });
  }
  return markers.filter(m => Number(m.time) >= session.open && Number(m.time) < session.close)
    .sort((a, b) => Number(a.time) - Number(b.time));
}

function addIndicator(chart: IChartApi, session: Session, indicator: Indicator) {
  if (indicator === 'none') return;
  const names = indicator === 'stochrsi' ? ['stochrsi_k', 'stochrsi_d'] : [indicator];
  for (const [index, name] of names.entries()) {
    const histogram = name === 'macd_hist';
    const series = chart.addSeries(histogram ? HistogramSeries : LineSeries, {
      color: index ? '#e8b66d' : '#99a8ff', priceLineVisible: false, lastValueVisible: true,
      priceFormat: { type: 'price', precision: name === 'cvd_21' ? 0 : 2, minMove: name === 'cvd_21' ? 1 : .01 },
    }, 1);
    series.setData(observations(session.indicators[name] || [], session).map(p => histogram && 'value' in p
      ? { ...p, color: p.value! >= 0 ? '#3b9f86' : '#bc697b' } : p));
    if (name === 'rsi' || name === 'stochrsi_k') for (const price of name === 'rsi' ? [30, 70] : [20, 80]) {
      series.createPriceLine({ price, color: '#3d4658', lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true });
    }
  }
  chart.panes()[1]?.setStretchFactor(1);
  chart.panes()[0]?.setStretchFactor(3.5);
}

export default function Chart({ session, selected, indicator, overlays, onIndicator, onFill, onScenario }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const shell = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const primaryRef = useRef<Primary | null>(null);
  const zoneRef = useRef<ScenarioOverlay | null>(null);
  const callbackRef = useRef({ onFill, onScenario });
  callbackRef.current = { onFill, onScenario };
  const selectedRef = useRef(selected); selectedRef.current = selected;
  const rangeRef = useRef<{ day: string; range: { from: Time; to: Time } | null }>({ day: '', range: null });
  const [hover, setHover] = useState<{ time: number; text: string } | null>(null);
  const [hoverFill, setHoverFill] = useState<Fill | null>(null);
  const overlayKey = overlays.join(',');

  useEffect(() => {
    if (!container.current) return;
    const chart = createChart(container.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: '#101722' }, textColor: '#8793a9', fontFamily: 'ui-monospace, monospace', fontSize: 10,
        panes: { separatorColor: '#263041', separatorHoverColor: '#596680', enableResize: true }, attributionLogo: true },
      grid: { vertLines: { color: '#19222f' }, horzLines: { color: '#19222f' } },
      crosshair: { mode: CrosshairMode.Normal, vertLine: { color: '#566176', labelBackgroundColor: '#343e53' }, horzLine: { color: '#566176', labelBackgroundColor: '#343e53' } },
      rightPriceScale: { borderColor: '#263041', scaleMargins: { top: .16, bottom: .13 } },
      timeScale: { borderColor: '#263041', timeVisible: true, secondsVisible: false, rightOffset: 3, tickMarkFormatter: (t: Time) => timeLabel(Number(t)), },
      localization: { timeFormatter: (t: Time) => `${timeLabel(Number(t))} ET` },
    });
    chartRef.current = chart;
    const primary = session.candles.length ? chart.addSeries(CandlestickSeries, {
      upColor: '#46bc9c', downColor: '#dd7788', wickUpColor: '#46bc9c', wickDownColor: '#dd7788', borderVisible: false,
      priceLineColor: '#617487', priceLineStyle: LineStyle.Dashed,
    }) : chart.addSeries(LineSeries, { color: '#72b8e6', lineWidth: 2, priceLineVisible: true });
    primaryRef.current = primary;
    if (session.candles.length) {
      const candleMap = new Map(session.candles.map(c => [c.time, c]));
      (primary as ISeriesApi<'Candlestick'>).setData(sessionGrid(session).map(t => candleMap.has(t)
        ? { ...candleMap.get(t)!, time: t as UTCTimestamp } : { time: t as UTCTimestamp }));
    } else (primary as ISeriesApi<'Line'>).setData(observations(session.prices, session));
    const zone = new ScenarioOverlay(session.open, session.close);
    primary.attachPrimitive(zone); zone.setScenarios(selectedRef.current ? [selectedRef.current] : session.scenarios, !!selectedRef.current);
    zoneRef.current = zone;
    const markers = createSeriesMarkers(primary, fillMarkers(session, selectedRef.current));
    for (const name of overlays) {
      const series = chart.addSeries(LineSeries, { color: { vwap: '#e5ba75', ema_9: '#90a2e0', ema_21: '#c796d0' }[name],
        lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
      series.setData(observations(session.indicators[name] || [], session));
    }
    addIndicator(chart, session, indicator);
    chart.timeScale().fitContent();
    if (rangeRef.current.day === session.date && rangeRef.current.range) chart.timeScale().setVisibleRange(rangeRef.current.range);
    const hoverHandler = (param: MouseEventParams) => {
      const bar = param.seriesData.get(primary);
      setHover(param.time && bar ? { time: Number(param.time), text: 'open' in bar
        ? `O ${bar.open.toFixed(2)}   H ${bar.high.toFixed(2)}   L ${bar.low.toFixed(2)}   C ${bar.close.toFixed(2)}`
        : 'value' in bar ? `Observed ${money(bar.value)}` : 'No recorded data' } : null);
      setHoverFill(session.fills.find(f => `fill:${f.id}` === param.hoveredObjectId) || null);
    };
    chart.subscribeCrosshairMove(hoverHandler);
    chart.subscribeClick(param => {
      const fill = session.fills.find(f => `fill:${f.id}` === param.hoveredObjectId);
      if (fill) callbackRef.current.onFill(fill);
      else if (String(param.hoveredObjectId).startsWith('scenario:')) callbackRef.current.onScenario(String(param.hoveredObjectId).slice(9));
    });
    // Selection updates need not recreate the chart or reset zoom.
    const selectionHandler = () => {
      zone.setScenarios(selectedRef.current ? [selectedRef.current] : session.scenarios, !!selectedRef.current);
      markers.setMarkers(fillMarkers(session, selectedRef.current));
    };
    container.current.addEventListener('review-selection', selectionHandler);
    const element = container.current;
    return () => {
      rangeRef.current = { day: session.date, range: chart.timeScale().getVisibleRange() };
      element.removeEventListener('review-selection', selectionHandler);
      chart.remove(); chartRef.current = null; primaryRef.current = null; zoneRef.current = null;
    };
  }, [session, indicator, overlayKey]);

  useEffect(() => { container.current?.dispatchEvent(new Event('review-selection')); }, [selected]);
  const visibleFills = session.fills.filter(f => !selected || f.scenario_id === selected.id);
  return <section className="chart-panel" ref={shell} aria-label="Session chart">
    <header className="chart-heading"><div className="instrument"><span className="ticker-logo">Q</span><div><h2>QQQ <span>NASDAQ</span></h2><p>Invesco QQQ · 3-minute view</p></div></div>
      <div className="chart-price"><strong>{money(session.stats.last)}</strong><span className={(session.stats.change || 0) >= 0 ? 'positive' : 'negative'}>{(session.stats.change || 0) > 0 ? '+' : ''}{session.stats.change?.toFixed(2) || '—'} from first observation</span></div>
      <div className="chart-actions"><button className="quiet-button" onClick={() => chartRef.current?.timeScale().fitContent()}>Fit session</button><button className="icon-button" aria-label="Full-screen chart" onClick={() => { if (document.fullscreenElement) void document.exitFullscreen(); else void shell.current?.requestFullscreen(); }}><Icon name="expand" /></button></div>
    </header>
    <div className="chart-legend"><span className="dot green" />Trigger zone <span className="legend-target">—</span>Target <span className="dot purple" />Exit <span className="legend-observation">{session.candles.length ? `${session.candles.length} OHLC candles` : 'Recorded prices · OHLC unavailable'}</span></div>
    <div className="chart-canvas-wrap"><div className="chart-readout">{hover ? `${timeLabel(hover.time)} ET   ${hover.text}` : 'Hover to inspect · scroll to zoom · drag to pan'}</div><div className="chart-canvas" ref={container} data-testid="price-chart" />
      {!session.candles.length && !session.prices.length && <div className="chart-empty">No market observations recorded for this session.</div>}
      {hoverFill && <div className="fill-tooltip"><b>{hoverFill.side === 'buy' ? 'Entry' : 'Exit'} · {hoverFill.qty} contracts</b><span>{hoverFill.symbol}</span><span>{money(hoverFill.price)} option premium · {timeLabel(hoverFill.time)} ET</span><small>{hoverFill.time_basis}</small>{hoverFill.pnl != null && <span>Realized {money(hoverFill.pnl)} before fees</span>}<span>{hoverFill.reason}</span><small>Click to inspect the setup</small></div>}
    </div>
    <footer className="chart-footer"><span>{session.price_source} · ET</span><span>{visibleFills.length} confirmed fills</span></footer>
    {indicator !== 'none' && <div className="indicator-caption"><span><b>{indicators.find(i => i.value === indicator)?.label}</b> · Last recorded observation per 3m interval · gaps preserved</span><button className="icon-button" onClick={() => onIndicator('none')} aria-label="Hide indicator"><Icon name="close" size={13} /></button></div>}
  </section>;
}
