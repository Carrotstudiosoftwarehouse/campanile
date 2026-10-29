// DEVELOPED BY CARROTSTUDIO software house
// The plan is meant to be printed: it is never sent to the Campanile and lives only in this tab.
// Every Campanile has the same address, so a fake network with the same name would be the same
// site to the browser and could read anything kept there (tested).
import { api, el, showResult } from "/common.js";
import { showEmergency, t, translatePage } from "/i18n.js";

translatePage();
api("/api/status").then((status) => showEmergency(status.emergency)).catch(() => {}); // else 112

const STORAGE_KEY = "campanile-plan-v1";
const form = document.getElementById("plan");
const members = document.getElementById("members");
const result = document.getElementById("result");

function readSaved() {
  try {
    // A plan saved by an older version: carried over, and removed from the phone's storage.
    const old = localStorage.getItem(STORAGE_KEY);
    if (old !== null) {
      sessionStorage.setItem(STORAGE_KEY, old);
      localStorage.removeItem(STORAGE_KEY);
    }
    return JSON.parse(sessionStorage.getItem(STORAGE_KEY)) || {};
  } catch {
    return {};
  }
}

function memberRow(data = {}) {
  const field = (name, label, max) => {
    const input = el("input", { type: "text", maxlength: String(max), "data-member": name });
    input.value = data[name] || "";
    return el("label", {}, label, input);
  };
  const remove = el("button", { type: "button", class: "secondary", text: t("remove") });
  const row = el("div", { class: "member" },
    field("name", t("plan.person.name"), 80),
    field("phone", t("plan.person.phone"), 40),
    field("health", t("plan.person.health"), 200),
    remove,
  );
  remove.addEventListener("click", () => { row.remove(); save(); });
  return row;
}

function save() {
  const data = { fields: {}, members: [] };
  for (const input of form.querySelectorAll("[data-field]")) {
    data.fields[input.dataset.field] = input.value;
  }
  for (const row of members.querySelectorAll(".member")) {
    const member = {};
    for (const input of row.querySelectorAll("[data-member]")) {
      member[input.dataset.member] = input.value;
    }
    data.members.push(member);
  }
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(data));
    showResult(result, t("plan.saved"));
  } catch {
    showResult(result, t("plan.cantsave"), true);
  }
}

function load() {
  const data = readSaved();
  for (const input of form.querySelectorAll("[data-field]")) {
    input.value = (data.fields || {})[input.dataset.field] || "";
  }
  const saved = Array.isArray(data.members) && data.members.length ? data.members : [{}];
  members.replaceChildren(...saved.map(memberRow));
}

form.addEventListener("input", save);
document.getElementById("add-member").addEventListener("click", () => {
  members.append(memberRow());
});
document.getElementById("print").addEventListener("click", () => window.print());
document.getElementById("clear").addEventListener("click", () => {
  if (!confirm(t("plan.confirm"))) return;
  try { sessionStorage.removeItem(STORAGE_KEY); } catch { /* nothing to do */ }
  load();
  showResult(result, t("plan.cleared"));
});

load();
