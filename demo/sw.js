// DEVELOPED BY CARROTSTUDIO software house
// The online demo: this service worker plays the Campanile for the real pages, inside the
// visitor's browser. Nothing leaves it: nobody sees what another visitor writes, nothing to
// moderate. Only what a visitor can try is here; the real rules are in campanile/api.py and
// campanile/store.py.

const VERSION = "0.1.0-demo";
const STORE = "campanile-demo";
const CATEGORIES = ["water", "food", "medicine", "power", "shelter", "transport", "help", "info", "other"];
const CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";

const MESSAGES = {
  it: {
    required: "Il campo '{field}' è obbligatorio.",
    too_long: "Il campo '{field}' supera i {max} caratteri.",
    choose_kind: "Scegli 'offro' o 'cerco'.",
    bad_category: "Categoria non valida.",
    search_too_short: "Scrivi almeno 2 lettere del nome da cercare.",
    wrong_code: "Numero o codice non corretti.",
    already_closed: "Già chiuso o già tolto.",
    demo_only: "Nella demo questa parte è spenta: si usa dal Campanile vero.",
    unknown_api: "Percorso API sconosciuto.",
    bad_json: "JSON non valido.",
  },
  en: {
    required: "The field '{field}' is required.",
    too_long: "The field '{field}' is longer than {max} characters.",
    choose_kind: "Choose 'I offer' or 'I need'.",
    bad_category: "Invalid category.",
    search_too_short: "Type at least 2 letters of the name.",
    wrong_code: "Wrong number or code.",
    already_closed: "Already closed or removed.",
    demo_only: "This part is off in the demo: it works on a real Campanile.",
    unknown_api: "Unknown API path.",
    bad_json: "Invalid JSON.",
  },
};

const FIELDS = {
  it: { text: "descrizione", area: "zona", contact: "contatto", name: "nome", message: "messaggio", place: "luogo" },
  en: { text: "description", area: "area", contact: "contact", name: "name", message: "message", place: "place" },
};

// Invented examples, in the visitor's language, dated a few minutes ago.
const EXAMPLES = {
  it: {
    notices: [
      { urgent: true, ago: 25, title: "Distribuzione di acqua potabile",
        text: "Oggi dalle 16 alle 19 in piazza del mercato. Portate contenitori: una tanica per famiglia." },
      { urgent: false, ago: 90, title: "Farmacia aperta",
        text: "La farmacia di via Roma 12 è aperta dalle 9 alle 13 con il generatore. Ricette su carta." },
    ],
    posts: [
      { kind: "offer", category: "water", ago: 12, text: "20 litri di acqua in bottiglia.",
        area: "corso Vittorio", contact: "Luca, all'edicola" },
      { kind: "offer", category: "power", ago: 40, text: "Generatore acceso: ricarico telefoni dalle 18 alle 21.",
        area: "via Po 3, cortile", contact: "Chiedere di Sara" },
      { kind: "need", category: "medicine", ago: 55, text: "Insulina da tenere al fresco: chi ha un frigo acceso?",
        area: "via Garibaldi 8", contact: "Anna, piano terra" },
      { kind: "offer", category: "transport", ago: 70, text: "Due posti in auto per Moncalieri, domani alle 8.",
        area: "piazza Statuto", contact: "Marco, auto grigia" },
    ],
    safe: [
      { name: "Giulia Rossi", message: "Sto bene, sono con mia sorella.", place: "palestra della scuola", ago: 30 },
      { name: "Paolo Bianchi", message: "", place: "", ago: 120 },
    ],
  },
  en: {
    notices: [
      { urgent: true, ago: 25, title: "Drinking water distribution",
        text: "Today 4 pm to 7 pm at the market square. Bring containers: one tank per family." },
      { urgent: false, ago: 90, title: "Pharmacy open",
        text: "The pharmacy at 12 Via Roma is open 9 am to 1 pm on a generator. Paper prescriptions." },
    ],
    posts: [
      { kind: "offer", category: "water", ago: 12, text: "20 litres of bottled water.",
        area: "Corso Vittorio", contact: "Luca, at the newsstand" },
      { kind: "offer", category: "power", ago: 40, text: "Generator on: I can charge phones 6 pm to 9 pm.",
        area: "3 Via Po, courtyard", contact: "Ask for Sara" },
      { kind: "need", category: "medicine", ago: 55, text: "Insulin that must stay cold: who has a working fridge?",
        area: "8 Via Garibaldi", contact: "Anna, ground floor" },
      { kind: "offer", category: "transport", ago: 70, text: "Two seats in a car to Moncalieri, tomorrow at 8 am.",
        area: "Piazza Statuto", contact: "Marco, grey car" },
    ],
    safe: [
      { name: "Giulia Rossi", message: "I'm fine, I'm with my sister.", place: "school gym", ago: 30 },
      { name: "Paolo Bianchi", message: "", place: "", ago: 120 },
    ],
  },
};

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin === location.origin && url.pathname.startsWith("/api/")) {
    event.respondWith(serialized(() => answer(event.request, url)));
  }
});

self.addEventListener("message", (event) => {
  if (event.data === "reset") event.waitUntil(caches.delete(STORE));
});

// One request at a time, so two quick taps can't both read the same state.
let queue = Promise.resolve();
function serialized(task) {
  const run = queue.then(task, task);
  queue = run.catch(() => {});
  return run;
}

class Refused extends Error {
  constructor(status, key, params = {}) {
    super(key);
    this.status = status;
    this.key = key;
    this.params = params;
  }
}

function language(request) {
  const tag = (request.headers.get("Accept-Language") || "").slice(0, 2).toLowerCase();
  return Object.hasOwn(MESSAGES, tag) ? tag : "en";
}

function message(lang, key, params) {
  return MESSAGES[lang][key].replace(/\{(\w+)\}/g, (_, name) =>
    name === "field" ? FIELDS[lang][params.field] : String(params[name]));
}

function reply(status, body) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
  });
}

async function answer(request, url) {
  const lang = language(request);
  try {
    const state = await load(lang);
    const result = await route(request, url, state, lang);
    await save(lang, state);
    return reply(result.status || 200, result.body);
  } catch (error) {
    if (error instanceof Refused) return reply(error.status, { error: message(lang, error.key, error.params) });
    throw error;
  }
}

// -- state, one per language, in the browser's cache storage ------------------------------

const stateUrl = (lang) => `/__demo-state-${lang}`;

async function load(lang) {
  const saved = await (await caches.open(STORE)).match(stateUrl(lang));
  return saved ? saved.json() : seed(lang);
}

async function save(lang, state) {
  await (await caches.open(STORE)).put(stateUrl(lang), new Response(JSON.stringify(state)));
}

async function seed(lang) {
  const now = Math.floor(Date.now() / 1000);
  const examples = EXAMPLES[lang] || EXAMPLES.en;
  let id = 0;
  const at = (minutes) => now - minutes * 60;
  return {
    nextId: 100,
    notices: examples.notices.map((n) => ({ id: ++id, title: n.title, text: n.text, urgent: n.urgent, created: at(n.ago) })),
    posts: examples.posts.map((p) => ({ ...p, id: ++id, created: at(p.ago), code: newCode(), closed: false })),
    safe: examples.safe.map((s) => ({ ...s, id: ++id, created: at(s.ago), code: newCode() })),
    maps: await mapList(),
  };
}

async function mapList() {
  try {
    const response = await fetch("/maps/index.json");
    return response.ok ? response.json() : [];
  } catch {
    return [];
  }
}

// -- the API --------------------------------------------------------------------------------

async function route(request, url, state, lang) {
  const path = url.pathname;
  if (request.method === "GET") {
    if (path === "/api/status") {
      return { body: {
        version: VERSION,
        open_posts: state.posts.filter((p) => !p.closed).length,
        registered_people: state.safe.length,
        kiwix: false, kiwix_port: 0, kiwix_url: null,
        signed_notices: false, setup: false,
        maps: state.maps,
        address: `${location.origin}/`,
        emergency: "112",
      } };
    }
    if (path === "/api/maps") return { body: { maps: state.maps } };
    if (path === "/api/notices") {
      const notices = [...state.notices].sort((a, b) => b.urgent - a.urgent || b.created - a.created);
      return { body: { notices } };
    }
    if (path === "/api/posts") {
      const kind = url.searchParams.get("kind");
      const category = url.searchParams.get("category");
      const posts = state.posts
        .filter((p) => !p.closed && (!kind || p.kind === kind) && (!category || p.category === category))
        .sort((a, b) => b.created - a.created || b.id - a.id)
        .map(({ id, kind, category, text, area, contact, created }) => ({ id, kind, category, text, area, contact, created }));
      return { body: { posts } };
    }
    if (path === "/api/safe") {
      const words = normalize(url.searchParams.get("q") || "").split(" ").filter(Boolean);
      if (words.join(" ").length < 2) throw new Refused(400, "search_too_short");
      const results = state.safe
        .filter((s) => words.every((w) => normalize(s.name).includes(w)))
        .sort((a, b) => b.created - a.created)
        .map(({ id, name, message, place, created }) => ({ id, name, message, place, created }));
      return { body: { results } };
    }
    if (path === "/api/places") return { body: await findPlaces(url, lang) };
    throw new Refused(404, "unknown_api");
  }

  if (path.startsWith("/api/admin/") || path.startsWith("/api/setup/")) throw new Refused(403, "demo_only");
  let data;
  try {
    data = await request.json();
  } catch {
    throw new Refused(400, "bad_json");
  }
  if (typeof data !== "object" || data === null || Array.isArray(data)) throw new Refused(400, "bad_json");
  const now = Math.floor(Date.now() / 1000);

  if (path === "/api/posts") {
    if (data.kind !== "offer" && data.kind !== "need") throw new Refused(400, "choose_kind");
    if (!CATEGORIES.includes(data.category)) throw new Refused(400, "bad_category");
    const post = {
      id: state.nextId++,
      kind: data.kind,
      category: data.category,
      text: field(data.text, "text", 500),
      area: field(data.area, "area", 80),
      contact: field(data.contact, "contact", 120),
      created: now,
      code: newCode(),
      closed: false,
    };
    state.posts.push(post);
    return { status: 201, body: { id: post.id, code: post.code, pending: false } };
  }
  if (path === "/api/posts/close") {
    const post = state.posts.find((p) => p.id === Number(data.id) && !p.closed);
    checkCode(post, data.code);
    post.closed = true;
    return { body: { ok: true } };
  }
  if (path === "/api/safe") {
    const person = {
      id: state.nextId++,
      name: field(data.name, "name", 80),
      message: field(data.message, "message", 300, false),
      place: field(data.place, "place", 80, false),
      created: now,
      code: newCode(),
    };
    state.safe.push(person);
    return { status: 201, body: { id: person.id, code: person.code } };
  }
  if (path === "/api/safe/remove") {
    const person = state.safe.find((s) => s.id === Number(data.id));
    checkCode(person, data.code);
    state.safe = state.safe.filter((s) => s !== person);
    return { body: { ok: true } };
  }
  throw new Refused(404, "unknown_api");
}

function field(value, name, max, required = true) {
  const text = typeof value === "string" ? value.trim() : "";
  if (required && !text) throw new Refused(400, "required", { field: name });
  if (text.length > max) throw new Refused(400, "too_long", { field: name, max });
  return text;
}

function checkCode(item, code) {
  if (!item) throw new Refused(404, "already_closed");
  const clean = (c) => String(c || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
  if (clean(item.code) !== clean(code)) throw new Refused(403, "wrong_code");
}

function newCode() {
  const pick = crypto.getRandomValues(new Uint32Array(8));
  const raw = Array.from(pick, (n) => CODE_ALPHABET[n % CODE_ALPHABET.length]).join("");
  return `${raw.slice(0, 4)}-${raw.slice(4)}`;
}

// -- searching the map: the rules of campanile/places.py, on the index build-demo.sh made
// with it (maps/places.json). Kept short: the demo has one small map.

const TYPES = ["place", "street", "poi"];
const PAD = 0.003; // degrees, about 300 m, as in places.py
let placesData = null;

function plain(text) {
  return text.toLowerCase().normalize("NFKD").replace(/\p{M}/gu, "")
    .replace(/[^\p{L}\p{N}]+/gu, " ").trim();
}

function km(lon1, lat1, lon2, lat2) {
  const dx = (lon2 - lon1) * 111.32 * Math.cos(((lat1 + lat2) / 2) * Math.PI / 180);
  return Math.hypot(dx, (lat2 - lat1) * 110.57);
}

function before(a, b) {
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    if (a[i] < b[i]) return -1;
    if (a[i] > b[i]) return 1;
  }
  return 0;
}

function touch(a, b) {
  return a[0] - PAD <= b[2] && b[0] - PAD <= a[2] && a[1] - PAD <= b[3] && b[1] - PAD <= a[3];
}

function sameThing(a, b) {
  if (plain(a.local || a.name) !== plain(b.local || b.name)) return false;
  if (a.type === "place" || b.type === "place") return km(a.lon, a.lat, b.lon, b.lat) < 3;
  const street = a.bbox ? a : b.bbox ? b : null;
  if (street) {
    const other = street === a ? b : a;
    return touch(street.bbox, [other.lon, other.lat, other.lon, other.lat]);
  }
  return km(a.lon, a.lat, b.lon, b.lat) < 0.05;
}

async function loadPlaces() {
  if (!placesData) {
    const response = await fetch("/maps/places.json");
    placesData = response.ok ? await response.json() : { synonyms: {}, maps: [] };
    // "Hwy" finds "Highway", as on the Campanile (places.SHORT_FORMS).
    const short = new Map(Object.entries(placesData.short_forms || {}));
    for (const m of placesData.maps) {
      m.variants = m.rows.map((r) => [...new Set([r[3], ...Object.values(r[4])].map(plain))]);
      m.words = m.variants.map((v) => {
        const words = v.join(" ").split(" ");
        return [...words, ...words.filter((w) => short.has(w)).map((w) => short.get(w))];
      });
    }
  }
  return placesData;
}

async function findPlaces(url, lang) {
  const text = plain(url.searchParams.get("q") || "");
  if (text.length < 2) throw new Refused(400, "search_too_short");
  let near = null;
  if (url.searchParams.get("near")) {
    near = url.searchParams.get("near").split(",").map(Number);
    if (near.length !== 2 || !(Math.abs(near[0]) <= 180 && Math.abs(near[1]) <= 90)) {
      throw new Refused(400, "bad_number");
    }
  }
  const data = await loadPlaces();
  // Its own keys only: "constructor" is in every object, and not a kind of place.
  const kinds = Object.prototype.hasOwnProperty.call(data.synonyms, text) ? data.synonyms[text] : null;
  const words = text.split(" ");
  const found = [];
  for (const m of [...data.maps].sort((a, b) => b.max_zoom - a.max_zoom)) {
    m.rows.forEach((r, i) => {
      const distance = near ? km(near[0], near[1], r[5], r[6]) : 0;
      if (kinds) { // a kind of place: only that kind, never a namesake (as places.py)
        if (r[0] === 2 && kinds.includes(r[1])) found.push([[-1, 0, distance], m, r]);
        return;
      }
      if (words.every((w) => m.words[i].some((x) => x.startsWith(w)))) {
        const variants = m.variants[i];
        const quality = variants.includes(text) ? 0 : variants.some((v) => v.startsWith(text)) ? 1 : 2;
        const order = r[0] === 0 ? ({ country: 0, region: 1, locality: 2 }[r[1]] ?? 3) : r[0] * 10;
        found.push([[quality, order, distance, -(r[9] || 0), variants[0]], m, r]);
      }
    });
  }
  found.sort((a, b) => before(a[0], b[0]));
  const results = [];
  for (const [, m, r] of found) {
    const name = r[4][lang] || r[3];
    const result = { name, type: TYPES[r[0]], kind: r[1], lon: r[5], lat: r[6], map: m.map };
    if (name !== r[3]) result.local = r[3];
    if (r[2]) result.detail = r[2];
    if (r[8]) result.near = r[8];
    if (r[7]) result.bbox = r[7];
    if (near) result.meters = Math.round(km(near[0], near[1], r[5], r[6]) * 1000);
    if (!results.some((other) => sameThing(result, other))) results.push(result);
    if (results.length === 10) break;
  }
  return { results, ready: true, missing: Boolean(kinds) && results.length === 0 };
}

function normalize(name) {
  return name.toLowerCase().normalize("NFKD").replace(/\p{M}/gu, "").split(/\s+/).filter(Boolean).join(" ");
}
