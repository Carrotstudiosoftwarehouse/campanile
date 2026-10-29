// DEVELOPED BY CARROTSTUDIO software house
import {
  api, el, when, showResult, CATEGORIES, categoryLabel, kindLabel, rememberMine,
  loadMine, saveMine, closeMine, fold,
} from "/common.js";
import { showEmergency, t, tn, translatePage } from "/i18n.js";

translatePage();

const MINE = { kind: "posts", path: "/api/posts/close" };
const FIRST = 3;  // the neighbors' newest posts, still; the rest behind one button

// Arriving from the home page's big buttons: show what helps and preset the form.
// ?i=need shows the offers, ?i=offer shows the needs.
const OPPOSITE = { need: "offer", offer: "need" };
const asked = new URLSearchParams(location.search).get("i");
const INTENT = Object.hasOwn(OPPOSITE, asked) ? asked : null;  // not "__proto__" and friends

const list = document.getElementById("list");
const listStatus = document.getElementById("list-status");
const mineSection = document.getElementById("mine-section");
const mineList = document.getElementById("mine");
const showAll = document.getElementById("show-all");
const filterKind = document.getElementById("filter-kind");
const filterCategory = document.getElementById("filter-category");
let everything = false;

function fillCategories() {
  const select = document.getElementById("category");
  for (const value of CATEGORIES) {
    filterCategory.append(el("option", { value, text: categoryLabel(value) }));
    select.append(el("option", { value, text: categoryLabel(value) }));
  }
}

function postCard(p, mine) {
  const card = el("article", { class: `post ${p.kind || ""}` },
    el("div", {},
      mine ? el("span", { class: "tag mine", text: t("board.mine.tag") }) : null,
      p.kind ? el("span", { class: "tag kind", text: kindLabel(p.kind) }) : null,
      p.category ? el("span", { class: "tag", text: categoryLabel(p.category) }) : null,
    ),
    el("p", { text: p.text }),
    p.area ? el("div", { class: "meta", text: t("board.area", { area: p.area }) }) : null,
    p.contact ? el("div", { class: "meta", text: t("board.contact", { contact: p.contact }) }) : null,
    el("div", { class: "meta", text: `N. ${p.id} · ${when(p.created)}` }),
  );
  if (mine) {  // posted from this phone: closing it is one tap, right here
    const close = el("button", { type: "button", class: "secondary", text: t(p.kind ? `board.close.${p.kind}` : "board.other.submit") });
    const result = el("p", { class: "result" });
    close.addEventListener("click", async () => {
      close.disabled = true;
      try {
        await closeMine(MINE.kind, MINE.path, mine);
      } catch (error) {
        showResult(result, error.message, true);
        close.disabled = false;
        return;
      }
      load();
    });
    card.append(close, result);
  }
  return card;
}

// The same words, however the server tidied the spaces.
const words = (text) => text.replace(/\s+/g, " ").trim().slice(0, 100);

// This phone's posts, as full cards. A number alone is not proof: after a new database the
// same number is someone else's post, so the text must match too, or the entry is forgotten.
function showMine(posts) {
  const byId = new Map(posts.map((p) => [p.id, p]));
  const kept = [];
  const cards = [];
  for (const entry of loadMine(MINE.kind)) {
    const post = byId.get(entry.id);
    if (post && !words(post.text).startsWith(words(entry.label))) continue;  // not ours
    kept.push(entry);
    if (post && INTENT && post.kind !== INTENT) continue;  // the other page's task
    // Not in the list: waiting for the admin's check, or older than the newest 500.
    cards.push(postCard(post || { id: entry.id, text: entry.label, created: entry.created }, entry));
  }
  if (kept.length !== loadMine(MINE.kind).length) saveMine(MINE.kind, kept);
  mineSection.classList.toggle("hidden", cards.length === 0);
  fold(mineList, cards.reverse(), t(INTENT ? `board.${INTENT}.many` : "board.many", { n: cards.length }));
  return new Set(kept.map((entry) => entry.id));
}

async function load() {
  listStatus.textContent = t("board.loading");
  try {
    const { posts } = await api("/api/posts");
    const mine = showMine(posts);
    const theirs = posts.filter((p) => !mine.has(p.id)
      && (!filterKind.value || p.kind === filterKind.value)
      && (!filterCategory.value || p.category === filterCategory.value));
    const shown = everything ? theirs : theirs.slice(0, FIRST);
    list.replaceChildren(...shown.map((p) => postCard(p)));
    if (INTENT) listStatus.textContent = theirs.length ? "" : t(`board.${INTENT}.empty`);
    else listStatus.textContent = theirs.length ? tn("board.count", theirs.length) : t("board.empty");
    showAll.textContent = t("board.all", { n: theirs.length });
    showAll.classList.toggle("hidden", shown.length === theirs.length);
  } catch (error) {
    listStatus.textContent = error.message;
  }
}

showAll.addEventListener("click", () => {
  everything = true;
  load();
});

document.getElementById("post-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.submitter || event.target.querySelector("button[type=submit]");
  const result = document.getElementById("post-result");
  button.disabled = true;
  try {
    const response = await api("/api/posts", {
      kind: document.getElementById("kind").value,
      category: document.getElementById("category").value,
      text: document.getElementById("text").value,
      area: document.getElementById("area").value,
      contact: document.getElementById("contact").value,
    });
    document.getElementById("receipt-title").textContent =
      t(response.pending ? "board.pending" : "board.published");
    rememberMine("posts", response, document.getElementById("text").value);
    document.getElementById("receipt-id").textContent = response.id;
    document.getElementById("receipt-code").textContent = response.code;
    document.getElementById("receipt").classList.remove("hidden");
    event.target.reset();
    if (INTENT) document.getElementById("kind").value = INTENT;  // still hidden, still meant
    showResult(result, "");
    document.getElementById("receipt").scrollIntoView({ behavior: "smooth" });
    load();
  } catch (error) {
    showResult(result, error.message, true);
  } finally {
    button.disabled = false;
  }
});

document.getElementById("close-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const result = document.getElementById("close-result");
  try {
    await api("/api/posts/close", {
      id: document.getElementById("close-id").value,
      code: document.getElementById("close-code").value,
    });
    showResult(result, t("board.closed"));
    event.target.reset();
    load();
  } catch (error) {
    showResult(result, error.message, true);
  }
});

filterKind.addEventListener("change", load);
filterCategory.addEventListener("change", load);
// No button to press: the board refreshes itself, as the home page does.
setInterval(load, 30_000);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") load();
});

function applyIntent(intent) {
  if (!intent) return;
  document.title = `${t(`board.${intent}.title`)} · Campanile`;
  document.getElementById("title").textContent = t(`board.${intent}.title`);
  document.getElementById("intro").textContent = t(`board.${intent}.intro`);
  document.getElementById("write-link").textContent = t(`board.${intent}.write`);
  document.getElementById("form-title").textContent = t(`board.${intent}.form`);
  document.getElementById("list-title").textContent = t(`board.${intent}.list`);
  document.getElementById("mine-title").textContent = t(`board.${intent}.mine`);
  document.getElementById("mine-sub").textContent = t("board.mine.sub.help");
  document.getElementById("kind").value = intent;
  // Said already with the button pressed: one question less, and an example that fits.
  document.getElementById("kind").classList.add("hidden");
  document.getElementById("kind-label").classList.add("hidden");
  document.getElementById("text").placeholder = t(`board.${intent}.ph`);
  filterKind.value = OPPOSITE[intent];
  // One page, one task: the title already says whose posts these are, "See all" how many.
  document.getElementById("filters").classList.add("hidden");
  if (intent === "need") {
    // Before anything else: this board is not a rescue line.
    document.getElementById("danger").classList.remove("hidden");
    api("/api/status").then((status) => showEmergency(status.emergency)).catch(() => {}); // else 112
  }
}

fillCategories();
applyIntent(INTENT);
load();
