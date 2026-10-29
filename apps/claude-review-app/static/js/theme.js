import { cssVar, safeStorageGet, safeStorageSet } from "./dom.js";

const THEME_KEY = "claude-review-theme";

export function initialThemeName() {
  const stored = safeStorageGet(THEME_KEY);
  return stored === "light" || stored === "dark" ? stored : "dark";
}

export function setThemeName(name) {
  document.documentElement.dataset.theme = name;
  safeStorageSet(THEME_KEY, name);
}

// Chart canvases cannot read CSS, so the palette is copied from custom properties.
export function readTheme() {
  return {
    background: cssVar("--chart-bg"),
    text: cssVar("--muted"),
    strongText: cssVar("--text"),
    grid: cssVar("--grid"),
    line: cssVar("--line"),
    crosshair: cssVar("--faint"),
    up: cssVar("--up"),
    down: cssVar("--down"),
    call: cssVar("--call"),
    put: cssVar("--put"),
    callSoft: cssVar("--call-soft"),
    putSoft: cssVar("--put-soft"),
    callZone: cssVar("--call-zone"),
    putZone: cssVar("--put-zone"),
    wait: cssVar("--wait"),
    pass: cssVar("--pass"),
    invalid: cssVar("--invalid"),
    accent: cssVar("--accent"),
    faint: cssVar("--faint"),
    vwap: cssVar("--vwap"),
    ema9: cssVar("--ema9"),
    ema21: cssVar("--ema21"),
    oscillatorLines: [cssVar("--osc-1"), cssVar("--osc-2"), cssVar("--osc-3")],
    oscillatorLevel: cssVar("--osc-level"),
    histogramNeutral: cssVar("--hist-neutral"),
    histogramUp: cssVar("--hist-up"),
    histogramDown: cssVar("--hist-down"),
    levelGroups: {
      prior_day: cssVar("--level-prev"),
      overnight: cssVar("--level-overnight"),
      camarilla: cssVar("--level-camarilla"),
      opening_range: cssVar("--level-or"),
    },
    levelDefault: cssVar("--level-default"),
  };
}

export function directionColor(theme, direction) {
  return direction === "put" ? theme.put : theme.call;
}
