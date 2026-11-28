// Nuovo componente: ricerca tra i modelli pronti. Un clic apre il modulo già compilato.
(function () {
  "use strict";
  var MAG = window.MAG, input = document.getElementById("preset-q"), list = document.getElementById("preset-results");
  if (!input || !list) return;
  var timer = null, lastQ = null;

  function render(items, q) {
    list.textContent = "";
    if (!q) return;
    if (!items.length) {
      var none = document.createElement("li");
      none.className = "preset-results__empty";
      none.textContent = "Nessun modello trovato. Puoi scansionare l'etichetta o compilare a mano.";
      list.appendChild(none);
      return;
    }
    items.forEach(function (p) {
      var li = document.createElement("li");
      var a = document.createElement("a");
      a.href = "/components/new?preset=" + encodeURIComponent(p.id);
      a.className = "preset-result";
      var name = document.createElement("span");
      name.className = "preset-result__name";
      name.textContent = p.name;
      var meta = document.createElement("span");
      meta.className = "preset-result__meta mono";
      meta.textContent = [p.part, p.category].filter(Boolean).join(" · ");
      a.appendChild(name); a.appendChild(meta);
      li.appendChild(a);
      list.appendChild(li);
    });
  }

  function lookup() {
    var q = input.value.trim();
    if (q === lastQ) return;
    lastQ = q;
    if (!q) { render([], ""); return; }
    MAG.fetchJSON("/presets?q=" + encodeURIComponent(q)).then(function (r) {
      if (input.value.trim() === q) render(Array.isArray(r.data) ? r.data : [], q);
    });
  }

  input.addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(lookup, 180); });
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter") {
      e.preventDefault();
      var first = list.querySelector("a");
      if (first) window.location.assign(first.href);
    }
  });
})();
