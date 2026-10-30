import { el } from "./dom.js";
import { clockTime, formatPrice, formatSigned, formatVolume } from "./format.js";
import { ZonePrimitive } from "./zone_primitive.js";

const LC = window.LightweightCharts;
const FONT_STACK = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';

function chartOptions(theme) {
  return {
    autoSize: true,
    layout: {
      background: { type: LC.ColorType.Solid, color: theme.background },
      textColor: theme.text,
      fontFamily: FONT_STACK,
      fontSize: 11,
      attributionLogo: true,
      panes: { separatorColor: theme.line, separatorHoverColor: theme.line, enableResize: false },
    },
    grid: { vertLines: { color: theme.grid }, horzLines: { color: theme.grid } },
    rightPriceScale: { borderColor: theme.line },
    timeScale: {
      borderColor: theme.line,
      timeVisible: true,
      secondsVisible: false,
      rightOffset: 3,
      barSpacing: 7,
      lockVisibleTimeRangeOnResize: true,
      tickMarkFormatter: (time) => clockTime(time),
    },
    crosshair: {
      mode: LC.CrosshairMode.Normal,
      vertLine: { color: theme.crosshair, labelBackgroundColor: theme.line },
      horzLine: { color: theme.crosshair, labelBackgroundColor: theme.line },
    },
    localization: { timeFormatter: (time) => clockTime(time) },
  };
}

function candleOptions(theme) {
  return {
    upColor: theme.up,
    downColor: theme.down,
    borderVisible: false,
    wickUpColor: theme.up,
    wickDownColor: theme.down,
    priceLineVisible: false,
  };
}

export function createChartView(container, readoutNode, theme) {
  const chart = LC.createChart(container, chartOptions(theme));
  const candles = chart.addSeries(LC.CandlestickSeries, candleOptions(theme), 0);
  const zone = new ZonePrimitive(chart);
  candles.attachPrimitive(zone);
  const view = {
    chart,
    candles,
    zone,
    markers: LC.createSeriesMarkers(candles, []),
    readoutNode,
    theme,
    bars: [],
    barTimes: [],
    barByTime: new Map(),
    overlaySeries: new Map(),
    overlayVisibility: { vwap: false, ema: false },
    levelLines: [],
    crosshairListeners: [],
  };
  chart.subscribeCrosshairMove((param) => {
    view.crosshairListeners.forEach((listener) => listener(param));
  });
  view.crosshairListeners.push((param) => updateReadout(view, param.time));
  return view;
}

export function applyChartTheme(view, theme) {
  view.theme = theme;
  view.chart.applyOptions(chartOptions(theme));
  view.candles.applyOptions(candleOptions(theme));
}

export function setBars(view, bars) {
  const clean = bars.filter((bar) => Number.isFinite(bar.time) && Number.isFinite(bar.close));
  view.bars = clean;
  view.barTimes = clean.map((bar) => bar.time);
  view.barByTime = new Map(clean.map((bar) => [bar.time, bar]));
  view.candles.setData(
    clean.map(({ time, open, high, low, close }) => ({ time, open, high, low, close })),
  );
  updateReadout(view, undefined);
}

// Largest bar time at or before `time`, clamped to the first bar.
export function snapToBar(view, time) {
  const times = view.barTimes;
  if (times.length === 0) return null;
  if (time <= times[0]) return times[0];
  let low = 0;
  let high = times.length - 1;
  while (low < high) {
    const middle = Math.ceil((low + high) / 2);
    if (times[middle] <= time) low = middle;
    else high = middle - 1;
  }
  return times[low];
}

export function indexOfBar(view, time) {
  const snapped = snapToBar(view, time);
  return snapped === null ? -1 : view.barTimes.indexOf(snapped);
}

export function lastBarTime(view) {
  return view.barTimes.length ? view.barTimes[view.barTimes.length - 1] : null;
}

function overlayKind(key) {
  const name = key.toLowerCase();
  if (name.includes("vwap")) return "vwap";
  if (name.includes("ema")) return "ema";
  return "other";
}

function overlayStyle(key, theme) {
  const kind = overlayKind(key);
  if (kind === "vwap") return { color: theme.vwap, lineWidth: 2, label: "VWAP" };
  const period = (key.match(/\d+/) ?? [""])[0];
  const color = period === "9" ? theme.ema9 : theme.ema21;
  return { color, lineWidth: 1, label: period ? `EMA ${period}` : key };
}

export function setOverlays(view, overlays) {
  view.overlaySeries.forEach(({ series }) => view.chart.removeSeries(series));
  view.overlaySeries = new Map();
  for (const [key, points] of Object.entries(overlays)) {
    if (!Array.isArray(points) || overlayKind(key) === "other") continue;
    const style = overlayStyle(key, view.theme);
    const series = view.chart.addSeries(LC.LineSeries, {
      color: style.color,
      lineWidth: style.lineWidth,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
      visible: view.overlayVisibility[overlayKind(key)] === true,
    }, 0);
    series.setData(points.filter((point) => Number.isFinite(point.value)));
    const byTime = new Map(points.map((point) => [point.time, point.value]));
    view.overlaySeries.set(key, { series, style, kind: overlayKind(key), byTime });
  }
}

export function hasOverlayKind(view, kind) {
  return [...view.overlaySeries.values()].some((entry) => entry.kind === kind);
}

export function setOverlayVisibility(view, visibility) {
  view.overlayVisibility = { ...visibility };
  view.overlaySeries.forEach((entry, key) => {
    entry.series.applyOptions({
      visible: visibility[entry.kind] === true,
      color: overlayStyle(key, view.theme).color,
    });
  });
  updateReadout(view, undefined);
}

export function setKeyLevels(view, levels, visible) {
  view.levelLines.forEach((line) => view.candles.removePriceLine(line));
  view.levelLines = [];
  if (!visible) return;
  for (const level of levels) {
    if (!Number.isFinite(level.price)) continue;
    const color = view.theme.levelGroups[level.group] ?? view.theme.levelDefault;
    view.levelLines.push(view.candles.createPriceLine({
      price: level.price,
      color,
      lineWidth: 1,
      lineStyle: LC.LineStyle.Dotted,
      axisLabelVisible: true,
      title: String(level.label ?? ""),
    }));
  }
}

export function showBarRange(view, fromIndex, toIndex) {
  view.chart.timeScale().setVisibleLogicalRange({ from: fromIndex, to: toIndex });
}

export function fitAll(view) {
  view.chart.timeScale().fitContent();
}

export function saveRange(view) {
  return view.chart.timeScale().getVisibleLogicalRange();
}

export function restoreRange(view, range) {
  if (range) view.chart.timeScale().setVisibleLogicalRange(range);
}

function readoutItem(label, value, className = "") {
  return el("span", { className: `readout-item ${className}`.trim() }, [
    el("span", { className: "readout-label", text: label }),
    el("span", { className: "readout-value", text: value }),
  ]);
}

function overlayReadoutItems(view, time) {
  const items = [];
  view.overlaySeries.forEach((entry) => {
    if (view.overlayVisibility[entry.kind] !== true) return;
    const item = readoutItem(entry.style.label, formatPrice(entry.byTime.get(time)));
    item.style.setProperty("--swatch", entry.style.color);
    item.classList.add("readout-swatch");
    items.push(item);
  });
  return items;
}

function updateReadout(view, time) {
  const bar = view.barByTime.get(time) ?? view.bars[view.bars.length - 1];
  if (!bar) {
    view.readoutNode.replaceChildren();
    return;
  }
  const change = bar.close - bar.open;
  const tone = change >= 0 ? "is-up" : "is-down";
  view.readoutNode.replaceChildren(
    el("span", { className: "readout-symbol", text: "QQQ 3m" }),
    el("span", { className: "readout-time", text: clockTime(bar.time) }),
    readoutItem("O", formatPrice(bar.open)),
    readoutItem("H", formatPrice(bar.high)),
    readoutItem("L", formatPrice(bar.low)),
    readoutItem("C", formatPrice(bar.close), tone),
    readoutItem("Chg", formatSigned(change), tone),
    readoutItem("V", formatVolume(bar.volume)),
    ...overlayReadoutItems(view, bar.time),
  );
}
