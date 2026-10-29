import { el } from "./dom.js";
import { capitalize, clockTime, formatMoney, formatPrice, humanize } from "./format.js";
import { agentCard, legKeys, linkQualityNote, voteStrip } from "./agent_card.js";

export function createDrawer(root, tab, panel) {
  return { root, tab, panel, open: false, renderedScenarioId: null };
}

export function setDrawerOpen(drawer, open) {
  drawer.open = open;
  drawer.root.dataset.open = open ? "true" : "false";
  drawer.tab.setAttribute("aria-expanded", open ? "true" : "false");
  drawer.tab.title = open ? "Collapse reasoning" : "Open reasoning";
  drawer.panel.hidden = !open;
}

export function evaluationsFor(scenario, evaluations) {
  if (!scenario) return [];
  const ids = new Set(scenario.evaluation_ids ?? []);
  return evaluations
    .filter((evaluation) => ids.has(evaluation.id))
    .sort((a, b) => a.time - b.time);
}

function chip(text, className) {
  return el("span", { className: `chip ${className}`, text });
}

function scenarioHeader(scenario) {
  const directionClass = scenario.direction === "put" ? "is-put" : "is-call";
  return el("header", { className: "drawer-header" }, [
    el("h2", { className: "drawer-title", text: scenario.label || "Unlabelled scenario" }),
    el("div", { className: "chip-row" }, [
      chip(capitalize(scenario.direction || "n/a"), `chip-direction ${directionClass}`),
      chip(humanize(scenario.status), `chip-status status-${String(scenario.status || "none")}`),
      chip(scenario.book || "no book", "chip-book"),
    ]),
  ]);
}

function zoneText(zone) {
  if (!zone) return "none";
  return `${formatPrice(zone.low)} to ${formatPrice(zone.high)}`;
}

function invalidationText(scenario) {
  if (!Number.isFinite(scenario.invalidation_price)) return "none parsed";
  const operator = scenario.invalidation_op ? `price ${scenario.invalidation_op} ` : "";
  return operator + formatPrice(scenario.invalidation_price);
}

function detailRows(scenario) {
  const end = Number.isFinite(scenario.end_time) ? clockTime(scenario.end_time, true) : "no terminal event";
  return [
    ["Setup", humanize(scenario.setup_type)],
    ["Confidence", humanize(scenario.confidence)],
    ["Source", humanize(scenario.source)],
    ["Created", clockTime(scenario.created_time, true)],
    ["Ended", end],
    ["Zone", zoneText(scenario.trigger_zone)],
    ["Target", Number.isFinite(scenario.target_price) ? formatPrice(scenario.target_price) : "none"],
    ["Invalidation", invalidationText(scenario)],
    ["TTL", Number.isFinite(scenario.ttl_minutes) ? `${scenario.ttl_minutes} min` : "none"],
    ["Terminal reason", scenario.terminal_reason || "none"],
  ];
}

function detailsList(scenario) {
  const items = detailRows(scenario).flatMap(([term, value]) => [
    el("dt", { text: term }),
    el("dd", { className: "num", text: value }),
  ]);
  return el("dl", { className: "detail-grid" }, items);
}

function conditionList(title, conditions) {
  const list = Array.isArray(conditions) && conditions.length > 0
    ? el("ul", { className: "condition-list" }, conditions.map((text) => el("li", { text })))
    : el("p", { className: "muted", text: "None recorded." });
  return el("section", { className: "drawer-section" }, [el("h3", { className: "section-title", text: title }), list]);
}

function lifecycleList(events, direction) {
  const sorted = [...(events ?? [])].sort((a, b) => a.time - b.time);
  const directionClass = direction === "put" ? "is-put" : "is-call";
  const list = sorted.length > 0
    ? el("ol", { className: `event-list ${directionClass}` }, sorted.map((event) => el("li", { className: `event event-${event.kind}` }, [
      el("span", { className: "event-time num", text: clockTime(event.time, true) }),
      el("span", { className: "event-kind", text: humanize(event.kind) }),
      el("span", { className: "event-text", text: event.text || "" }),
      el("span", { className: "event-price num", text: Number.isFinite(event.price) ? formatPrice(event.price) : "" }),
    ])))
    : el("p", { className: "muted", text: "No lifecycle events recorded." });
  return el("section", { className: "drawer-section" }, [el("h3", { className: "section-title", text: "Lifecycle" }), list]);
}

function evaluationSelect(evaluations, selectedId, onChange) {
  const select = el("select", { attrs: { "aria-label": "Consensus evaluation" }, className: "eval-select" });
  evaluations.forEach((evaluation) => {
    const option = el("option", { text: `${clockTime(evaluation.time, true)}, ${humanize(evaluation.decision)}` });
    option.value = evaluation.id;
    option.selected = evaluation.id === selectedId;
    select.append(option);
  });
  select.addEventListener("change", () => onChange(select.value));
  return select;
}

function consensusBlock(evaluation) {
  return el("div", { className: "consensus" }, [
    voteStrip(evaluation),
    linkQualityNote(evaluation),
    el("p", { className: "consensus-text", text: evaluation.consensus_reasoning || "No consensus text recorded." }),
  ]);
}

function evaluationSection(evaluations, selected, handlers) {
  const title = el("h3", { className: "section-title", text: `Consensus calls (${evaluations.length})` });
  if (!selected) {
    return el("section", { className: "drawer-section" }, [
      title,
      el("p", { className: "muted", text: "No consensus call is linked to this scenario. A direction-gate pass makes no LLM call." }),
    ]);
  }
  const expand = el("button", { className: "button", text: "Expand", attrs: { type: "button", title: "Show both agents side by side" } });
  expand.addEventListener("click", handlers.onExpand);
  const controls = el("div", { className: "eval-controls" }, [
    evaluationSelect(evaluations, selected.id, handlers.onEvaluationChange),
    expand,
  ]);
  const cards = el("div", { className: "card-stack" }, legKeys(selected).map((key) => agentCard(key, selected.legs[key])));
  return el("section", { className: "drawer-section" }, [title, controls, consensusBlock(selected), cards]);
}

function tradeSummary(trades) {
  if (trades.length === 0) return el("p", { className: "muted", text: "No fills recorded for this day." });
  return el("ul", { className: "trade-list" }, trades.map((trade) => el("li", { className: "trade-item" }, [
    el("span", { className: `trade-contract ${trade.direction === "put" ? "is-put" : "is-call"}`, text: trade.contract || "n/a" }),
    el("span", { className: "num", text: trade.entry ? clockTime(trade.entry.time) : "n/a" }),
    el("span", { className: "trade-label", text: trade.scenario_label || "" }),
    el("span", { className: `num ${trade.realized_pnl >= 0 ? "is-up" : "is-down"}`, text: trade.open ? "open" : formatMoney(trade.realized_pnl) }),
  ])));
}

function emptyState(trades) {
  return el("div", { className: "drawer-empty" }, [
    el("p", { text: "Select a scenario in the toolbar to see its trigger plan, lifecycle and both agents' reasoning." }),
    el("section", { className: "drawer-section" }, [el("h3", { className: "section-title", text: "Trades" }), tradeSummary(trades)]),
  ]);
}

export function renderDrawer(drawer, model, handlers) {
  const { scenario, evaluations, selectedEvaluation, trades } = model;
  const scenarioId = scenario ? scenario.id : null;
  if (scenarioId !== drawer.renderedScenarioId) drawer.panel.scrollTop = 0;
  drawer.renderedScenarioId = scenarioId;
  if (!scenario) {
    drawer.panel.replaceChildren(emptyState(trades));
    return;
  }
  drawer.panel.replaceChildren(
    scenarioHeader(scenario),
    detailsList(scenario),
    conditionList("Trigger conditions", scenario.trigger_conditions),
    conditionList("Invalidation conditions", scenario.invalidation_conditions),
    lifecycleList(scenario.events, scenario.direction),
    evaluationSection(evaluations, selectedEvaluation, handlers),
  );
}
