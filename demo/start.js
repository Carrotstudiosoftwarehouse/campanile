// DEVELOPED BY CARROTSTUDIO software house
// Online demo only. Hands the API to the service worker (demo/sw.js) and says clearly, on
// every page, that this is a demo with invented data.
(function () {
  "use strict";

  var TEXT = {
    it: ["Demo: dati inventati, salvati solo in questo browser. Il Campanile vero funziona senza internet, su un portatile o un Raspberry Pi.", "Ricomincia"],
    en: ["Demo: invented data, kept only in this browser. A real Campanile runs without internet, on a laptop or a Raspberry Pi.", "Start over"],
    off: ["This demo needs a browser that allows service workers (not a private window in some browsers).", ""],
  };

  function language() {
    var chosen = null;
    try { chosen = localStorage.getItem("campanile-lang"); } catch (e) { /* no storage */ }
    var tags = chosen ? [chosen] : (navigator.languages || [navigator.language || ""]);
    for (var i = 0; i < tags.length; i++) {
      var code = String(tags[i]).slice(0, 2).toLowerCase();
      if (code === "it" || code === "en") return code;
    }
    return "en";
  }

  function banner(lines) {
    var bar = document.createElement("div");
    bar.setAttribute("role", "note");
    bar.style.cssText = "background:#111;color:#fff;font:14px/1.4 system-ui,sans-serif;padding:8px 16px;text-align:center";
    bar.appendChild(document.createTextNode(lines[0] + " "));
    if (lines[1]) {
      var again = document.createElement("button");
      again.type = "button";
      again.textContent = lines[1];
      again.style.cssText = "background:none;border:1px solid #fff;color:#fff;border-radius:6px;padding:2px 8px;margin-left:4px;font:inherit;cursor:pointer";
      again.addEventListener("click", function () {
        navigator.serviceWorker.controller.postMessage("reset");
        try { localStorage.removeItem("campanile-mine-v1"); } catch (e) { /* nothing to clear */ }
        setTimeout(function () { location.reload(); }, 300);
      });
      bar.appendChild(again);
    }
    document.body.insertBefore(bar, document.body.firstChild);
  }

  function whenReady(fn) {
    if (document.body) fn();
    else document.addEventListener("DOMContentLoaded", fn);
  }

  if (!("serviceWorker" in navigator)) {
    whenReady(function () { banner(TEXT.off); });
    return;
  }
  if (navigator.serviceWorker.controller) {
    try { sessionStorage.removeItem("campanile-demo-reload"); } catch (e) { /* ignore */ }
    whenReady(function () { banner(TEXT[language()]); });
    return;
  }
  // First visit: the pages would ask the API before the worker answers. Hide them, start
  // the worker, then load again under its control (once: no loops if it never takes over).
  var root = document.documentElement;
  root.style.visibility = "hidden";
  var tried = false;
  try { tried = sessionStorage.getItem("campanile-demo-reload") === "1"; } catch (e) { /* ignore */ }
  function giveUp() {
    root.style.visibility = "";
    whenReady(function () { banner(TEXT.off); });
  }
  if (tried) { giveUp(); return; }
  navigator.serviceWorker.register("/demo-sw.js")
    .then(function () { return navigator.serviceWorker.ready; })
    .then(function () {
      try { sessionStorage.setItem("campanile-demo-reload", "1"); } catch (e) { /* ignore */ }
      location.reload();
    })
    .catch(giveUp);
})();
