import { el, setPressed } from "./dom.js";
import { orderedOscillatorKeys } from "./sub_chart.js";

function option(value, text, selected) {
  const node = el("option", { text });
  node.value = value;
  node.selected = selected;
  return node;
}

export function renderDayOptions(select, days, selectedDate) {
  select.replaceChildren(...days.map((day) => {
    const suffix = day.is_today ? " (today)" : "";
    return option(day.date, `${day.date}${suffix}`, day.date === selectedDate);
  }));
  select.disabled = days.length === 0;
}

function groupByBook(scenarios) {
  const sorted = [...scenarios].sort((a, b) => a.created_time - b.created_time);
  const groups = new Map();
  for (const scenario of sorted) {
    const book = scenario.book || "Unassigned";
    groups.set(book, [...(groups.get(book) ?? []), scenario]);
  }
  return groups;
}

function scenarioOption(scenario, selectedId) {
  const direction = scenario.direction ? `${scenario.direction.toUpperCase()}: ` : "";
  const text = `${direction}${scenario.label || scenario.id} [${scenario.status || "no status"}]`;
  const node = option(scenario.id, text, scenario.id === selectedId);
  if (scenario.direction) node.classList.add(`is-${scenario.direction}`);
  return node;
}

export function renderScenarioOptions(select, scenarios, selectedId) {
  const nodes = [option("", "(no scenario)", !selectedId)];
  groupByBook(scenarios).forEach((items, book) => {
    const group = el("optgroup", { attrs: { label: book } });
    items.forEach((scenario) => group.append(scenarioOption(scenario, selectedId)));
    nodes.push(group);
  });
  select.replaceChildren(...nodes);
  select.disabled = scenarios.length === 0;
}

export function renderSubChartOptions(select, oscillators, selectedKey) {
  const keys = orderedOscillatorKeys(oscillators);
  select.replaceChildren(...keys.map((key) => {
    const label = oscillators[key]?.label || key;
    return option(key, label, key === selectedKey);
  }));
  select.disabled = keys.length === 0;
}

export function syncToggle(button, pressed, available, unavailableTitle) {
  setPressed(button, pressed && available);
  button.disabled = !available;
  button.title = available ? "" : unavailableTitle;
}

export function syncReload(button, payload) {
  button.disabled = !payload;
  button.title = payload && payload.is_today
    ? "Reload today's logs and bars"
    : "Reload the logs and fetch the bars again, replacing the cached bars";
}
