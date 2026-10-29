const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

async function getJson(url) {
  let response;
  try {
    response = await fetch(url, { cache: "no-store" });
  } catch (error) {
    throw new Error(`Network error loading ${url}: ${error.message}`);
  }
  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok) {
    const detail = body && typeof body.error === "string" ? body.error : `HTTP ${response.status}`;
    throw new Error(`${url}: ${detail}`);
  }
  if (body === null || typeof body !== "object") {
    throw new Error(`${url}: response is not a JSON object`);
  }
  return body;
}

export async function fetchDays() {
  const body = await getJson("/api/days");
  if (!Array.isArray(body.days)) throw new Error("/api/days: missing days list");
  return body.days.filter((day) => day && DATE_PATTERN.test(String(day.date)));
}

export async function fetchDay(date, refresh = false) {
  if (!DATE_PATTERN.test(date)) throw new Error(`Invalid date: ${date}`);
  const query = refresh ? "?refresh=1" : "";
  const payload = await getJson(`/api/day/${date}${query}`);
  return normalizePayload(payload, date);
}

function normalizePayload(payload, date) {
  const indicators = payload.indicators ?? {};
  return {
    date: payload.date ?? date,
    is_today: payload.is_today === true,
    warnings: arrayOr(payload.warnings),
    bars: arrayOr(payload.bars),
    indicators: {
      overlays: indicators.overlays ?? {},
      oscillators: indicators.oscillators ?? {},
    },
    key_levels: arrayOr(payload.key_levels),
    scenarios: arrayOr(payload.scenarios),
    evaluations: arrayOr(payload.evaluations),
    trades: arrayOr(payload.trades),
  };
}

function arrayOr(value) {
  return Array.isArray(value) ? value : [];
}
