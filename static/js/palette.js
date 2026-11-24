// Palette di ricerca globale: Ctrl+K / Cmd+K (o "/" fuori dai campi), navigazione da tastiera.
(function () {
  "use strict";
  var MAG = window.MAG, dlg = document.getElementById("palette");
  if (!MAG || !dlg) return;
  var input = document.getElementById("palette-input"), list = document.getElementById("palette-list");
  var hits = [], active = -1, timer = null, seq = 0;

  function render(groups) {
    list.innerHTML = "";
    hits = [];
    groups.forEach(function (g) {
      var head = document.createElement("li");
      head.className = "palette__group";
      head.setAttribute("role", "presentation");
      head.textContent = g.label;
      list.appendChild(head);
      g.items.forEach(function (h) {
        var li = document.createElement("li");
        li.id = "palette-opt-" + hits.length;
        li.className = "palette__item";
        li.setAttribute("role", "option");
        li.setAttribute("aria-selected", "false");
        var t = document.createElement("strong"); t.textContent = h.title;
        var s = document.createElement("span"); s.className = "muted"; s.textContent = h.subtitle;
        li.appendChild(t); li.appendChild(s);
        li.addEventListener("click", function () { window.location.assign(h.url); });
        list.appendChild(li);
        hits.push({ el: li, url: h.url });
      });
    });
    if (!hits.length && input.value.trim().length >= 2) {
      var empty = document.createElement("li");
      empty.className = "palette__group";
      empty.textContent = "Nessun risultato";
      list.appendChild(empty);
    }
    input.setAttribute("aria-expanded", hits.length ? "true" : "false");
    select(hits.length ? 0 : -1);
  }

  function select(i) {
    if (active >= 0 && hits[active]) hits[active].el.setAttribute("aria-selected", "false");
    active = i;
    if (active >= 0 && hits[active]) {
      hits[active].el.setAttribute("aria-selected", "true");
      hits[active].el.scrollIntoView({ block: "nearest" });
      input.setAttribute("aria-activedescendant", hits[active].el.id);
    } else {
      input.removeAttribute("aria-activedescendant");
    }
  }

  function search() {
    var q = input.value.trim(), mine = ++seq;
    if (q.length < 2) { render([]); return; }
    MAG.fetchJSON("/search.json?q=" + encodeURIComponent(q)).then(function (r) {
      if (mine === seq && r.data && r.data.groups) render(r.data.groups);
    });
  }

  MAG.openPalette = function () {
    if (dlg.open) return;
    input.value = "";
    render([]);
    dlg.showModal();
    input.focus();
  };

  input.addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(search, 150); });
  input.addEventListener("keydown", function (e) {
    if (e.key === "ArrowDown") { e.preventDefault(); select(Math.min(active + 1, hits.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); select(Math.max(active - 1, 0)); }
    else if (e.key === "Enter") {
      e.preventDefault();
      if (hits[active]) window.location.assign(hits[active].url);
      else if (input.value.trim()) window.location.assign("/search?q=" + encodeURIComponent(input.value.trim()));
    }
  });
  dlg.addEventListener("click", function (e) { if (e.target === dlg) dlg.close(); });

  document.addEventListener("keydown", function (e) {
    var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName) || document.activeElement.isContentEditable;
    if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")) { e.preventDefault(); MAG.openPalette(); }
    else if (e.key === "/" && !typing && !document.querySelector("dialog[open]")) { e.preventDefault(); MAG.openPalette(); }
  });
  document.addEventListener("click", function (e) {
    if (e.target.closest("[data-open-palette]")) { e.preventDefault(); MAG.openPalette(); }
  });
})();
