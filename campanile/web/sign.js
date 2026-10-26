// DEVELOPED BY CARROTSTUDIO software house
import qrcode from "/vendor/qrcode.mjs";
import { api } from "/common.js";
import { translatePage } from "/i18n.js";

translatePage();

const SVG = "http://www.w3.org/2000/svg";
const NETWORK_KEY = "campanile-network-name";

function drawQr(container, text) {
  const qr = qrcode(0, "M");
  qr.addData(text);
  qr.make();
  const modules = qr.getModuleCount();
  const margin = 4;
  const side = modules + margin * 2;
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", `0 0 ${side} ${side}`);
  svg.setAttribute("shape-rendering", "crispEdges");
  const background = document.createElementNS(SVG, "rect");
  background.setAttribute("width", side);
  background.setAttribute("height", side);
  background.setAttribute("fill", "#fff");
  svg.append(background);
  let d = "";
  for (let row = 0; row < modules; row++) {
    for (let col = 0; col < modules; col++) {
      if (qr.isDark(row, col)) d += `M${col + margin} ${row + margin}h1v1h-1z`;
    }
  }
  const dots = document.createElementNS(SVG, "path");
  dots.setAttribute("d", d);
  dots.setAttribute("fill", "#000");
  svg.append(dots);
  container.replaceChildren(svg);
}

function readNetwork() {
  try { return localStorage.getItem(NETWORK_KEY); } catch { return null; }
}

function saveNetwork(value) {
  try { localStorage.setItem(NETWORK_KEY, value); } catch { /* only on screen then */ }
}

async function start() {
  const input = document.getElementById("network-name");
  const printed = document.getElementById("printed-network");
  input.value = readNetwork() || input.value;
  const update = () => {
    printed.textContent = input.value.trim() || "…";
    saveNetwork(input.value);
  };
  input.addEventListener("input", update);
  update();
  document.getElementById("print").addEventListener("click", () => window.print());

  let address = `${location.origin}/`;
  try {
    const status = await api("/api/status");
    if (status.address) address = status.address;
  } catch {
    // fall back to the page's own address
  }
  document.getElementById("address-text").textContent = address.replace(/\/$/, "");
  drawQr(document.getElementById("qr"), address);
}

start();
