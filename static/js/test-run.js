// Form test: propone l'esito dalle regole del modello (min/max, sì/no). L'operatore sceglie sempre.
(function () {
  "use strict";
  var form = document.getElementById("test-form"), out = document.getElementById("test-suggest");
  if (!form || !out) return;
  function num(v) { var n = parseFloat(String(v).replace(",", ".")); return isNaN(n) ? null : n; }
  function suggest() {
    var evaluated = false, fail = false;
    form.querySelectorAll("[data-rule-min], [data-rule-max]").forEach(function (el) {
      var v = num(el.value), mn = num(el.getAttribute("data-rule-min")), mx = num(el.getAttribute("data-rule-max"));
      if (v === null || (mn === null && mx === null)) return;
      evaluated = true;
      if ((mn !== null && v < mn) || (mx !== null && v > mx)) fail = true;
    });
    form.querySelectorAll("[data-rule-bool]").forEach(function (el) {
      if (!el.value) return;
      evaluated = true;
      if (el.value !== el.getAttribute("data-rule-bool")) fail = true;
    });
    out.textContent = evaluated ? "(suggerito: " + (fail ? "Fallito" : "OK") + ")" : "";
  }
  form.addEventListener("input", suggest);
  form.addEventListener("change", suggest);
})();
