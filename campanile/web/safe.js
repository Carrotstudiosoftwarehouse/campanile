// DEVELOPED BY CARROTSTUDIO software house
import { api, el, when, showResult, showMine, rememberMine } from "/common.js";
import { t, tn, translatePage } from "/i18n.js";

translatePage();

const MINE = { kind: "safe", path: "/api/safe/remove", button: "safe.remove.one" };
const FIRST = 5;  // results shown before "See all"
showMine(MINE);

document.getElementById("search-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const result = document.getElementById("search-result");
  const results = document.getElementById("results");
  const q = document.getElementById("q").value;
  try {
    const { results: found } = await api("/api/safe?q=" + encodeURIComponent(q));
    const cards = found.map((p) =>
      el("article", { class: "post offer" },
        el("strong", { text: p.name }),
        p.message ? el("p", { text: p.message }) : null,
        p.place ? el("div", { class: "meta", text: t("safe.where", { place: p.place }) }) : null,
        el("div", { class: "meta", text: t("safe.registered", { when: when(p.created) }) }),
      ));
    results.replaceChildren(...cards.slice(0, FIRST));
    if (cards.length > FIRST) {
      const all = el("button", { type: "button", class: "secondary", text: t("board.all", { n: cards.length }) });
      all.addEventListener("click", () => results.replaceChildren(...cards));
      results.append(all);
    }
    showResult(result, found.length ? tn("safe.results", found.length) : t("safe.noresults"));
  } catch (error) {
    results.replaceChildren();
    showResult(result, error.message, true);
  }
});

document.getElementById("safe-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.submitter || event.target.querySelector("button[type=submit]");
  const result = document.getElementById("safe-result");
  button.disabled = true;
  try {
    const response = await api("/api/safe", {
      name: document.getElementById("name").value,
      message: document.getElementById("message").value,
      place: document.getElementById("place").value,
    });
    rememberMine("safe", response, document.getElementById("name").value);
    showMine(MINE);
    document.getElementById("receipt-id").textContent = response.id;
    document.getElementById("receipt-code").textContent = response.code;
    document.getElementById("receipt").classList.remove("hidden");
    event.target.reset();
    showResult(result, "");
    document.getElementById("receipt").scrollIntoView({ behavior: "smooth" });
  } catch (error) {
    showResult(result, error.message, true);
  } finally {
    button.disabled = false;
  }
});

document.getElementById("remove-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const result = document.getElementById("remove-result");
  try {
    await api("/api/safe/remove", {
      id: document.getElementById("remove-id").value,
      code: document.getElementById("remove-code").value,
    });
    showResult(result, t("safe.removed"));
    event.target.reset();
  } catch (error) {
    showResult(result, error.message, true);
  }
});
