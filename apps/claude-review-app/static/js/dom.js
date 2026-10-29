// DOM helpers. All log-derived text goes through textContent, never innerHTML.

export function el(tag, options = {}, children = []) {
  const node = document.createElement(tag);
  if (options.className) node.className = options.className;
  if (options.text !== undefined && options.text !== null) node.textContent = String(options.text);
  if (options.title) node.title = String(options.title);
  for (const [name, value] of Object.entries(options.attrs ?? {})) {
    node.setAttribute(name, String(value));
  }
  for (const [name, value] of Object.entries(options.dataset ?? {})) {
    node.dataset[name] = String(value);
  }
  for (const child of children) {
    if (child !== null && child !== undefined && child !== false) node.append(child);
  }
  return node;
}

export function byId(id) {
  const node = document.getElementById(id);
  if (!node) throw new Error(`Missing element #${id}`);
  return node;
}

export function setPressed(button, pressed) {
  button.setAttribute("aria-pressed", pressed ? "true" : "false");
}

export function isPressed(button) {
  return button.getAttribute("aria-pressed") === "true";
}

export function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function safeStorageGet(key) {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function safeStorageSet(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Storage is a convenience only; the page works without it.
  }
}
