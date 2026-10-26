// DEVELOPED BY CARROTSTUDIO software house
// The navigator: where to, from where, on foot or by car, and the line to follow. A phone's
// browser tells its position only to https sites, so on a phone the start is a touch on the
// map; on the Campanile's own computer the browser can tell where it is.
import { api, el } from "/common.js";
import { lang, t } from "/i18n.js";
import { maplibregl } from "/mapstyle.js";

const INK = "#111111";
const RED = "#c4161c";
const CLOSED_EVERY = 60_000; // ms between looks at the blocked streets
const BUILDING_EVERY = 5_000; // ms between looks while the Campanile builds a map's streets
const MOVED = 40; // metres: a start or an end this far from the nearest street is said
const number = new Intl.NumberFormat(lang, { maximumFractionDigits: 1 });
const day = new Intl.DateTimeFormat(lang, { dateStyle: "long" });
const EMPTY = { type: "FeatureCollection", features: [] };

export function distance(metres) {
  return metres < 1000
    ? t("search.meters", { n: Math.max(10, Math.round(metres / 10) * 10) })
    : t("search.km", { n: number.format(metres / 1000) });
}

function duration(seconds) {
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes < 60) return t("route.minutes", { n: minutes });
  return t("route.hours", { h: Math.floor(minutes / 60), m: minutes % 60 });
}

// "Turn right onto Via Roma": the server says which turn and which street, the page says it.
function say(step) {
  if (step.turn === "arrive") return t("route.turn.arrive");
  return t(`route.turn.${step.turn}${step.name ? "" : ".here"}`, { name: step.name });
}

// The maps whose streets are ready for routes. They are built in the background when a map
// arrives: while the Campanile says it is building, look again every few seconds, then stop.
export async function routable(answer) {
  let { maps, building } = answer || (await api("/api/maps"));
  while (building && !maps.some((m) => m.routes)) {
    await new Promise((resolve) => setTimeout(resolve, BUILDING_EVERY));
    try {
      ({ maps, building } = await api("/api/maps"));
    } catch {
      // offline for a moment: the next look will do
    }
  }
  return maps.filter((m) => m.routes);
}

function point(lngLat) {
  return [Number(lngLat[0].toFixed(6)), Number(lngLat[1].toFixed(6))];
}

// ui: the elements of the panel (see map.html). getMap() gives the map once it exists.
export function attachRoute({ getMap, ui }) {
  let stage = "off"; // "to": choosing where to go, "from": choosing the start, then "shown"
  let to = null;
  let from = null;
  let mode = "foot";
  let toMarker = null;
  let fromMarker = null;
  let asked = 0;
  let line = EMPTY;
  let closed = EMPTY;

  function help(text, isError = false) {
    ui.help.textContent = text || "";
    ui.help.classList.toggle("hidden", !text);
    ui.help.classList.toggle("error", isError);
  }

  function layers(map) {
    if (!map.getSource("closed")) {
      map.addSource("closed", { type: "geojson", data: closed });
      map.addLayer({
        id: "closed",
        type: "line",
        source: "closed",
        layout: { "line-cap": "round" },
        paint: { "line-color": RED, "line-width": 6, "line-dasharray": [1.2, 0.9] },
      });
    }
    if (!map.getSource("route")) {
      map.addSource("route", { type: "geojson", data: line });
      const layout = { "line-cap": "round", "line-join": "round" };
      map.addLayer({
        id: "route-casing", type: "line", source: "route", layout,
        paint: { "line-color": "#ffffff", "line-width": 11 },
      });
      map.addLayer({
        id: "route", type: "line", source: "route", layout,
        paint: { "line-color": INK, "line-width": 6 },
      });
    }
  }

  function draw(source, data) {
    const map = getMap();
    if (map?.getSource(source)) map.getSource(source).setData(data);
  }

  function mark(which, where) {
    const map = getMap();
    if (!map) return;
    if (which === "to") {
      toMarker?.remove();
      toMarker = new maplibregl.Marker({ color: INK }).setLngLat(where).addTo(map);
    } else {
      fromMarker?.remove();
      const dot = el("div", { class: "route-start", title: t("route.start") });
      fromMarker = new maplibregl.Marker({ element: dot }).setLngLat(where).addTo(map);
    }
  }

  function askStart() {
    stage = "from";
    ui.find.classList.remove("routing"); // the search may find where one is
    if (window.isSecureContext && navigator.geolocation) {
      help(t("route.locating"));
      navigator.geolocation.getCurrentPosition(
        (where) => {
          if (stage !== "from") return;
          choose([where.coords.longitude, where.coords.latitude]);
        },
        () => {
          if (stage === "from") help(`${t("route.from")} ${t("route.from.why")}`);
        },
        { timeout: 8000, maximumAge: 60_000 },
      );
    } else {
      help(`${t("route.from")} ${t("route.from.why")}`);
    }
  }

  // A point touched on the map, or a search result chosen, while choosing.
  function choose(where) {
    const p = point(where);
    if (stage === "to") {
      to = p;
      mark("to", p);
      if (from) find();
      else askStart();
    } else if (stage === "from") {
      from = p;
      mark("from", p);
      find();
    }
  }

  async function find() {
    stage = "shown";
    const mine = ++asked;
    help(t("route.working"));
    ui.result.classList.add("hidden");
    let r;
    try {
      r = await api(`/api/route?from=${from.join(",")}&to=${to.join(",")}&by=${mode}`);
    } catch (error) {
      if (mine === asked) help(error.message, true);
      return;
    }
    if (mine !== asked) return;
    help("");
    line = { type: "Feature", geometry: { type: "LineString", coordinates: r.line }, properties: {} };
    draw("route", line);
    ui.summary.textContent = `${distance(r.metres)} · ${duration(r.seconds)} · ${t(`route.${r.mode}`)}`;
    const made = new Date(`${r.made}T12:00:00`);
    const moved = Math.max(0, ...(r.moved || []));
    ui.made.textContent = [
      Number.isNaN(made.getTime()) ? "" : t("route.made", { date: day.format(made) }),
      moved >= MOVED ? t("route.moved", { n: moved }) : "",
    ].filter(Boolean).join(" ");
    ui.steps.replaceChildren(...r.steps.map((s) => el("li", {
      text: s.metres > 0 ? `${say(s)} · ${distance(s.metres)}` : say(s),
    })));
    ui.result.classList.remove("hidden");
    ui.find.classList.add("routing");
    const map = getMap();
    if (map && r.line.length > 1) {
      map.resize(); // the panel just grew: the map is smaller than it knows
      const lons = r.line.map((c) => c[0]);
      const lats = r.line.map((c) => c[1]);
      map.fitBounds(
        [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]],
        { padding: 50, maxZoom: 17 },
      );
    }
  }

  function setMode(next) {
    mode = next;
    for (const button of ui.modes.querySelectorAll("button")) {
      button.setAttribute("aria-pressed", String(button.dataset.mode === mode));
    }
    if (to && from) find();
  }

  function reset() {
    stage = "off";
    asked++;
    to = from = null;
    toMarker?.remove();
    fromMarker?.remove();
    toMarker = fromMarker = null;
    line = EMPTY;
    draw("route", line);
    ui.result.classList.add("hidden");
    ui.panel.classList.add("hidden");
    ui.add.classList.remove("hidden");
    ui.find.classList.remove("routing");
    getMap()?.resize();
  }

  async function loadClosed() {
    try {
      const { closed: list } = await api("/api/roads/closed");
      closed = {
        type: "FeatureCollection",
        features: list.flatMap((road) => road.lines.map((coordinates) => ({
          type: "Feature",
          geometry: { type: "LineString", coordinates },
          properties: { name: road.name, note: road.note },
        }))),
      };
      draw("closed", closed);
    } catch {
      // offline for a moment: the next look will do
    }
  }

  ui.add.addEventListener("click", () => {
    ui.panel.classList.remove("hidden");
    ui.add.classList.add("hidden");
    stage = "to";
    help(t("route.to"));
  });
  ui.close.addEventListener("click", reset);
  ui.from.addEventListener("click", askStart);
  for (const button of ui.modes.querySelectorAll("button")) {
    button.addEventListener("click", () => setMode(button.dataset.mode));
  }
  setMode(mode);

  function hook(map) {
    if (map.isStyleLoaded()) layers(map);
    map.on("style.load", () => layers(map)); // a different map: the lines go on top again
    map.on("click", (event) => {
      if (stage === "to" || stage === "from") choose([event.lngLat.lng, event.lngLat.lat]);
    });
    map.on("click", "closed", (event) => {
      if (stage !== "off") return;
      const road = event.features[0]?.properties || {};
      const card = el("div", {},
        el("strong", { text: t("route.closed") }),
        el("span", { text: [road.name, road.note].filter(Boolean).join(" · ") }));
      new maplibregl.Popup({ closeButton: false }).setLngLat(event.lngLat).setDOMContent(card).addTo(map);
    });
    loadClosed();
    setInterval(loadClosed, CLOSED_EVERY);
  }

  return {
    hook,
    picking: () => stage === "to" || stage === "from",
    pick: (result) => choose([result.lon, result.lat]),
  };
}
