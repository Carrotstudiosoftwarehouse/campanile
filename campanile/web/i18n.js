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

// The number to call in danger, inside sentences marked data-emergency: the Campanile's own,
// 112 until it says. data-emergency may name a sentence for any number but 112.
let emergency = "112";

function fillEmergency(node) {
  const key = (emergency !== "112" && node.dataset.emergency) || node.dataset.i18n;
  node.textContent = t(key, { n: emergency });
}

export function showEmergency(number) {
  if (typeof number === "string" && /^[0-9]{2,6}$/.test(number)) emergency = number;
  for (const node of document.querySelectorAll("[data-emergency]")) fillEmergency(node);
}

export function t(key, params = {}) {
  const text = STRINGS[lang][key] ?? STRINGS.it[key] ?? key;
  return text.replace(/\{(\w+)\}/g, (_, name) => String(params[name] ?? ""));
}

// Distances as the phone's country measures them: feet and miles in the few that use them.
const MILES = ["US", "LR", "MM"];
const FOOT = 0.3048; // metres
const MILE = 1609.344;
const decimal = new Intl.NumberFormat(lang, { maximumFractionDigits: 1 });
const phone = (navigator.languages || [])[0] || navigator.language || ""; // like "en-US"
const country = /^[a-z]{2,3}(?:-[a-z]{4})?-([a-z]{2})\b/i.exec(phone)?.[1].toUpperCase();
const miles = MILES.includes(country);

export function distance(metres) {
  if (miles) {
    return metres < MILE / 10
      ? t("search.feet", { n: Math.max(50, Math.round(metres / FOOT / 50) * 50) })
      : t("search.miles", { n: decimal.format(metres / MILE) });
  }
  return metres < 1000
    ? t("search.meters", { n: Math.max(10, Math.round(metres / 10) * 10) })
    : t("search.km", { n: decimal.format(metres / 1000) });
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
  for (const node of document.querySelectorAll("[data-i18n]")) {
    if ("emergency" in node.dataset) fillEmergency(node);
    else node.textContent = t(node.dataset.i18n);
  }
  for (const node of document.querySelectorAll("[data-i18n-ph]")) node.placeholder = t(node.dataset.i18nPh);
  for (const node of document.querySelectorAll("[data-i18n-aria]")) {
    node.setAttribute("aria-label", t(node.dataset.i18nAria));
  }
}
