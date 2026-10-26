// DEVELOPED BY CARROTSTUDIO software house
// Golden rule: what users type goes into the page only as text (textContent),
// never as HTML. That way nobody can inject code.
import { lang, t } from "/i18n.js";

export const CATEGORIES = [
  "water", "food", "medicine", "power", "shelter", "transport", "help", "info", "other",
];

export const categoryLabel = (category) => t(`cat.${category}`);
export const kindLabel = (kind) => t(`kind.${kind}`);

// What this phone published, so it can close it with one tap. Stays on the phone.
const MINE_KEY = "campanile-mine-v1";
const MAX_MINE = 30;
const CODE_FORMAT = /^[A-Z2-9]{4}-[A-Z2-9]{4}$/;

function validEntry(e) {
  return e && Number.isInteger(e.id) && e.id > 0 && typeof e.code === "string"
    && CODE_FORMAT.test(e.code) && typeof e.label === "string" && Number.isFinite(e.created);
}

export function loadMine(kind) {
  try {
    const all = JSON.parse(localStorage.getItem(MINE_KEY)) || {};
    return (Array.isArray(all[kind]) ? all[kind] : []).filter(validEntry);
  } catch {
    return [];
  }
}

export function saveMine(kind, entries) {
  try {
    const all = JSON.parse(localStorage.getItem(MINE_KEY) || "{}") || {};
    all[kind] = entries.filter(validEntry).slice(-MAX_MINE);
    localStorage.setItem(MINE_KEY, JSON.stringify(all));
  } catch {
    // no storage (private mode, captive-portal window): the printed code still works
  }
}

// A Raspberry has no clock battery and may restart offline days behind. Phones usually know the
// time, so times are shown on the phone's clock, using the offset from each Date header.
const CLOCK_TOLERANCE = 120_000; // below this it's network delay and rounding, not a wrong clock
let clockOffset = 0;

function learnClock(response) {
  const campanile = Date.parse(response.headers.get("Date") || "");
  if (!Number.isFinite(campanile)) return;
  const difference = Date.now() - campanile;
  clockOffset = Math.abs(difference) > CLOCK_TOLERANCE ? difference : 0;
}

export async function api(path, data) {
  // The server answers errors in the language chosen here, not only the phone's.
  const options = data === undefined
    ? { method: "GET", headers: { "Accept-Language": lang } }
    : {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept-Language": lang },
        body: JSON.stringify(data),
      };
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new Error(t("offline"));
  }
  learnClock(response);
  let body = {};
  try {
    body = await response.json();
  } catch {
    // some responses have no body
  }
  if (!response.ok) {
    const error = new Error(body.error || t("error.status", { status: response.status }));
    error.status = response.status;
    throw error;
  }
  return body;
}

// Builds an element without ever going through innerHTML.
export function el(tag, attributes = {}, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) {
    if (name === "text") node.textContent = value;
    else if (name === "class") node.className = value;
    else node.setAttribute(name, value);
  }
  for (const child of children) {
    if (child !== null && child !== undefined) {
      node.append(child instanceof Node ? child : String(child));
    }
  }
  return node;
}

// A time written by the Campanile, shown on the phone's clock.
export function when(seconds) {
  return realTime(seconds * 1000 + clockOffset);
}

// A time that is already real, such as a signed notice's expiry set by the authority.
export function realTime(ms) {
  return new Date(ms).toLocaleString(lang, {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

export function showResult(node, message, isError = false) {
  node.textContent = message;
  node.classList.toggle("error", isError);
}

const decimal = new Intl.NumberFormat(lang, { maximumFractionDigits: 1 }); // "1,6" in Italian

export function fileSize(bytes) {
  if (bytes >= 1e9) return `${decimal.format(bytes / 1e9)} GB`;
  if (bytes >= 1e6) return Math.round(bytes / 1e6) + " MB";
  return Math.max(1, Math.round(bytes / 1e3)) + " kB";
}

// One item of yours shows whole; several fold behind one line that stays in sight, so they
// are neither a wall nor forgotten. The line stays open across the page's own refreshes.
export function fold(container, cards, summary) {
  const wasOpen = container.querySelector(":scope > details.many")?.open;
  if (cards.length <= 1) {
    container.replaceChildren(...cards);
    return;
  }
  const box = el("details", { class: "many" }, el("summary", { text: summary }), ...cards);
  box.open = Boolean(wasOpen);
  container.replaceChildren(box);
}

// Closes one of this phone's posts or names, and forgets it.
export async function closeMine(kind, path, entry) {
  try {
    await api(path, { id: entry.id, code: entry.code });
  } catch (error) {
    if (error.status !== 404) throw error;  // 404: already closed, e.g. by the admin
  }
  saveMine(kind, loadMine(kind).filter((e) => e.id !== entry.id));
}

// Draws this phone's own posts or names, each with a one-tap button to close it.
export function showMine({ kind, path, button, onChange }) {
  const section = document.getElementById("mine-section");
  const list = document.getElementById("mine");
  const entries = loadMine(kind);
  section.classList.toggle("hidden", entries.length === 0);
  fold(list, entries.slice().reverse().map((entry) => {
    const action = el("button", { type: "button", class: "secondary", text: t(button) });
    const result = el("p", { class: "result" });
    action.addEventListener("click", async () => {
      action.disabled = true;
      try {
        await closeMine(kind, path, entry);
      } catch (error) {
        showResult(result, error.message, true);
        action.disabled = false;
        return;
      }
      showMine({ kind, path, button, onChange });
      if (onChange) onChange();
    });
    return el("article", { class: "post" },
      el("p", { text: entry.label }),
      el("div", { class: "meta", text: `N. ${entry.id} · ${when(entry.created)}` }),
      action, result);
  }), t(`${kind}.many`, { n: entries.length }));
}

export function rememberMine(kind, response, label) {
  saveMine(kind, [...loadMine(kind), {
    id: response.id, code: response.code, label: label.slice(0, 120),
    created: Math.floor(Date.now() / 1000),
  }]);
}
