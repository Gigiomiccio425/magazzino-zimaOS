// MAGAZZINO — interazioni UI (vanilla JS, nessuna dipendenza esterna)
(function () {
  "use strict";

  // ---- Nav: evidenzia link attivo ----
  var path = window.location.pathname;
  document.querySelectorAll(".nav__link").forEach(function (a) {
    var match = a.getAttribute("data-match");
    if (match === "/" ? path === "/" : path.indexOf(match) === 0) {
      a.classList.add("is-active");
    }
  });

  // ---- Sidebar mobile ----
  var burger = document.getElementById("burger");
  var sidebar = document.getElementById("sidebar");
  if (burger && sidebar) {
    burger.addEventListener("click", function () {
      sidebar.classList.toggle("is-open");
    });
    document.addEventListener("click", function (e) {
      if (window.innerWidth <= 780 && sidebar.classList.contains("is-open")
          && !sidebar.contains(e.target) && e.target !== burger) {
        sidebar.classList.remove("is-open");
      }
    });
  }

  // ---- Auto-dismiss flash ----
  setTimeout(function () {
    document.querySelectorAll(".flash").forEach(function (f) {
      f.style.transition = "opacity .4s, transform .4s";
      f.style.opacity = "0";
      f.style.transform = "translateY(-8px)";
      setTimeout(function () { f.remove(); }, 400);
    });
  }, 4500);

  // ---- Attributi dinamici (form componente) ----
  var rows = document.getElementById("attr-rows");
  var addBtn = document.getElementById("add-attr");
  var suggestBtn = document.getElementById("suggest-attr");
  var catInput = document.getElementById("category-input");

  // Chiavi suggerite per categoria
  var CATEGORY_ATTRS = {
    "RAM": ["Capacita (GB)", "Tipo", "Velocita (MHz)", "Form factor"],
    "SSD": ["Capacita (GB)", "Interfaccia", "Form factor", "TBW"],
    "HDD": ["Capacita (GB)", "Interfaccia", "RPM", "Form factor"],
    "CPU": ["Socket", "Core", "Thread", "Frequenza (GHz)", "TDP"],
    "GPU": ["VRAM (GB)", "Chipset", "Interfaccia", "TDP"],
    "Scheda madre": ["Socket", "Chipset", "Form factor", "Slot RAM"],
    "Alimentatore": ["Potenza (W)", "Certificazione", "Modulare"],
    "Scheda di rete": ["Velocita", "Interfaccia", "Porte"],
    "Ventola": ["Dimensione (mm)", "Connettore", "RPM"]
  };

  function makeRow(key, value) {
    var div = document.createElement("div");
    div.className = "attr-row";
    div.innerHTML =
      '<input type="text" name="attr_key" placeholder="Attributo" class="input">' +
      '<input type="text" name="attr_value" placeholder="Valore" class="input">' +
      '<button type="button" class="btn btn--x">&times;</button>';
    if (key) div.children[0].value = key;
    if (value) div.children[1].value = value;
    div.querySelector(".btn--x").addEventListener("click", function () { div.remove(); });
    return div;
  }

  if (rows) {
    // Collega bottoni rimozione righe gia presenti (render server)
    rows.querySelectorAll(".attr-row .btn--x").forEach(function (b) {
      b.addEventListener("click", function () { b.parentElement.remove(); });
    });
  }
  if (addBtn && rows) {
    addBtn.addEventListener("click", function () { rows.appendChild(makeRow()); });
  }
  if (suggestBtn && rows) {
    suggestBtn.addEventListener("click", function () {
      var cat = catInput ? (catInput.value || "").trim() : "";
      var keys = CATEGORY_ATTRS[cat];
      if (!keys) {
        alert("Nessun attributo suggerito per \"" + (cat || "questa categoria") + "\". Aggiungi righe manuali.");
        return;
      }
      // Chiavi gia presenti (evita duplicati)
      var existing = {};
      rows.querySelectorAll('input[name="attr_key"]').forEach(function (i) {
        existing[i.value.trim().toLowerCase()] = true;
      });
      keys.forEach(function (k) {
        if (!existing[k.toLowerCase()]) rows.appendChild(makeRow(k, ""));
      });
    });
  }
})();
