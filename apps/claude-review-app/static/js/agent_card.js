import { el } from "./dom.js";
import { formatLatency, humanize } from "./format.js";

const KNOWN_DECISIONS = new Set(["enter_now", "wait", "pass", "unparsed"]);
export const LEG_ORDER = ["opus", "astra"];
const LEG_NAMES = { opus: "Opus", astra: "Astra" };

export function legName(key) {
  return LEG_NAMES[key] ?? key;
}

export function decisionClass(decision) {
  const value = String(decision ?? "").toLowerCase();
  return KNOWN_DECISIONS.has(value) ? `decision-${value.replace("_", "-")}` : "decision-other";
}

export function decisionBadge(decision) {
  return el("span", {
    className: `badge ${decisionClass(decision)}`,
    text: humanize(decision || "none"),
  });
}

export function legKeys(evaluation) {
  const keys = Object.keys(evaluation?.legs ?? {});
  const ordered = LEG_ORDER.filter((key) => keys.includes(key));
  return [...ordered, ...keys.filter((key) => !LEG_ORDER.includes(key))];
}

function section(title, content) {
  return el("section", { className: "card-section" }, [
    el("h4", { className: "card-section-title", text: title }),
    content,
  ]);
}

function textSection(title, text) {
  if (!text) return null;
  return section(title, el("p", { className: "card-text", text }));
}

function factorsSection(factors) {
  if (!Array.isArray(factors) || factors.length === 0) return null;
  const list = el("ul", { className: "card-list" }, factors.map((factor) => el("li", { text: factor })));
  return section("Key factors", list);
}

function rawSection(raw) {
  if (!raw) return null;
  return el("details", { className: "card-raw" }, [
    el("summary", { text: "Raw response" }),
    el("pre", { className: "raw-pre", text: raw }),
  ]);
}

function cardHeader(key, leg) {
  const meta = leg
    ? [
      el("span", { className: "card-model", text: leg.model || "model not recorded" }),
      el("span", { className: "card-latency num", text: formatLatency(leg.latency_ms) }),
    ]
    : [];
  return el("header", { className: "card-header" }, [
    el("div", { className: "card-title-row" }, [
      el("h3", { className: "card-title", text: legName(key) }),
      leg ? decisionBadge(leg.decision) : el("span", { className: "badge decision-missing", text: "no response" }),
    ]),
    el("div", { className: "card-meta" }, meta),
  ]);
}

export function agentCard(key, leg) {
  const tone = leg ? decisionClass(leg.decision) : "decision-missing";
  const card = el("article", { className: `agent-card ${tone}`, attrs: { "aria-label": `${legName(key)} response` } });
  card.append(cardHeader(key, leg));
  if (!leg) {
    card.append(el("p", { className: "card-empty", text: "No response recorded" }));
    return card;
  }
  const body = [
    section("Reasoning", el("p", { className: "card-text", text: leg.reasoning || "No reasoning text in the response." })),
    factorsSection(leg.key_factors),
    textSection("Case for", leg.case_for),
    textSection("Case against", leg.case_against),
    textSection("Verdict", leg.verdict),
    textSection("Wait for", leg.wait_for),
    rawSection(leg.raw_response),
  ];
  body.forEach((node) => node && card.append(node));
  return card;
}

// One segment per leg, then the consensus badge: shows at a glance why a call was a wait.
export function voteStrip(evaluation) {
  const segments = legKeys(evaluation).map((key) => {
    const leg = evaluation.legs[key];
    const decision = leg ? leg.decision : null;
    return el("span", {
      className: `vote-segment ${leg ? decisionClass(decision) : "decision-missing"}`,
      title: `${legName(key)}: ${leg ? humanize(decision) : "no response"}`,
    }, [
      el("span", { className: "vote-name", text: legName(key) }),
      el("span", { className: "vote-decision", text: leg ? humanize(decision) : "none" }),
    ]);
  });
  return el("div", { className: "vote-strip" }, [
    el("div", { className: "vote-legs" }, segments),
    el("div", { className: "vote-result" }, [
      el("span", { className: "vote-result-label", text: "Consensus" }),
      decisionBadge(evaluation.decision),
    ]),
  ]);
}

export function linkQualityNote(evaluation) {
  const quality = evaluation.link_quality || "unknown";
  if (quality === "exact") return null;
  return el("div", { className: "link-note", attrs: { role: "note" } }, [
    el("span", { className: "link-quality", text: `Link: ${humanize(quality)}` }),
    evaluation.note ? el("span", { className: "link-text", text: evaluation.note }) : null,
  ]);
}
