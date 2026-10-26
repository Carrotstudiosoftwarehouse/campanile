// DEVELOPED BY CARROTSTUDIO software house
import { api, el, realTime, when } from "/common.js";
import { t, tn, translatePage } from "/i18n.js";

translatePage();

// An urgent notice must reach people even if they never reload the page.
const REFRESH_INTERVAL = 30_000;

function noticeLabel(n) {
  const kind = t(n.urgent ? "notice.urgent" : "notice");
  if (n.signer) return t("notice.signed", { kind, signer: n.signer });
  return n.source ? t("notice.cap", { kind, source: n.source }) : kind;
}

async function showNotices() {
  const { notices } = await api("/api/notices");
  const list = document.getElementById("notices");
  if (notices.length === 0) {
    list.replaceChildren(el("p", { class: "meta", text: t("notices.none") }));
  } else {
    list.replaceChildren(...notices.map((n) =>
      el("article", { class: n.urgent ? "notice urgent" : "notice" },
        el("div", { class: "tag", text: noticeLabel(n) }),
        el("h3", { text: n.title }),
        el("p", { text: n.text }),
        el("div", { class: "meta", text: n.expires
          ? `${when(n.created)} · ${t("notice.until", { when: realTime(n.expires * 1000) })}`
          : when(n.created) }))));
  }
}

async function showStatus() {
  const status = await api("/api/status");
  document.getElementById("version").textContent = "v" + status.version;
  document.getElementById("people-count").textContent = tn("people", status.registered_people);

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
