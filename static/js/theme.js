// Tema chiaro/scuro: applicato subito (script nel <head>) per evitare il lampo di colore.
(function () {
  "use strict";
  var KEY = "mag-theme", root = document.documentElement;
  try { var saved = localStorage.getItem(KEY); if (saved) root.setAttribute("data-theme", saved); } catch (e) { /* storage non disponibile */ }

  function current() {
    var t = root.getAttribute("data-theme");
    if (t) return t;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  document.addEventListener("DOMContentLoaded", function () {
    var btn = document.getElementById("theme-toggle");
    if (!btn) return;
    function label() {
      var dark = current() === "dark";
      btn.textContent = dark ? "Tema chiaro" : "Tema scuro";
      btn.setAttribute("aria-pressed", dark ? "true" : "false");
    }
    btn.addEventListener("click", function () {
      var next = current() === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try { localStorage.setItem(KEY, next); } catch (e) { /* ignora */ }
      label();
    });
    label();
  });
})();
