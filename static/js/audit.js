// Inventario fisico: ogni scansione viene segnata subito sul server.
(function () {
  "use strict";
  var MAG = window.MAG, box = document.querySelector(".audit-scan");
  if (!box || !MAG) return;
  var id = box.getAttribute("data-audit-id"), last = document.getElementById("audit-last");
  var LABELS = { found: "trovato ✓", unexpected: "fuori posto", unknown: "non riconosciuto", closed: "inventario chiuso" };
  var changed = false;

  function mark(value) {
    return MAG.fetchJSON("/audits/" + id + "/scan", { method: "POST", body: { value: value } }).then(function (r) {
      if (r.status === 428) {
        return MAG.openSign({}).then(function (ok) { if (ok) return mark(value); });
      }
      var d = r.data || {};
      var text = (d.component ? d.component + " (" + d.tag + ")" : value) + " — " + (LABELS[d.state] || d.state);
      last.textContent = text;
      if (d.state === "found" || d.state === "unexpected") changed = true;
      return text;
    });
  }

  document.getElementById("audit-scan-btn").addEventListener("click", function () {
    MAG.scan({ continuous: true, onEach: mark, onDone: function () { if (changed) window.location.reload(); } });
  });
  document.getElementById("audit-manual").addEventListener("submit", function (e) {
    e.preventDefault();
    var input = document.getElementById("audit-code");
    if (!input.value.trim()) return;
    mark(input.value.trim()).then(function () { window.location.reload(); });
  });
})();
