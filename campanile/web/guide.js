// DEVELOPED BY CARROTSTUDIO software house
import { api } from "/common.js";
import { showEmergency, translatePage } from "/i18n.js";

translatePage();
api("/api/status").then((status) => showEmergency(status.emergency)).catch(() => {}); // else 112
document.getElementById("print").addEventListener("click", () => window.print());
