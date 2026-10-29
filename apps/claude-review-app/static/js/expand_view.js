import { el } from "./dom.js";
import { clockTime } from "./format.js";
import { agentCard, legKeys, linkQualityNote, voteStrip } from "./agent_card.js";

// Full-screen comparison of both legs. Returns a close function.
export function openExpandView(scenario, evaluation, onClosed) {
  const previousFocus = document.activeElement;
  const closeButton = el("button", { className: "button", text: "Close", attrs: { type: "button" } });
  const title = `${scenario.label || "Scenario"} at ${clockTime(evaluation.time, true)}`;
  const overlay = el("div", {
    className: "expand-overlay",
    attrs: { role: "dialog", "aria-modal": "true", "aria-label": `Agent comparison: ${title}` },
  }, [
    el("header", { className: "expand-header" }, [
      el("div", { className: "expand-heading" }, [
        el("h2", { className: "expand-title", text: title }),
        voteStrip(evaluation),
      ]),
      closeButton,
    ]),
    linkQualityNote(evaluation),
    el("p", { className: "consensus-text expand-consensus", text: evaluation.consensus_reasoning || "" }),
    el("div", { className: "expand-cards" }, legKeys(evaluation).map((key) => agentCard(key, evaluation.legs[key]))),
  ]);

  const close = () => {
    document.removeEventListener("keydown", onKeyDown, true);
    overlay.remove();
    document.body.classList.remove("has-overlay");
    if (previousFocus && typeof previousFocus.focus === "function") previousFocus.focus();
    onClosed();
  };
  const onKeyDown = (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      close();
    }
  };

  closeButton.addEventListener("click", close);
  document.addEventListener("keydown", onKeyDown, true);
  document.body.classList.add("has-overlay");
  document.body.append(overlay);
  closeButton.focus();
  return close;
}
