// DEVELOPED BY CARROTSTUDIO software house
import { api, el, realTime, when } from "/common.js";
import { showEmergency, t, translatePage } from "/i18n.js";

translatePage();

// An urgent notice must reach people even if they never reload the page.
const REFRESH_INTERVAL = 30_000;

function noticeLabel(n) {
  const kind = t(n.urgent ? "notice.urgent" : "notice");
  if (n.signer) return t("notice.signed", { kind, signer: n.signer });
  return n.source ? t("notice.cap", { kind, source: n.source }) : kind;
}

function noticeCard(n) {
  return el("article", { class: n.urgent ? "notice urgent" : "notice" },
    el("div", { class: "tag", text: noticeLabel(n) }),
    el("h3", { text: n.title }),
    el("p", { text: n.text }),
    el("div", { class: "meta", text: n.expires
      ? `${when(n.created)} · ${t("notice.until", { when: realTime(n.expires * 1000) })}`
      : when(n.created) }));
}

// One notice in view, the first the Campanile sends (urgent ones first, then the newest), and
// the rest behind a button: "I need" and "I can give" stay within reach of a thumb.
const allButton = document.getElementById("all-notices");
let notices = [];
let showAll = false;

function drawNotices() {
  const list = document.getElementById("notices");
  if (notices.length === 0) {
    list.replaceChildren(el("p", { class: "meta", text: t("notices.none") }));
  } else {
    list.replaceChildren(...(showAll ? notices : notices.slice(0, 1)).map(noticeCard));
  }
  allButton.classList.toggle("hidden", notices.length < 2);
  allButton.setAttribute("aria-expanded", String(showAll));
  allButton.textContent = showAll ? t("notices.fewer") : t("notices.all", { n: notices.length });
}

allButton.addEventListener("click", () => {
  showAll = !showAll;
  drawNotices();
  if (!showAll) allButton.scrollIntoView({ block: "nearest" }); // the list shrank above it
});

async function showNotices() {
  ({ notices } = await api("/api/notices"));
  drawNotices();
}

async function showStatus() {
  const status = await api("/api/status");
  showEmergency(status.emergency);
  document.getElementById("version").textContent = "v" + status.version;

  const hasMaps = status.maps.length > 0;
  document.getElementById("map-card").classList.toggle("off", !hasMaps);
  document.getElementById("map-text").textContent = t(hasMaps ? "home.map.sub" : "home.map.none");

  const card = document.getElementById("wiki-card");
  const text = document.getElementById("wiki-text");
  card.classList.toggle("off", !status.kiwix);
  if (status.kiwix) {
    // Kiwix runs on the same machine, on another port.
    card.href = status.kiwix_url || `${location.protocol}//${location.hostname}:${status.kiwix_port}/`;
    text.textContent = t("home.wiki.on");
  } else {
    card.removeAttribute("href");
    text.textContent = t("home.wiki.off");
  }
}

let lastUpdate = null;

function clock(date) {
  return date.toLocaleTimeString(document.documentElement.lang, { hour: "2-digit", minute: "2-digit" });
}

// In an emergency, stale information shown as current is dangerous: say when a refresh fails.
async function refresh() {
  const results = await Promise.allSettled([showNotices(), showStatus()]);
  const failed = results.find((r) => r.status === "rejected");
  const stale = document.getElementById("stale");
  if (failed) {
    stale.textContent = lastUpdate
      ? `${t("stale.since", { time: clock(lastUpdate) })} ${failed.reason.message}`
      : failed.reason.message;
    stale.classList.remove("hidden");
    return;
  }
  lastUpdate = new Date();
  stale.classList.add("hidden");
  document.getElementById("updated").textContent = t("updated", { time: clock(lastUpdate) });
}

refresh();
setInterval(refresh, REFRESH_INTERVAL);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") refresh();
});
