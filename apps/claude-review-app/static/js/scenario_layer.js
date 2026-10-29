import { barTimeOf } from "./format.js";
import { directionColor } from "./theme.js";
import { indexOfBar, lastBarTime, showBarRange, snapToBar } from "./chart_view.js";

const LC = window.LightweightCharts;
const MARKER_TEXT_LIMIT = 22;
const SCROLL_PADDING_BARS = 6;
const MIN_VISIBLE_BARS = 36;

function scenarioEndTime(view, scenario) {
  const last = lastBarTime(view);
  if (!Number.isFinite(scenario.end_time)) return last;
  return Math.min(barTimeOf(scenario.end_time), last);
}

function eventColor(theme, kind, direction) {
  switch (kind) {
    case "created":
      return theme.accent;
    case "triggered":
    case "signal_confirmed":
    case "entered":
      return directionColor(theme, direction);
    case "entry_timing":
      return theme.strongText;
    case "invalidated":
      return theme.invalid;
    case "expired":
      return theme.faint;
    default:
      return theme.faint;
  }
}

function shortText(text, fallback) {
  const value = String(text || fallback || "").trim();
  return value.length > MARKER_TEXT_LIMIT ? value.slice(0, MARKER_TEXT_LIMIT - 1) + "." : value;
}

export function scenarioMarkers(view, scenario) {
  if (!scenario || view.barTimes.length === 0) return [];
  return (scenario.events ?? [])
    .filter((event) => Number.isFinite(event.time))
    .map((event, index) => ({
      id: `scenario-${index}`,
      time: snapToBar(view, barTimeOf(event.time)),
      position: "aboveBar",
      shape: "circle",
      size: 0.8,
      color: eventColor(view.theme, event.kind, scenario.direction),
      text: shortText(event.text, event.kind),
    }));
}

function zoneColors(theme, direction) {
  return direction === "put"
    ? { fill: theme.putZone, stroke: theme.put }
    : { fill: theme.callZone, stroke: theme.call };
}

function zoneFor(view, scenario) {
  const zone = scenario.trigger_zone;
  const fromTime = snapToBar(view, barTimeOf(scenario.created_time));
  const toTime = snapToBar(view, scenarioEndTime(view, scenario));
  if (!zone || !Number.isFinite(zone.low) || !Number.isFinite(zone.high) || fromTime === null) return null;
  return {
    fromTime,
    toTime,
    fromIndex: indexOfBar(view, fromTime),
    toIndex: indexOfBar(view, toTime),
    low: Math.min(zone.low, zone.high),
    high: Math.max(zone.low, zone.high),
    ...zoneColors(view.theme, scenario.direction),
    autoscalePrices: [zone.low, zone.high, scenario.target_price, scenario.invalidation_price],
  };
}

function priceLinesFor(view, scenario) {
  const lines = [];
  if (Number.isFinite(scenario.target_price)) {
    lines.push(view.candles.createPriceLine({
      price: scenario.target_price,
      color: directionColor(view.theme, scenario.direction),
      lineWidth: 1,
      lineStyle: LC.LineStyle.Dashed,
      axisLabelVisible: true,
      title: "Target",
    }));
  }
  if (Number.isFinite(scenario.invalidation_price)) {
    const operator = scenario.invalidation_op ? ` ${scenario.invalidation_op}` : "";
    lines.push(view.candles.createPriceLine({
      price: scenario.invalidation_price,
      color: view.theme.invalid,
      lineWidth: 1,
      lineStyle: LC.LineStyle.LargeDashed,
      axisLabelVisible: true,
      title: `Invalidation${operator}`,
    }));
  }
  return lines;
}

export function clearScenario(view) {
  (view.scenarioLines ?? []).forEach((line) => view.candles.removePriceLine(line));
  view.scenarioLines = [];
  view.zone.setZone(null);
}

export function drawScenario(view, scenario) {
  clearScenario(view);
  if (!scenario || view.barTimes.length === 0) return;
  view.scenarioLines = priceLinesFor(view, scenario);
  view.zone.setZone(zoneFor(view, scenario));
}

export function scrollToScenario(view, scenario) {
  if (!scenario || view.barTimes.length === 0) return;
  const fromIndex = indexOfBar(view, barTimeOf(scenario.created_time));
  const toIndex = indexOfBar(view, scenarioEndTime(view, scenario));
  const span = Math.max(toIndex - fromIndex + SCROLL_PADDING_BARS * 2, MIN_VISIBLE_BARS);
  const lastIndex = view.barTimes.length - 1;
  const centered = (fromIndex + toIndex) / 2 - span / 2;
  // Keep the window over real bars rather than empty space before the open or after the close.
  const from = Math.max(-2, Math.min(centered, lastIndex + 3 - span));
  showBarRange(view, from, from + span);
}
