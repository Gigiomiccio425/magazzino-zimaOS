// Form componente: mostra i campi tipizzati della categoria scelta e i campi scorta solo per articoli a quantita'.
(function () {
  "use strict";
  var form = document.getElementById("component-form");
  if (!form) return;
  var cat = document.getElementById("category-input");
  var hint = document.getElementById("typed-hint");

  function syncCategory() {
    var name = (cat.value || "").trim(), found = false;
    form.querySelectorAll(".typed-group").forEach(function (g) {
      var on = g.getAttribute("data-category") === name;
      found = found || on;
      g.hidden = !on;
      g.querySelectorAll("input, select, textarea").forEach(function (el) { el.disabled = !on; });
    });
    if (hint) hint.textContent = found ? "(" + name + ")" : name ? "(nessun campo predefinito per questa categoria)" : "(scegli una categoria)";
  }

  function syncTracking() {
    var checked = form.querySelector('input[name="tracking"]:checked');
    var isQty = checked && checked.value === "quantity";
    form.querySelectorAll('[data-tracking="quantity"]').forEach(function (el) {
      el.hidden = !isQty && el.querySelector('[name="quantity"]') === null;
      if (el.querySelector('[name="quantity"]')) {
        el.querySelector("input").readOnly = !isQty;
        if (!isQty) el.querySelector("input").value = 1;
      }
    });
  }

  if (cat) { cat.addEventListener("input", syncCategory); cat.addEventListener("change", syncCategory); syncCategory(); }
  form.querySelectorAll('input[name="tracking"]').forEach(function (r) { r.addEventListener("change", syncTracking); });
  syncTracking();
})();
