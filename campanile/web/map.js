// DEVELOPED BY CARROTSTUDIO software house
import { api, fileSize } from "/common.js";
import { has, t, translatePage } from "/i18n.js";
import { maplibregl, readHeader, registerPmtiles, style } from "/mapstyle.js";
import { attachRoute, routable } from "/route.js";
import { attachSearch, describe, title } from "/search.js";

translatePage();

const picker = document.getElementById("map-select");
const message = document.getElementById("map-message");
// How close to go, by what was found: a country, a town, a street, a pharmacy...
const ZOOM = { country: 5, region: 7, city: 11, town: 12, village: 13, hamlet: 14, poi: 17 };

let map = null;
let marker = null;

const route = attachRoute({
  getMap: () => map,
  ui: Object.fromEntries(
    ["add", "help", "modes", "result", "summary", "made", "steps", "from", "close"].map((k) => [
      k,
      document.getElementById(`route-${k}`),
    ]).concat([["panel", document.getElementById("route")], ["find", document.querySelector(".find")]]),
  ),
});

// The search sheet at the bottom. Open, it takes the screen and the box gets the keyboard;
// a result chosen, a route started or a touch on the map gives the map back.
const sheet = document.querySelector(".sheet");
const opener = document.getElementById("find-open");

function openSheet(open) {
  sheet.classList.toggle("open", open);
  document.body.classList.toggle("sheet-open", open);
  opener.setAttribute("aria-expanded", String(open));
  if (open) document.getElementById("find-q").focus();
  else opener.focus({ preventScroll: true });
}

opener.addEventListener("click", () => openSheet(true));
document.getElementById("find-close").addEventListener("click", () => openSheet(false));
document.getElementById("route-add").addEventListener("click", () => openSheet(false));
sheet.addEventListener("keydown", (event) => {
  if (event.key === "Escape") openSheet(false);
});

function showMessage(text) {
  message.textContent = text;
  message.classList.remove("hidden");
  document.getElementById("map").classList.add("hidden");
}

// keepView: a search result is about to be shown, so no jump to the whole map first.
async function open(file, keepView = false) {
  const { bounds, maxZoom } = await readHeader(file);
  if (map) {
    map.setStyle(style(file));
    map.setMaxZoom(maxZoom + 2);
    if (!keepView) map.fitBounds(bounds, { animate: false, padding: 10 });
    return;
  }
  map = new maplibregl.Map({
    container: "map",
    style: style(file),
    bounds,
    fitBoundsOptions: { padding: 10 },
    // Past the file's max zoom, the existing tiles are simply scaled up.
    maxZoom: maxZoom + 2,
    attributionControl: { compact: true },
  });
  map.addControl(new maplibregl.NavigationControl(), "top-right");
  map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");
  window.campanileMap = map; // handy for debugging from the console
  route.hook(map);
  map.on("click", () => {
    if (!route.picking() && sheet.classList.contains("open")) openSheet(false);
  });
}

// A result is shown on the map it was found in: for a street or a pharmacy, the detailed one.
async function go(result) {
  const file = `${result.map}.pmtiles`;
  if (picker.value !== file && [...picker.options].some((o) => o.value === file)) {
    picker.value = file;
    history.replaceState(null, "", "?m=" + encodeURIComponent(file));
    await open(file, true);
  }
  marker?.remove();
  const card = document.createElement("div");
  const name = document.createElement("strong");
  name.textContent = title(result);
  const about = document.createElement("span");
  about.textContent = describe(result);
  card.append(name, about);
  marker = new maplibregl.Marker({ color: "#111111" })
    .setLngLat([result.lon, result.lat])
    .setPopup(new maplibregl.Popup({ closeButton: false, offset: 30 }).setDOMContent(card))
    .addTo(map);
  marker.togglePopup();
  const most = map.getMaxZoom();
  if (result.bbox) {
    const [w, s, e, n] = result.bbox;
    map.fitBounds([[w, s], [e, n]], { padding: 60, maxZoom: Math.min(17, most) });
  } else {
    const zoom = ZOOM[result.type] ?? ZOOM[result.detail] ?? ZOOM[result.kind] ?? 14;
    map.flyTo({ center: [result.lon, result.lat], zoom: Math.min(zoom, most) });
  }
}

async function start() {
  registerPmtiles();

  let maps;
  let building;
  try {
    ({ maps, building } = await api("/api/maps"));
  } catch (error) {
    showMessage(error.message);
    return;
  }
  if (maps.length === 0) {
    showMessage(t("map.none"));
    sheet.classList.add("hidden");
    return;
  }
  maps.sort((a, b) => (a.name === "world") - (b.name === "world")); // the detailed map first
  for (const m of maps) {
    const option = document.createElement("option");
    option.value = m.file;
    const name = has(`map.name.${m.name}`) ? t(`map.name.${m.name}`) : m.name;
    option.textContent = `${name} (${fileSize(m.bytes)})`;
    picker.append(option);
  }
  // A choice only when there is one to make.
  document.getElementById("map-choice").classList.toggle("hidden", maps.length < 2);
  const requested = new URLSearchParams(location.search).get("m");
  if (requested && maps.some((m) => m.file === requested)) picker.value = requested;

  picker.addEventListener("change", () => {
    history.replaceState(null, "", "?m=" + encodeURIComponent(picker.value));
    open(picker.value).catch((e) => showMessage(t("map.unreadable", { error: e.message })));
  });
  try {
    await open(picker.value);
  } catch (error) {
    showMessage(t("map.unreadable", { error: error.message }));
    return;
  }
  attachSearch({
    input: document.getElementById("find-q"),
    results: document.getElementById("find-results"),
    chips: document.getElementById("find-chips"),
    center: () => (map ? map.getCenter().toArray() : null),
    pick: (result) => {
      openSheet(false);
      if (route.picking()) route.pick(result); // choosing where to go, or where one is
      else go(result).catch((e) => showMessage(t("map.unreadable", { error: e.message })));
    },
  });
  // The button shows once a map's streets are ready for routes (built in the background).
  routable({ maps, building }).then((ready) => {
    if (ready.length) document.getElementById("route-add").classList.remove("hidden");
  });
}

start();
