// DEVELOPED BY CARROTSTUDIO software house
// Finding a street, a town or the nearest pharmacy in the maps, without internet. Shared by
// the map page and the setup page: one box, a few big buttons, a list to tap.
import { api } from "/common.js";
import { distance, has, t } from "/i18n.js";

const WAIT = 250; // ms after the last key before searching
const RETRY = 2000; // while the Campanile is still reading the maps
const CHIPS = ["hospital", "pharmacy", "water", "police"];

// What a result is, in words: "Pharmacy", "Street", "Village"...
export function label(result) {
  if (result.type === "street") return t("place.street");
  for (const key of [result.detail, result.kind]) {
    if (key && has(`place.${key}`)) return t(`place.${key}`);
  }
  return "";
}

// The name, or what it is for a place without one: most drinking fountains.
export function title(result) {
  return result.name || label(result);
}

// "Pharmacy · San Salvario": what it is and where, for the list and the map.
export function describe(result) {
  return [result.name && label(result), result.near].filter(Boolean).join(" · ");
}

// Options: input and results are elements; chips may be null; center() is [lon, lat] or
// null; pick(result) is called when one is chosen.
export function attachSearch({ input, results, chips, center, pick }) {
  let timer = null;
  let asked = 0; // only the answer to the last question is shown
  let shown = [];

  function close() {
    results.classList.add("hidden");
    results.replaceChildren();
  }

  function say(text) {
    const p = document.createElement("p");
    p.textContent = text;
    results.replaceChildren(p);
    results.classList.remove("hidden");
  }

  function choose(result) {
    close();
    input.blur();
    pick(result);
  }

  function show(found) {
    shown = found;
    const rows = found.map((result) => {
      const button = document.createElement("button");
      button.type = "button";
      const name = document.createElement("strong");
      name.textContent = result.local ? `${result.name} (${result.local})` : title(result);
      const about = document.createElement("span");
      const far = result.meters === undefined ? "" : distance(result.meters);
      about.textContent = [describe(result), far].filter(Boolean).join(" · ");
      button.append(name, about);
      button.addEventListener("click", () => choose(result));
      return button;
    });
    if (found.some((r) => r.meters !== undefined)) {
      const note = document.createElement("p");
      note.className = "note-line";
      note.textContent = t("search.from");
      rows.push(note);
    }
    results.replaceChildren(...rows);
    results.classList.remove("hidden");
  }

  async function run(query) {
    const mine = ++asked;
    const here = center();
    const near = here ? `&near=${here.map((v) => v.toFixed(5)).join(",")}` : "";
    let answer;
    try {
      answer = await api(`/api/places?q=${encodeURIComponent(query)}${near}`);
    } catch (error) {
      if (mine === asked) say(error.message);
      return;
    }
    if (mine !== asked) return;
    if (answer.results.length) show(answer.results);
    else if (!answer.ready) {
      say(t("search.wait"));
      timer = setTimeout(() => run(query), RETRY);
    } else say(answer.missing ? t("search.missing") : t("search.none"));
  }

  input.addEventListener("input", () => {
    clearTimeout(timer);
    const query = input.value.trim();
    if (query.length < 2) {
      asked++;
      close();
      return;
    }
    timer = setTimeout(() => run(query), WAIT);
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      close();
    } else if (event.key === "Enter") {
      event.preventDefault(); // the box is in a form: no page reload
      if (shown.length && !results.classList.contains("hidden")) choose(shown[0]);
    }
  });

  if (chips) {
    chips.replaceChildren(...CHIPS.map((chip) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "secondary";
      button.textContent = t(`search.chip.${chip}`);
      button.addEventListener("click", () => {
        input.value = t(`search.q.${chip}`);
        clearTimeout(timer);
        run(input.value);
      });
      return button;
    }));
  }
}
