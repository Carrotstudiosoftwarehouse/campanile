// DEVELOPED BY CARROTSTUDIO software house
// The setup page: the Campanile downloads, this page only says what and shows how it goes.
import { api, fileSize, showResult } from "/common.js";
import { t, translatePage } from "/i18n.js";
import { maplibregl, readHeader, registerPmtiles, style } from "/mapstyle.js";
import { attachSearch } from "/search.js";

translatePage();
registerPmtiles();

const MAX_AREA = 0.25; // square degrees, the same limit the Campanile checks
const POLL = 1000;
const IDLE_POLL = 3000; // a stick plugged in shows up by itself
const TOWN_ZOOM = 11; // a town and its surroundings: well within MAX_AREA

let password = "";
let areaMap = null;
let polling = null;
let lastState = null;

const $ = (id) => document.getElementById(id);

async function call(path, body = {}) {
  return api(path, { password, ...body });
}

function showJob(job) {
  const box = $("job");
  box.classList.toggle("hidden", !job);
  if (!job) return;
  $("job-title").textContent = t(`setup.task.${job.task}`);
  const known = job.total && job.total > 0;
  const bar = $("job-bar");
  if (known) bar.value = job.done / job.total;
  else bar.removeAttribute("value"); // moving bar: we don't know the size
  const amount = known
    ? t("setup.amount.of", { done: fileSize(job.done), total: fileSize(job.total) })
    : job.done ? fileSize(job.done) : "";
  $("job-text").textContent = [t(`setup.step.${job.step}`), amount].filter(Boolean).join(" · ");
  $("job-error").textContent = job.error
    ? `${t(`setup.error.${job.error}`)}${job.detail ? ` (${job.detail})` : ""}`
    : "";
  $("cancel").classList.toggle("hidden", job.finished);
}

// Where this computer is, if the browser knows and the person agrees: the area to download
// is then already framed. The position stays in this page; the Campanile never receives it.
function locate() {
  if (!navigator.geolocation) return;
  navigator.geolocation.getCurrentPosition(
    ({ coords }) => {
      areaMap.jumpTo({ center: [coords.longitude, coords.latitude], zoom: TOWN_ZOOM });
      $("area-where").textContent = t("setup.area.here");
    },
    () => {
      $("area-where").textContent = t("setup.area.nowhere");
    },
    { timeout: 15000, maximumAge: 3600000 },
  );
}

async function showArea(maps) {
  const overview = maps.includes("world") ? "world" : null;
  $("area-wait").classList.toggle("hidden", Boolean(overview));
  $("area-map").classList.toggle("hidden", !overview);
  $("area-find").classList.toggle("hidden", !overview);
  document.querySelector("[data-task=map-area]").classList.toggle("hidden", !overview);
  if (!overview || areaMap) return;
  const { bounds } = await readHeader(`${overview}.pmtiles`);
  areaMap = new maplibregl.Map({
    container: "area-map",
    style: style(`${overview}.pmtiles`),
    bounds,
    maxZoom: 14,
    attributionControl: { compact: true },
  });
  areaMap.addControl(new maplibregl.NavigationControl(), "top-right");
  attachSearch({
    input: $("area-q"),
    results: $("area-results"),
    chips: null,
    center: () => areaMap.getCenter().toArray(),
    pick: (place) => {
      const zoom = { country: 5, region: 7 }[place.kind] ?? TOWN_ZOOM;
      areaMap.flyTo({ center: [place.lon, place.lat], zoom });
    },
  });
  locate();
}

async function refresh() {
  const state = await call("/api/setup/state");
  const hasWiki = (code) => state.wiki.some((name) => name.startsWith(`wikipedia_${code}_medicine`));
  $("world-ok").textContent = state.maps.includes("world") ? "✓" : "";
  $("area-ok").textContent = state.maps.includes("area") ? "✓" : "";
  $("wiki-unsupported").classList.toggle("hidden", state.supported["kiwix-serve"]);
  document.querySelector("[data-task=map-world]").disabled = !state.supported.pmtiles;
  $("free").textContent = t("setup.free", { free: fileSize(state.free) });

  // A step already done can be run again to update it: shown, but not as the next thing to do.
  const world = document.querySelector("[data-task=map-world]");
  world.classList.toggle("secondary", state.maps.includes("world"));
  world.textContent = state.maps.includes("world") ? t("setup.again") : t(world.dataset.i18n);
  for (const button of document.querySelectorAll("[data-task=wiki]")) {
    const code = button.dataset.lang;
    button.classList.toggle("hidden", !state.supported["kiwix-serve"]);
    button.classList.toggle("secondary", hasWiki(code));
    $(`wiki-${code}-ok`).textContent = hasWiki(code) ? "✓" : "";
  }
  showDrives(state);

  const running = state.job && !state.job.finished;
  for (const button of document.querySelectorAll("[data-task]")) button.disabled = running;
  document.querySelector("[data-task=copy]").disabled = running || !state.drives.length;
  showJob(state.job);
  await showArea(state.maps);
  clearTimeout(polling);
  polling = setTimeout(() => refresh().catch(() => {}), running ? POLL : IDLE_POLL);
}

function showDrives(state) {
  lastState = state;
  $("extras-ok").textContent = state.extras ? "✓" : "";
  const select = $("drive");
  const chosen = select.value;
  select.replaceChildren(...state.drives.map((drive) => {
    const option = document.createElement("option");
    option.value = drive.path;
    option.textContent = t("setup.copy.option", { name: drive.name, free: fileSize(drive.free) });
    return option;
  }));
  if (state.drives.some((d) => d.path === chosen)) select.value = chosen;
  select.classList.toggle("hidden", !state.drives.length);
  $("copy-none").classList.toggle("hidden", state.drives.length > 0);
  const drive = state.drives.find((d) => d.path === select.value);
  const size = t("setup.copy.size", { size: fileSize(state.copy_bytes) });
  $("copy-size").textContent = drive && drive.free < state.copy_bytes
    ? `${size} ${t("setup.copy.small")}`
    : size;
}

function areaBox() {
  const b = areaMap.getBounds();
  const box = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].map((v) => Math.round(v * 1e5) / 1e5);
  return (box[2] - box[0]) * (box[3] - box[1]) <= MAX_AREA ? box : null;
}

for (const button of document.querySelectorAll("[data-task]")) {
  button.addEventListener("click", async () => {
    const task = button.dataset.task;
    const body = { task };
    if (task === "map-area") {
      body.bbox = areaBox();
      if (!body.bbox) {
        showResult($("area-result"), t("setup.area.big"), true);
        return;
      }
      showResult($("area-result"), "");
    }
    if (task === "wiki") body.lang = button.dataset.lang;
    if (task === "copy") body.drive = $("drive").value;
    if (task === "receive") {
      body.address = $("receive-address").value;
      body.code = $("receive-code").value;
    }
    try {
      await call("/api/setup/start", body);
    } catch (error) {
      alert(error.message);
    }
    await refresh();
  });
}

$("drive").addEventListener("change", () => lastState && showDrives(lastState));

$("cancel").addEventListener("click", async () => {
  await call("/api/setup/cancel");
  await refresh();
});

$("login").addEventListener("submit", async (event) => {
  event.preventDefault();
  password = $("password").value;
  try {
    await refresh();
    $("login").classList.add("hidden");
    $("steps").classList.remove("hidden");
    areaMap?.resize();
  } catch (error) {
    password = "";
    showResult($("login-result"), error.message, true);
  }
});
