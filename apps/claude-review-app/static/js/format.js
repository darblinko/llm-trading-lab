// Chart times are ET wall-clock seconds encoded as UTC, so UTC getters yield ET.

export const BAR_SECONDS = 180;

export function barTimeOf(chartSeconds) {
  return Math.floor(chartSeconds / BAR_SECONDS) * BAR_SECONDS;
}

export function clockTime(chartSeconds, withSeconds = false) {
  if (!Number.isFinite(chartSeconds)) return "n/a";
  const iso = new Date(chartSeconds * 1000).toISOString();
  return withSeconds ? iso.slice(11, 19) : iso.slice(11, 16);
}

export function formatPrice(value, digits = 2) {
  return Number.isFinite(value) ? value.toFixed(digits) : "n/a";
}

export function formatSigned(value, digits = 2) {
  if (!Number.isFinite(value)) return "n/a";
  const sign = value > 0 ? "+" : "";
  return sign + value.toFixed(digits);
}

export function formatMoney(value) {
  if (!Number.isFinite(value)) return "n/a";
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  const amount = Math.abs(value).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${sign}$${amount}`;
}

export function formatVolume(value) {
  if (!Number.isFinite(value)) return "n/a";
  if (value >= 1e6) return (value / 1e6).toFixed(2) + "M";
  if (value >= 1e3) return (value / 1e3).toFixed(1) + "K";
  return String(Math.round(value));
}

export function formatLatency(milliseconds) {
  return Number.isFinite(milliseconds) ? (milliseconds / 1000).toFixed(1) + " s" : "n/a";
}

export function humanize(identifier) {
  if (identifier === null || identifier === undefined || identifier === "") return "n/a";
  return String(identifier).replace(/_/g, " ");
}

export function capitalize(text) {
  const value = String(text ?? "");
  return value.charAt(0).toUpperCase() + value.slice(1);
}
