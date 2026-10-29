import { byId, el, isPressed, setPressed } from "./dom.js";
import { fetchDay, fetchDays } from "./api.js";
import { initialThemeName, readTheme, setThemeName } from "./theme.js";
import {
  applyChartTheme, createChartView, fitAll, hasOverlayKind, restoreRange, saveRange,
  setBars, setKeyLevels, setOverlays, setOverlayVisibility,
} from "./chart_view.js";
import { createSubChart, defaultOscillatorKey, hideOscillator, positionLegend, showOscillator } from "./sub_chart.js";
import { clearScenario, drawScenario, scenarioMarkers, scrollToScenario } from "./scenario_layer.js";
import { buildFillIndex, createFillTooltip, tradeMarkers } from "./trades_layer.js";
import { createDrawer, evaluationsFor, renderDrawer, setDrawerOpen } from "./drawer.js";
import { openExpandView } from "./expand_view.js";
import {
  renderDayOptions, renderScenarioOptions, renderSubChartOptions, syncReload, syncToggle,
} from "./toolbar.js";

const nodes = {
  daySelect: byId("day-select"),
  scenarioSelect: byId("scenario-select"),
  subSelect: byId("sub-select"),
  vwapToggle: byId("toggle-vwap"),
  emaToggle: byId("toggle-ema"),
  levelsToggle: byId("toggle-levels"),
  subHiddenToggle: byId("toggle-sub-hidden"),
  reloadButton: byId("reload-button"),
  themeButton: byId("theme-button"),
  loadState: byId("load-state"),
  errorBanner: byId("error-banner"),
  errorText: byId("error-text"),
  warningBanner: byId("warning-banner"),
  warningList: byId("warning-list"),
  chartEmpty: byId("chart-empty"),
};

const state = {
  date: null,
  payload: null,
  scenarioId: "",
  evaluationId: null,
  overlays: { vwap: false, ema: false, levels: false },
  subKey: null,
  subHidden: false,
  loadToken: 0,
};

let view;
let sub;
let drawer;
let fillIndex = new Map();

function emptyPayload(date) {
  return {
    date, is_today: false, warnings: [], bars: [],
    indicators: { overlays: {}, oscillators: {} },
    key_levels: [], scenarios: [], evaluations: [], trades: [],
  };
}

function selectedScenario() {
  return state.payload?.scenarios.find((scenario) => scenario.id === state.scenarioId) ?? null;
}

function showError(message) {
  nodes.errorText.textContent = message;
  nodes.errorBanner.hidden = false;
}

function hideError() {
  nodes.errorBanner.hidden = true;
}

function renderWarnings(warnings) {
  nodes.warningList.replaceChildren(...warnings.map((text) => el("li", { text })));
  nodes.warningBanner.hidden = warnings.length === 0;
}

function setLoading(message) {
  nodes.loadState.textContent = message;
  nodes.reloadButton.disabled = Boolean(message) || !state.payload?.is_today;
}

function refreshMarkers() {
  const trades = state.payload?.trades ?? [];
  const markers = [...tradeMarkers(view, trades), ...scenarioMarkers(view, selectedScenario())];
  view.markers.setMarkers(markers.sort((a, b) => a.time - b.time));
  fillIndex = buildFillIndex(view, trades);
}

function currentEvaluations() {
  return evaluationsFor(selectedScenario(), state.payload?.evaluations ?? []);
}

function renderDrawerNow() {
  const evaluations = currentEvaluations();
  renderDrawer(drawer, {
    scenario: selectedScenario(),
    evaluations,
    selectedEvaluation: evaluations.find((evaluation) => evaluation.id === state.evaluationId) ?? null,
    trades: state.payload?.trades ?? [],
  }, { onEvaluationChange, onExpand });
}

function applyScenario(scroll) {
  const scenario = selectedScenario();
  if (scenario) drawScenario(view, scenario);
  else clearScenario(view);
  refreshMarkers();
  const evaluations = currentEvaluations();
  if (!evaluations.some((evaluation) => evaluation.id === state.evaluationId)) {
    state.evaluationId = evaluations.length ? evaluations[evaluations.length - 1].id : null;
  }
  renderDrawerNow();
  if (!scroll) return;
  if (scenario) scrollToScenario(view, scenario);
  else fitAll(view);
}

function applyOverlays() {
  const payload = state.payload;
  syncToggle(nodes.vwapToggle, state.overlays.vwap, hasOverlayKind(view, "vwap"), "No VWAP series for this day");
  syncToggle(nodes.emaToggle, state.overlays.ema, hasOverlayKind(view, "ema"), "No EMA series for this day");
  syncToggle(nodes.levelsToggle, state.overlays.levels, payload.key_levels.length > 0, "No key levels for this day");
  setOverlayVisibility(view, { vwap: state.overlays.vwap, ema: state.overlays.ema });
  setKeyLevels(view, payload.key_levels, state.overlays.levels);
}

function applySubChart() {
  const oscillators = state.payload.indicators.oscillators;
  const available = Object.keys(oscillators).length > 0;
  syncToggle(nodes.subHiddenToggle, state.subHidden, available, "No indicator series for this day");
  nodes.subSelect.disabled = !available || state.subHidden;
  if (state.subHidden || !available || !state.subKey) hideOscillator(sub);
  else showOscillator(sub, state.subKey, oscillators[state.subKey]);
}

function applyPayload(payload, keepView) {
  const range = keepView ? saveRange(view) : null;
  state.payload = payload;
  state.date = payload.date;
  if (!payload.scenarios.some((scenario) => scenario.id === state.scenarioId)) {
    state.scenarioId = "";
    state.evaluationId = null;
  }
  setBars(view, payload.bars);
  setOverlays(view, payload.indicators.overlays);
  state.subKey = defaultOscillatorKey(payload.indicators.oscillators, state.subKey);
  renderScenarioOptions(nodes.scenarioSelect, payload.scenarios, state.scenarioId);
  renderSubChartOptions(nodes.subSelect, payload.indicators.oscillators, state.subKey);
  syncReload(nodes.reloadButton, payload);
  applyOverlays();
  applySubChart();
  renderWarnings(payload.warnings);
  nodes.chartEmpty.hidden = payload.bars.length > 0;
  nodes.chartEmpty.textContent = `No bars to show for ${payload.date}.`;
  applyScenario(!keepView);
  if (range) restoreRange(view, range);
}

async function loadDay(date, refresh = false) {
  const token = ++state.loadToken;
  setLoading(refresh ? `Reloading ${date}` : `Loading ${date}`);
  try {
    const payload = await fetchDay(date, refresh);
    if (token !== state.loadToken) return;
    hideError();
    applyPayload(payload, refresh);
  } catch (error) {
    if (token !== state.loadToken) return;
    showError(`Could not load ${date}. ${error.message}`);
    if (!refresh) applyPayload(emptyPayload(date), false);
  } finally {
    if (token === state.loadToken) setLoading("");
  }
}

async function loadDays() {
  setLoading("Loading days");
  try {
    const days = await fetchDays();
    renderDayOptions(nodes.daySelect, days, days[0]?.date);
    if (days.length === 0) {
      applyPayload(emptyPayload("any day"), false);
      showError("No trading days found in the tick logs.");
      setLoading("");
      return;
    }
    await loadDay(days[0].date);
  } catch (error) {
    showError(`Could not load the day list. ${error.message}`);
    applyPayload(emptyPayload("any day"), false);
    setLoading("");
  }
}

function onEvaluationChange(evaluationId) {
  state.evaluationId = evaluationId;
  renderDrawerNow();
}

function onExpand() {
  const scenario = selectedScenario();
  const evaluation = currentEvaluations().find((item) => item.id === state.evaluationId);
  if (!scenario || !evaluation) return;
  const range = saveRange(view);
  openExpandView(scenario, evaluation, () => restoreRange(view, range));
}

function toggleOverlay(button, key) {
  state.overlays = { ...state.overlays, [key]: !isPressed(button) };
  applyOverlays();
}

function applyTheme(name) {
  setThemeName(name);
  nodes.themeButton.textContent = name === "dark" ? "Light" : "Dark";
  if (!view || !state.payload) return;
  const range = saveRange(view);
  applyChartTheme(view, readTheme());
  applyOverlays();
  applySubChart();
  applyScenario(false);
  restoreRange(view, range);
}

function bindToolbar() {
  nodes.daySelect.addEventListener("change", () => loadDay(nodes.daySelect.value));
  nodes.scenarioSelect.addEventListener("change", () => {
    state.scenarioId = nodes.scenarioSelect.value;
    state.evaluationId = null;
    applyScenario(true);
  });
  nodes.vwapToggle.addEventListener("click", () => toggleOverlay(nodes.vwapToggle, "vwap"));
  nodes.emaToggle.addEventListener("click", () => toggleOverlay(nodes.emaToggle, "ema"));
  nodes.levelsToggle.addEventListener("click", () => toggleOverlay(nodes.levelsToggle, "levels"));
  nodes.subSelect.addEventListener("change", () => {
    state.subKey = nodes.subSelect.value;
    applySubChart();
  });
  nodes.subHiddenToggle.addEventListener("click", () => {
    state.subHidden = !state.subHidden;
    setPressed(nodes.subHiddenToggle, state.subHidden);
    applySubChart();
  });
  nodes.reloadButton.addEventListener("click", () => state.date && loadDay(state.date, true));
  nodes.themeButton.addEventListener("click", () => {
    applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
  });
}

function bindChrome() {
  byId("error-close").addEventListener("click", hideError);
  byId("warning-close").addEventListener("click", () => { nodes.warningBanner.hidden = true; });
  byId("drawer-tab").addEventListener("click", () => setDrawerOpen(drawer, !drawer.open));
  const observer = new ResizeObserver(() => requestAnimationFrame(() => positionLegend(sub)));
  observer.observe(byId("chart"));
}

function init() {
  if (!window.LightweightCharts) {
    showError("The chart library failed to load from vendor/.");
    return;
  }
  applyTheme(initialThemeName());
  view = createChartView(byId("chart"), byId("readout"), readTheme());
  sub = createSubChart(view, byId("sub-legend"));
  createFillTooltip(view, byId("fill-tooltip"), () => fillIndex);
  drawer = createDrawer(byId("drawer"), byId("drawer-tab"), byId("drawer-panel"));
  setDrawerOpen(drawer, false);
  bindToolbar();
  bindChrome();
  loadDays();
}

init();
