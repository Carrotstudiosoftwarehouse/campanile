// DEVELOPED BY CARROTSTUDIO software house
import { api, el, when, realTime, showResult, categoryLabel, kindLabel, fileSize } from "/common.js";
import { lang, t, tn, translatePage } from "/i18n.js";
import { maplibregl, readHeader, registerPmtiles, style } from "/mapstyle.js";
import { routable } from "/route.js";

translatePage();

// The password lives only in memory, while the page is open.
let password = "";
const loginResult = document.getElementById("login-result");

function item(table, id, ...lines) {
  const button = el("button", { type: "button", class: "secondary", text: t("admin.delete") });
  const card = el("article", { class: "post" }, ...lines, button);
  button.addEventListener("click", async () => {
    if (!confirm(t("admin.delete.confirm"))) return;
    try {
      await api("/api/admin/delete", { password, table, id });
      card.remove();
    } catch (error) {
      alert(error.message);
    }
  });
  return card;
}

// Shown to the admin as "Device a3f9": enough to group one phone's posts.
const deviceLabel = (tag) => (tag ? t("admin.device", { tag: tag.slice(0, 4) }) : "");

function bulkButton(label, path, device, result) {
  const button = el("button", { type: "button", class: "secondary", text: label });
  button.addEventListener("click", async () => {
    if (!confirm(t("confirm", { action: label }))) return;
    try {
      const r = await api(path, { password, device });
      showResult(document.getElementById("bulk-result"), result(r));
      await load();
    } catch (error) {
      alert(error.message);
    }
  });
  return button;
}

function fill(id, items) {
  const container = document.getElementById(id);
  if (items.length) container.replaceChildren(...items);
  else container.replaceChildren(el("p", { class: "meta", text: t("admin.none") }));
}

async function load() {
  const [data, { notices }] = await Promise.all([
    api("/api/admin/list", { password }),
    api("/api/notices"),
  ]);
  fill("notices", notices.map((n) =>
    item("notice", n.id,
      el("div", { class: "meta", text: [
        n.urgent ? t("admin.urgent") : "",
        n.signer ? t("admin.signedby", { signer: n.signer }) : "",
        n.source ? t("admin.capfrom", { source: n.source }) : "",
        when(n.created),
      ].filter(Boolean).join(" · ") }),
      el("strong", { text: n.title }),
      el("p", { text: n.text }))));
  fill("pending", data.pending.map((p) => {
    const card = item("post", p.id,
      el("div", { class: "meta", text:
        `N. ${p.id} · ${kindLabel(p.kind)} · ${categoryLabel(p.category)} · ${deviceLabel(p.device)}` }),
      el("p", { text: p.text }),
      el("div", { class: "meta", text: `${p.area} · ${p.contact}` }));
    const approve = el("button", { type: "button", text: t("admin.approve") });
    approve.addEventListener("click", async () => {
      try {
        await api("/api/admin/approve", { password, id: p.id });
        await load();
      } catch (error) {
        alert(error.message);
      }
    });
    card.append(" ", approve);
    return card;
  }));
  fill("posts", data.posts.map((p) =>
    item("post", p.id,
      el("div", { class: "meta", text:
        `N. ${p.id} · ${kindLabel(p.kind)} · ${categoryLabel(p.category)} · ${when(p.created)} · ${deviceLabel(p.device)}` }),
      el("p", { text: p.text }),
      el("div", { class: "meta", text: `${p.area} · ${p.contact}` }),
      p.device ? bulkButton(t("admin.closedevice"), "/api/admin/close-device",
        p.device, (r) => tn("admin.closed", r.closed)) : null)));
  fill("people", data.safe.map((p) =>
    item("safe", p.id,
      el("div", { class: "meta", text: `N. ${p.id} · ${when(p.created)}` }),
      el("strong", { text: p.name }),
      p.message ? el("p", { text: p.message }) : null,
      p.place ? el("div", { class: "meta", text: p.place }) : null,
      p.device ? bulkButton(t("admin.removedevice"), "/api/admin/remove-device-safe",
        p.device, (r) => tn("admin.removed", r.removed)) : null)));
  await loadLog();
}

// The Campanile's clock (a Raspberry restarts behind, without internet), how long posts and
// names are kept, and what the admin did.
async function loadLog() {
  const r = await api("/api/admin/log", { password });
  const off = Math.round((r.now * 1000 - Date.now()) / 60_000);
  document.getElementById("clock-now").textContent =
    t("admin.time.now", { time: realTime(r.now * 1000) });
  const warning = document.getElementById("clock-off");
  warning.textContent = t("admin.time.off", { n: Math.abs(off) });
  warning.classList.toggle("hidden", Math.abs(off) < 2);
  const days = (n) => (n ? t("admin.keep.days", { n }) : t("admin.keep.never"));
  document.getElementById("keep").textContent =
    t("admin.keep", { posts: days(r.keep.posts), safe: days(r.keep.safe) });
  fill("log", r.log.map((e) => {
    const seconds = Number.parseInt(e.detail, 10);
    const detail = e.action === "clock_set" && !Number.isNaN(seconds) ? shift(seconds) : e.detail;
    return el("div", { class: "meta", text:
      `${realTime(e.at * 1000)} · ${t(`log.${e.action}`)}${detail ? `: ${detail}` : ""}` });
  }));
}

const decimal = new Intl.NumberFormat(lang, { maximumFractionDigits: 1 });

// How far the clock was moved, in words a family reads: "+3 days", not "+259200 s".
function shift(seconds) {
  const sign = seconds < 0 ? "−" : "+";
  const s = Math.abs(seconds);
  if (s >= 86400) return `${sign}${decimal.format(s / 86400)} ${t("log.days")}`;
  if (s >= 3600) return `${sign}${decimal.format(s / 3600)} ${t("log.hours")}`;
  return `${sign}${Math.round(s / 60)} min`;
}

function localInput(date) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
    + `T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

document.getElementById("clock-input").value = localInput(new Date());
document.getElementById("clock-set").addEventListener("click", async () => {
  const result = document.getElementById("clock-result");
  const chosen = new Date(document.getElementById("clock-input").value).getTime();
  try {
    await api("/api/admin/clock", { password, now: chosen / 1000 });
    showResult(result, t("admin.time.done"));
    await loadLog();
  } catch (error) {
    showResult(result, error.message, true);
  }
});

document.getElementById("notice-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const result = document.getElementById("notice-result");
  try {
    await api("/api/admin/notices", {
      password,
      title: document.getElementById("notice-title").value,
      text: document.getElementById("notice-text").value,
      urgent: document.getElementById("notice-urgent").checked,
    });
    event.target.reset();
    showResult(result, t("admin.notice.done"));
    await load();
  } catch (error) {
    showResult(result, error.message, true);
  }
});

for (const button of document.querySelectorAll("[data-recent]")) {
  button.addEventListener("click", async () => {
    const minutes = Number(button.dataset.recent);
    if (!confirm(t("confirm", { action: button.textContent }))) return;
    try {
      const r = await api("/api/admin/close-recent", { password, minutes });
      showResult(document.getElementById("bulk-result"), tn("admin.closed", r.closed));
      await load();
    } catch (error) {
      showResult(document.getElementById("bulk-result"), error.message, true);
    }
  });
}

document.getElementById("signed-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const result = document.getElementById("signed-result");
  try {
    const { signer } = await api("/api/admin/notices/signed", {
      password,
      signed: document.getElementById("signed-text").value.trim(),
    });
    event.target.reset();
    showResult(result, t("admin.signed.done", { signer }));
    await load();
  } catch (error) {
    showResult(result, error.message, true);
  }
});

// An official alert in CAP, from a file: the server reads it and refuses what it can't trust.
document.getElementById("cap-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const result = document.getElementById("cap-result");
  try {
    const file = document.getElementById("cap-file").files[0];
    const { title, source } = await api("/api/admin/cap", { password, cap: await file.text() });
    event.target.reset();
    showResult(result, t("admin.cap.done", { title, source }));
    await load();
  } catch (error) {
    showResult(result, error.message, true);
  }
});

// The "I'm safe" names as a PFIF file, saved on this computer.
document.getElementById("pfif-export").addEventListener("click", async () => {
  const result = document.getElementById("pfif-result");
  try {
    const { pfif, count } = await api("/api/admin/pfif", { password });
    const link = el("a", {
      href: URL.createObjectURL(new Blob([pfif], { type: "application/xml" })),
      download: `campanile-sto-bene-${new Date().toISOString().slice(0, 10)}.xml`,
    });
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 60_000);  // after the download has started
    showResult(result, tn("admin.pfif.done", count));
  } catch (error) {
    showResult(result, error.message, true);
  }
});

// Blocked streets: touched on the map, avoided by every route, shown in red to everyone.
let roadMap = null;

async function loadRoads() {
  const { closed } = await api("/api/roads/closed");
  fill("roads", closed.map((road) => {
    const reopen = el("button", { type: "button", class: "secondary", text: t("admin.roads.open") });
    reopen.addEventListener("click", async () => {
      try {
        await api("/api/admin/roads/open", { password, id: road.id });
        await loadRoads();
      } catch (error) {
        alert(error.message);
      }
    });
    return el("article", { class: "post" },
      el("div", { class: "meta", text: when(road.created) }),
      el("strong", { text: road.name || t("admin.roads.unnamed") }),
      road.note ? el("p", { text: road.note }) : null,
      reopen);
  }));
  const data = {
    type: "FeatureCollection",
    features: closed.flatMap((road) => road.lines.map((coordinates) => ({
      type: "Feature", geometry: { type: "LineString", coordinates }, properties: {},
    }))),
  };
  roadMap?.getSource("closed")?.setData(data);
}

async function openRoadMap() {
  const answer = await api("/api/maps");
  const result = document.getElementById("road-result");
  if (answer.building && !answer.maps.some((m) => m.routes)) {
    showResult(result, t("admin.roads.building")); // a map just arrived: its streets come first
  }
  const [detailed] = await routable(answer);
  showResult(result, "");
  const box = document.getElementById("road-map");
  if (!detailed) {
    box.replaceWith(el("p", { class: "meta", text: t("admin.roads.nomap") }));
    return;
  }
  registerPmtiles();
  const { bounds, maxZoom } = await readHeader(detailed.file);
  roadMap = new maplibregl.Map({
    container: box, style: style(detailed.file), bounds, maxZoom: maxZoom + 2,
    attributionControl: { compact: true },
  });
  roadMap.addControl(new maplibregl.NavigationControl(), "top-right");
  window.campanileRoadMap = roadMap; // handy for debugging from the console
  roadMap.on("load", () => {
    roadMap.resize(); // the panel had just appeared: measure it again
    roadMap.addSource("closed", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    roadMap.addLayer({
      id: "closed", type: "line", source: "closed", layout: { "line-cap": "round" },
      paint: { "line-color": "#c4161c", "line-width": 6, "line-dasharray": [1.2, 0.9] },
    });
    loadRoads().catch(() => {});
  });
  roadMap.on("click", async (event) => {
    const result = document.getElementById("road-result");
    if (!confirm(t("admin.roads.confirm"))) return;
    try {
      const road = await api("/api/admin/roads/close", {
        password,
        lon: Number(event.lngLat.lng.toFixed(6)),
        lat: Number(event.lngLat.lat.toFixed(6)),
        note: document.getElementById("road-note").value,
      });
      showResult(result, t("admin.roads.done", { name: road.name || t("admin.roads.unnamed") }));
      if (road.open.length) { // lines of the same street or structure, alongside, still open
        const list = road.open
          .map((o) => `${o.name || t("admin.roads.unnamed")} (${t("search.meters", { n: o.metres })})`)
          .join(", ");
        showResult(result, `${result.textContent} ${t("admin.roads.alongside", { list })}`, true);
      }
      await loadRoads();
    } catch (error) {
      showResult(result, error.message, true);
    }
  });
}

// Sharing with a Campanile nearby: the code is shown here only, on the Campanile itself.
let sharePoll = null;

function showShare(state) {
  document.getElementById("share-start").classList.toggle("hidden", state.active);
  document.getElementById("share-on").classList.toggle("hidden", !state.active);
  clearTimeout(sharePoll);
  if (!state.active) return;
  document.getElementById("share-code").textContent = state.code;
  document.getElementById("share-status").textContent = state.ready
    ? t("admin.share.ready", { files: state.files, size: fileSize(state.bytes), minutes: state.minutes })
    : t("admin.share.preparing", { done: fileSize(state.done), total: fileSize(state.bytes) });
  sharePoll = setTimeout(() => share("state").catch(() => {}), state.ready ? 30000 : 1000);
}

async function share(action) {
  showShare(await api(`/api/admin/share/${action}`, { password }));
}

document.getElementById("share-start").addEventListener("click", () => share("start").catch((e) => alert(e.message)));
document.getElementById("share-stop").addEventListener("click", () => share("stop").catch((e) => alert(e.message)));

document.getElementById("login").addEventListener("submit", async (event) => {
  event.preventDefault();
  password = document.getElementById("password").value;
  try {
    await load();
    document.getElementById("login").classList.add("hidden");
    document.getElementById("admin-panel").classList.remove("hidden");
    const status = await api("/api/status");
    document.getElementById("signed-section").classList.toggle("hidden", !status.signed_notices);
    document.getElementById("setup-link").classList.toggle("hidden", !status.setup);
    document.getElementById("share-address").textContent = status.address || location.origin;
    await share("state");
    // On its own: waiting for a map's streets, or failing, never undoes the login.
    openRoadMap().catch((e) => showResult(document.getElementById("road-result"), e.message, true));
  } catch (error) {
    password = "";
    showResult(loginResult, error.message, true);
  }
});
