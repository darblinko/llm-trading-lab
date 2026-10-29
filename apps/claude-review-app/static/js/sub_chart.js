import { el } from "./dom.js";
import { formatPrice, formatVolume } from "./format.js";

const LC = window.LightweightCharts;
const SUB_PANE = 1;
const MAIN_STRETCH = 3;
const SUB_STRETCH = 1;
const PREFERRED_ORDER = ["rsi", "stochrsi", "macd", "volume", "rvol"];

export function orderedOscillatorKeys(oscillators) {
  const keys = Object.keys(oscillators);
  const rank = (key) => {
    const index = PREFERRED_ORDER.indexOf(key.toLowerCase());
    return index === -1 ? PREFERRED_ORDER.length : index;
  };
  return [...keys].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
}

export function defaultOscillatorKey(oscillators, preferred) {
  const keys = orderedOscillatorKeys(oscillators);
  if (preferred && keys.includes(preferred)) return preferred;
  return keys.find((key) => key.toLowerCase() === "rsi") ?? keys[0] ?? null;
}

export function createSubChart(view, legendNode) {
  const sub = { view, legendNode, entries: [], oscillator: null, key: null };
  view.crosshairListeners.push((param) => updateLegend(sub, param.time));
  return sub;
}

function isVolumeKey(key) {
  return key.toLowerCase().includes("volume");
}

function histogramColor(sub, key, point) {
  const theme = sub.view.theme;
  if (isVolumeKey(key)) {
    const bar = sub.view.barByTime.get(point.time);
    if (!bar) return theme.histogramNeutral;
    return bar.close >= bar.open ? theme.histogramUp : theme.histogramDown;
  }
  if (key.toLowerCase().includes("macd")) {
    return point.value >= 0 ? theme.histogramUp : theme.histogramDown;
  }
  return theme.histogramNeutral;
}

function valueFormat(key) {
  return isVolumeKey(key)
    ? { type: "volume" }
    : { type: "price", precision: 2, minMove: 0.01 };
}

function addHistogram(sub, key, points) {
  const series = sub.view.chart.addSeries(LC.HistogramSeries, {
    priceFormat: valueFormat(key),
    priceLineVisible: false,
    lastValueVisible: false,
  }, SUB_PANE);
  const clean = points.filter((point) => Number.isFinite(point.value));
  series.setData(clean.map((point) => ({ ...point, color: histogramColor(sub, key, point) })));
  return { series, label: key, color: sub.view.theme.histogramNeutral, byTime: toMap(clean), key };
}

function addLine(sub, key, name, points, color) {
  const series = sub.view.chart.addSeries(LC.LineSeries, {
    color,
    lineWidth: 1,
    priceFormat: valueFormat(key),
    priceLineVisible: false,
    lastValueVisible: true,
    crosshairMarkerRadius: 3,
  }, SUB_PANE);
  const clean = points.filter((point) => Number.isFinite(point.value));
  series.setData(clean);
  return { series, label: name, color, byTime: toMap(clean), key };
}

function toMap(points) {
  return new Map(points.map((point) => [point.time, point.value]));
}

function addLevelLines(sub, levels) {
  const first = sub.entries[0];
  if (!first) return;
  for (const level of levels) {
    if (!Number.isFinite(level)) continue;
    first.series.createPriceLine({
      price: level,
      color: sub.view.theme.oscillatorLevel,
      lineWidth: 1,
      lineStyle: LC.LineStyle.Dashed,
      axisLabelVisible: false,
    });
  }
}

function removeEntries(sub) {
  sub.entries.forEach((entry) => sub.view.chart.removeSeries(entry.series));
  sub.entries = [];
}

export function showOscillator(sub, key, oscillator) {
  removeEntries(sub);
  sub.key = key;
  sub.oscillator = oscillator ?? null;
  if (!oscillator) {
    updateLegend(sub, undefined);
    return;
  }
  if (Array.isArray(oscillator.histogram) && oscillator.histogram.length > 0) {
    sub.entries.push(addHistogram(sub, key, oscillator.histogram));
  }
  const palette = sub.view.theme.oscillatorLines;
  Object.entries(oscillator.lines ?? {}).forEach(([name, points], index) => {
    if (!Array.isArray(points)) return;
    sub.entries.push(addLine(sub, key, name, points, palette[index % palette.length]));
  });
  addLevelLines(sub, oscillator.levels ?? []);
  applyStretch(sub);
  updateLegend(sub, undefined);
}

export function hideOscillator(sub) {
  removeEntries(sub);
  sub.oscillator = null;
  sub.legendNode.hidden = true;
}

function applyStretch(sub) {
  const panes = sub.view.chart.panes();
  if (panes.length < 2) return;
  panes[0].setStretchFactor(MAIN_STRETCH);
  panes[SUB_PANE].setStretchFactor(SUB_STRETCH);
}

function legendValue(entry, time) {
  const value = entry.byTime.get(time);
  return isVolumeKey(entry.key) ? formatVolume(value) : formatPrice(value);
}

function latestTime(sub) {
  const bars = sub.view.bars;
  return bars.length ? bars[bars.length - 1].time : undefined;
}

export function updateLegend(sub, time) {
  const node = sub.legendNode;
  if (!sub.oscillator || sub.entries.length === 0) {
    node.hidden = true;
    return;
  }
  const at = time ?? latestTime(sub);
  const items = sub.entries.map((entry) => {
    const item = el("span", { className: "readout-item readout-swatch" }, [
      el("span", { className: "readout-label", text: entry.label }),
      el("span", { className: "readout-value", text: legendValue(entry, at) }),
    ]);
    item.style.setProperty("--swatch", entry.color);
    return item;
  });
  node.replaceChildren(el("span", { className: "legend-title", text: sub.oscillator.label ?? sub.key }), ...items);
  node.hidden = false;
  positionLegend(sub);
}

export function positionLegend(sub) {
  if (sub.view.chart.panes().length < 2) return;
  const mainHeight = sub.view.chart.paneSize(0).height;
  sub.legendNode.style.top = `${Math.round(mainHeight) + 4}px`;
}
