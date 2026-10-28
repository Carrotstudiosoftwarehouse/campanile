// DEVELOPED BY CARROTSTUDIO software house
// Pages are written in Italian. In another language, every element marked data-i18n gets
// its text replaced from strings.js: always as text (textContent), never as HTML.
import { STRINGS } from "/strings.js";

const AVAILABLE = Object.keys(STRINGS);
const FALLBACK = "en"; // a phone in a language we don't have yet understands English more often
const CHOICE_KEY = "campanile-lang";
// Written right to left: their pages are mirrored.
const RTL = ["ar", "fa", "he", "ur"];

function detect() {
  try {
    const chosen = localStorage.getItem(CHOICE_KEY);
    if (AVAILABLE.includes(chosen)) return chosen;
  } catch {
    // no storage: follow the phone
  }
  for (const tag of navigator.languages || [navigator.language || ""]) {
    const code = String(tag).slice(0, 2).toLowerCase();
    if (AVAILABLE.includes(code)) return code;
  }
  return FALLBACK;
}

export const lang = detect();

export function t(key, params = {}) {
  const text = STRINGS[lang][key] ?? STRINGS.it[key] ?? key;
  return text.replace(/\{(\w+)\}/g, (_, name) => String(params[name] ?? ""));
}

export function has(key) {
  return Object.hasOwn(STRINGS[lang], key) || Object.hasOwn(STRINGS.it, key);
}

// t() for countable things: picks "key_one" or "key_other".
export function tn(key, n, params = {}) {
  return t(`${key}_${n === 1 ? "one" : "other"}`, { n, ...params });
}

function switcher() {
  const nav = document.getElementById("lang-switch");
  if (!nav) return;
  nav.setAttribute("aria-label", t("lang.label"));
  const names = { it: "Italiano", en: "English" };
  nav.replaceChildren(...AVAILABLE.map((code) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "link";
    button.textContent = names[code] || code;
    button.disabled = code === lang;
    button.addEventListener("click", () => {
      try { localStorage.setItem(CHOICE_KEY, code); } catch { /* no storage: choice not kept */ }
      location.reload();
    });
    return button;
  }));
}

export function translatePage() {
  document.documentElement.lang = lang;
  document.documentElement.dir = RTL.includes(lang) ? "rtl" : "ltr";
  switcher();
  const page = document.querySelector("title[data-i18n-title]");
  if (page) document.title = `${t(page.dataset.i18nTitle)} · Campanile`;
  if (lang === "it") return;
  for (const node of document.querySelectorAll("[data-i18n]")) node.textContent = t(node.dataset.i18n);
  for (const node of document.querySelectorAll("[data-i18n-ph]")) node.placeholder = t(node.dataset.i18nPh);
  for (const node of document.querySelectorAll("[data-i18n-aria]")) {
    node.setAttribute("aria-label", t(node.dataset.i18nAria));
  }
}
