import { el } from "./dom.js";
import { barTimeOf, clockTime, formatMoney, formatPrice, humanize } from "./format.js";
import { snapToBar } from "./chart_view.js";

const TOOLTIP_OFFSET = 14;

function directionLetter(direction) {
  return direction === "put" ? "P" : "C";
}

function fillsOf(trade) {
  const fills = [];
  if (trade.entry) fills.push({ trade, fill: trade.entry, kind: "entry" });
  (trade.exits ?? []).forEach((fill) => fills.push({ trade, fill, kind: "exit" }));
  return fills.filter(({ fill }) => Number.isFinite(fill.time));
}

function markerFor(view, { trade, fill, kind }, index) {
  const isPut = trade.direction === "put";
  const theme = view.theme;
  const time = snapToBar(view, barTimeOf(fill.time));
  if (kind === "entry") {
    return {
      id: `trade-${index}`,
      time,
      position: isPut ? "aboveBar" : "belowBar",
      shape: isPut ? "arrowDown" : "arrowUp",
      color: isPut ? theme.put : theme.call,
      size: 1.3,
      text: `Buy ${directionLetter(trade.direction)} ${fill.qty}`,
    };
  }
  return {
    id: `trade-${index}`,
    time,
    position: isPut ? "belowBar" : "aboveBar",
    shape: isPut ? "arrowUp" : "arrowDown",
    color: isPut ? theme.putSoft : theme.callSoft,
    size: 1.1,
    text: `Sell ${fill.qty}`,
  };
}

export function tradeMarkers(view, trades) {
  if (view.barTimes.length === 0) return [];
  return trades.flatMap(fillsOf).map((entry, index) => markerFor(view, entry, index));
}

export function buildFillIndex(view, trades) {
  const index = new Map();
  if (view.barTimes.length === 0) return index;
  for (const entry of trades.flatMap(fillsOf)) {
    const time = snapToBar(view, barTimeOf(entry.fill.time));
    index.set(time, [...(index.get(time) ?? []), entry]);
  }
  return index;
}

function row(label, value, className = "") {
  return el("div", { className: "tip-row" }, [
    el("span", { className: "tip-label", text: label }),
    el("span", { className: `tip-value ${className}`.trim(), text: value }),
  ]);
}

function pnlTone(value) {
  if (!Number.isFinite(value)) return "";
  return value >= 0 ? "is-up" : "is-down";
}

function fillBlock({ trade, fill, kind }) {
  const heading = kind === "entry" ? "Entry" : "Exit";
  const directionClass = trade.direction === "put" ? "is-put" : "is-call";
  const rows = [
    el("div", { className: `tip-heading ${directionClass}` }, [
      el("span", { text: `${heading} ${humanize(trade.direction)}` }),
      el("span", { className: "tip-time", text: `detected ${clockTime(fill.time, true)}` }),
    ]),
    row("Contract", trade.contract ?? "n/a"),
    row("Qty", `${fill.qty} of ${trade.qty}`),
    row("Option fill", formatPrice(fill.option_price)),
    row("QQQ", formatPrice(fill.underlying_price)),
  ];
  if (kind === "exit") rows.push(row("Exit reason", humanize(fill.reason)));
  if (kind === "entry" && trade.scenario_label) rows.push(row("Scenario", trade.scenario_label));
  const pnlText = trade.open ? "open" : formatMoney(trade.realized_pnl);
  rows.push(row("Trade profit or loss", pnlText, pnlTone(trade.realized_pnl)));
  return el("div", { className: "tip-block" }, rows);
}

export function createFillTooltip(view, node, getIndex) {
  view.crosshairListeners.push((param) => {
    const entries = param.time === undefined ? null : getIndex().get(param.time);
    if (!entries || !param.point) {
      node.hidden = true;
      return;
    }
    node.replaceChildren(...entries.map(fillBlock));
    node.hidden = false;
    placeTooltip(node, param.point);
  });
}

function placeTooltip(node, point) {
  const container = node.parentElement.getBoundingClientRect();
  const width = node.offsetWidth;
  const height = node.offsetHeight;
  let left = point.x + TOOLTIP_OFFSET;
  if (left + width > container.width - 8) left = point.x - width - TOOLTIP_OFFSET;
  let top = point.y + TOOLTIP_OFFSET;
  if (top + height > container.height - 8) top = Math.max(8, container.height - height - 8);
  node.style.left = `${Math.max(8, left)}px`;
  node.style.top = `${top}px`;
}
