// Lista componenti: selezione multipla (anche da scansione a raffica) e azioni di massa.
(function () {
  "use strict";
  var MAG = window.MAG, bar = document.getElementById("bulk-bar");
  if (!bar) return;
  var boxes = function () { return Array.prototype.slice.call(document.querySelectorAll(".bulk-check")); };
  var countEl = document.getElementById("bulk-count");
  var all = document.getElementById("bulk-all");

  function selected() { return boxes().filter(function (b) { return b.checked; }).map(function (b) { return b.value; }); }

  function refresh() {
    var n = selected().length;
    bar.hidden = n === 0;
    countEl.textContent = n + (n === 1 ? " selezionato" : " selezionati");
    var label = document.getElementById("bulk-labels");
    if (label) label.href = "/labels?components=" + selected().join(",");
  }

  // copia gli id selezionati nei form di massa prima dell'invio (prima di sign.js)
  document.querySelectorAll(".bulk-form").forEach(function (form) {
    form.addEventListener("submit", function () {
      form.querySelectorAll('input[name="ids"]').forEach(function (i) { i.remove(); });
      selected().forEach(function (id) {
        var i = document.createElement("input");
        i.type = "hidden"; i.name = "ids"; i.value = id;
        form.appendChild(i);
      });
    }, true);
  });

  var action = document.getElementById("bulk-action");
  function syncAction() {
    document.querySelectorAll("[data-bulk-for]").forEach(function (el) {
      var on = el.getAttribute("data-bulk-for") === action.value;
      el.hidden = !on;
      el.querySelectorAll("input, select").forEach(function (i) { i.disabled = !on; });
    });
  }
  if (action) { action.addEventListener("change", syncAction); syncAction(); }

  document.addEventListener("change", function (e) {
    if (e.target === all) boxes().forEach(function (b) { b.checked = all.checked; });
    if (e.target === all || e.target.classList.contains("bulk-check")) refresh();
  });

  MAG.bulkSelect = function (ids) {
    var found = 0;
    boxes().forEach(function (b) { if (ids.indexOf(b.value) >= 0) { b.checked = true; found++; } });
    refresh();
    MAG.toast(found + " componenti selezionati dalla scansione" + (found < ids.length ? " (alcuni non sono in questa lista)" : "") + ".");
  };
  refresh();
})();
