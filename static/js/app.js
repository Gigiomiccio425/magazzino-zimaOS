// MAGAZZINO — interazioni UI (vanilla JS, nessuna dipendenza esterna)
// Espone window.MAG: csrf, fetchJSON, toast, confirm, info, submitForm.
(function () {
  "use strict";

  var MAG = window.MAG = window.MAG || {};

  // ---- CSRF + fetch ----
  MAG.csrf = function () {
    var m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.getAttribute("content") : "";
  };

  MAG.fetchJSON = function (url, opts) {
    opts = opts || {};
    var headers = { "X-CSRF-Token": MAG.csrf(), "X-Requested-With": "fetch", "Accept": "application/json" };
    var body = opts.body;
    if (body && !(body instanceof FormData) && typeof body !== "string") {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(body);
    }
    return fetch(url, { method: opts.method || "GET", headers: headers, body: body, credentials: "same-origin" })
      .then(function (res) {
        var ct = res.headers.get("content-type") || "";
        var parse = ct.indexOf("application/json") >= 0 ? res.json() : res.text();
        return parse.then(function (data) { return { status: res.status, data: data, url: res.url }; });
      });
  };

  // ---- Toast (messaggi brevi, aria-live) ----
  MAG.toast = function (msg, kind) {
    var box = document.getElementById("toasts");
    if (!box) return;
    var t = document.createElement("div");
    t.className = "flash flash--" + (kind || "success");
    t.textContent = msg;
    box.appendChild(t);
    setTimeout(function () { t.remove(); }, 6000);
  };

  // ---- Dialog di conferma / informazione (sostituisce alert/confirm nativi) ----
  function openDialog(title, msg, okLabel, showCancel, danger) {
    var dlg = document.getElementById("mag-dialog");
    if (!dlg || typeof dlg.showModal !== "function") return Promise.resolve(true);
    document.getElementById("mag-dialog-title").textContent = title;
    document.getElementById("mag-dialog-msg").textContent = msg;
    var ok = document.getElementById("mag-dialog-ok");
    var cancel = document.getElementById("mag-dialog-cancel");
    ok.textContent = okLabel;
    ok.className = "btn " + (danger ? "btn--danger" : "btn--red");
    cancel.hidden = !showCancel;
    dlg.returnValue = "";
    dlg.showModal();
    (showCancel ? cancel : ok).focus();
    return new Promise(function (resolve) {
      dlg.addEventListener("close", function onClose() {
        dlg.removeEventListener("close", onClose);
        resolve(dlg.returnValue === "ok");
      });
    });
  };

  MAG.confirm = function (msg, opts) {
    opts = opts || {};
    return openDialog(opts.title || "Conferma", msg, opts.okLabel || "Conferma", true, !!opts.danger);
  };

  MAG.info = function (msg, title) {
    return openDialog(title || "Attenzione", msg, "OK", false, false);
  };

  // ---- Invio form via fetch (usato da sign.js): segue {"redirect": url} ----
  MAG.submitForm = function (form, extra) {
    var fd = new FormData(form);
    Object.keys(extra || {}).forEach(function (k) { fd.set(k, extra[k]); });
    var method = (form.getAttribute("method") || "post").toUpperCase();
    return MAG.fetchJSON(form.getAttribute("action") || window.location.pathname, { method: method, body: fd })
      .then(function (r) {
        if (r.data && r.data.redirect) { window.location.assign(r.data.redirect); }
        return r;
      });
  };

  // ---- Conferma per form con data-confirm ----
  document.addEventListener("submit", function (e) {
    var form = e.target;
    var msg = form.getAttribute && form.getAttribute("data-confirm");
    if (!msg || form.dataset.confirmed === "1") return;
    e.preventDefault();
    e.stopImmediatePropagation();
    MAG.confirm(msg, { danger: true, okLabel: "Elimina" }).then(function (yes) {
      if (!yes) return;
      form.dataset.confirmed = "1";
      if (typeof form.requestSubmit === "function") form.requestSubmit(); else form.submit();
    });
  }, true);

  // ---- Stampa (etichette) ----
  document.addEventListener("click", function (e) {
    if (e.target.closest("[data-print]")) window.print();
  });

  // ---- Sidebar mobile ----
  var burger = document.getElementById("burger");
  var sidebar = document.getElementById("sidebar");
  if (burger && sidebar) {
    var setOpen = function (open) {
      sidebar.classList.toggle("is-open", open);
      burger.setAttribute("aria-expanded", open ? "true" : "false");
    };
    burger.addEventListener("click", function () { setOpen(!sidebar.classList.contains("is-open")); });
    document.addEventListener("click", function (e) {
      if (window.innerWidth <= 780 && sidebar.classList.contains("is-open")
          && !sidebar.contains(e.target) && e.target !== burger) {
        setOpen(false);
      }
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && sidebar.classList.contains("is-open")) { setOpen(false); burger.focus(); }
    });
  }

  // ---- Auto-dismiss flash ----
  setTimeout(function () {
    document.querySelectorAll(".flashes .flash").forEach(function (f) {
      f.style.transition = "opacity .4s, transform .4s";
      f.style.opacity = "0";
      f.style.transform = "translateY(-8px)";
      setTimeout(function () { f.remove(); }, 400);
    });
  }, 6000);

  // ---- Attributi dinamici (form componente) ----
  var rows = document.getElementById("attr-rows");
  var addBtn = document.getElementById("add-attr");
  var suggestBtn = document.getElementById("suggest-attr");
  var catInput = document.getElementById("category-input");

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
      '<input type="text" name="attr_key" placeholder="Attributo" aria-label="Nome attributo" class="input">' +
      '<input type="text" name="attr_value" placeholder="Valore" aria-label="Valore attributo" class="input">' +
      '<button type="button" class="btn btn--x" aria-label="Rimuovi attributo">&times;</button>';
    if (key) div.children[0].value = key;
    if (value) div.children[1].value = value;
    div.querySelector(".btn--x").addEventListener("click", function () { div.remove(); });
    return div;
  }

  if (rows) {
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
        MAG.info("Nessun attributo suggerito per \"" + (cat || "questa categoria") + "\". Aggiungi righe manuali.");
        return;
      }
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
