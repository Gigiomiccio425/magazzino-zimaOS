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

  // ---- Posizione di scorrimento ----
  // Dopo un salvataggio che torna alla stessa pagina, la pagina resta dove eri invece di tornare in cima.
  var SCROLL_KEY = "mag-scroll";
  function here() { return window.location.pathname + window.location.search; }
  MAG.rememberScroll = function () {
    try { sessionStorage.setItem(SCROLL_KEY, JSON.stringify({ p: here(), y: window.scrollY, t: Date.now() })); } catch (e) {}
  };
  document.addEventListener("submit", function (e) {
    var method = (e.target.getAttribute && e.target.getAttribute("method") || "get").toLowerCase();
    if (method === "post") MAG.rememberScroll();
  }, true);
  (function restoreScroll() {
    var saved = null;
    try { saved = JSON.parse(sessionStorage.getItem(SCROLL_KEY) || "null"); sessionStorage.removeItem(SCROLL_KEY); } catch (e) {}
    if (!saved || saved.p !== here() || Date.now() - saved.t > 120000 || saved.y < 40) return;
    if ("scrollRestoration" in history) history.scrollRestoration = "manual";
    window.scrollTo(0, saved.y);
    // I messaggi stanno in cima alla pagina, fuori vista: si ripetono come avvisi in basso.
    document.querySelectorAll(".flashes .flash").forEach(function (el) {
      MAG.toast(el.textContent.trim(), el.classList.contains("flash--error") ? "error" : "success");
    });
  })();

  // ---- Invio form via fetch (usato da sign.js): segue {"redirect": url} ----
  MAG.submitForm = function (form, extra) {
    var fd = new FormData(form);
    var sb = form._submitter;
    if (sb && sb.name) fd.append(sb.name, sb.value);
    Object.keys(extra || {}).forEach(function (k) { fd.set(k, extra[k]); });
    var method = (form.getAttribute("method") || "post").toUpperCase();
    return MAG.fetchJSON(form.getAttribute("action") || window.location.pathname, { method: method, body: fd })
      .then(function (r) {
        if (r.data && r.data.redirect) { MAG.rememberScroll(); window.location.assign(r.data.redirect); }
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

  // ---- PWA: service worker (solo in contesto sicuro) ----
  if ("serviceWorker" in navigator && window.isSecureContext) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function () { /* opzionale */ });
    });
  }

  // ---- Sidebar: resta allo stesso punto quando si cambia pagina ----
  var sidebar = document.getElementById("sidebar");
  if (sidebar) {
    var SIDEBAR_KEY = "mag-sidebar-scroll";
    var savedTop = null;
    try { savedTop = sessionStorage.getItem(SIDEBAR_KEY); } catch (e) {}
    if (savedTop !== null) sidebar.scrollTop = parseInt(savedTop, 10) || 0;
    // La voce della pagina aperta deve essere visibile anche arrivando da un link esterno
    var activeLink = sidebar.querySelector(".nav__link.is-active");
    if (activeLink) {
      var r = activeLink.getBoundingClientRect(), box = sidebar.getBoundingClientRect();
      if (r.top < box.top || r.bottom > box.bottom) {
        sidebar.scrollTop += r.top - box.top - (box.height - r.height) / 2;
      }
    }
    var saveSidebar = function () {
      try { sessionStorage.setItem(SIDEBAR_KEY, String(sidebar.scrollTop)); } catch (e) {}
    };
    sidebar.addEventListener("click", function (e) { if (e.target.closest("a")) saveSidebar(); });
    window.addEventListener("pagehide", saveSidebar);
  }

  // ---- Sidebar mobile ----
  var burger = document.getElementById("burger");
  if (burger && sidebar) {
    var setOpen = function (open) {
      sidebar.classList.toggle("is-open", open);
      document.body.classList.toggle("menu-open", open);
      burger.setAttribute("aria-expanded", open ? "true" : "false");
      if (open) { var first = sidebar.querySelector(".nav-close"); if (first) first.focus(); }
    };
    sidebar.addEventListener("click", function (e) {
      if (e.target.closest("[data-close-menu]")) { setOpen(false); burger.focus(); }
    });
    burger.addEventListener("click", function () { setOpen(!sidebar.classList.contains("is-open")); });
    document.addEventListener("click", function (e) {
      if (window.innerWidth <= 1024 && sidebar.classList.contains("is-open")
          && !sidebar.contains(e.target) && e.target !== burger) {
        setOpen(false);
      }
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && sidebar.classList.contains("is-open")) { setOpen(false); burger.focus(); }
    });
    document.addEventListener("click", function (e) {
      if (e.target.closest("[data-open-menu]")) { e.stopPropagation(); setOpen(!sidebar.classList.contains("is-open")); }
    }, true);
  }

  // ---- Ricerca nel menu: filtra le voci; Invio senza voci trovate = ricerca nel magazzino ----
  var navFilter = document.getElementById("nav-filter");
  if (navFilter && sidebar) {
    var norm = function (t) { return (t || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, ""); };
    navFilter.addEventListener("input", function () {
      var q = norm(navFilter.value.trim());
      sidebar.querySelectorAll(".nav .nav__link").forEach(function (a) {
        a.hidden = !!q && norm(a.textContent).indexOf(q) < 0;
      });
      sidebar.querySelectorAll(".nav__group").forEach(function (g) {
        g.hidden = !!q && !g.querySelector(".nav__link:not([hidden])");
      });
    });
    navFilter.addEventListener("keydown", function (e) {
      if (e.key !== "Enter") return;
      e.preventDefault();
      var visible = sidebar.querySelectorAll(".nav .nav__link:not([hidden])");
      var q = navFilter.value.trim();
      if (q && visible.length === 1) window.location.assign(visible[0].href);
      else if (q) window.location.assign("/search?q=" + encodeURIComponent(q));
    });
  }

  // ---- Form con destinazione scelta da una tendina (riserva per progetto, fornitore del pezzo) ----
  document.addEventListener("change", function (e) {
    var sel = e.target.closest("[data-reserve-project], [data-supplier-select]");
    if (sel && sel.form) sel.form.setAttribute("action", sel.value);
  });

  // ---- Senza rete: solo consultazione (pagine già aperte), niente modifiche ----
  var offlineBar = null;
  function setOffline(off) {
    document.body.classList.toggle("is-offline", off);
    if (off && !offlineBar) {
      offlineBar = document.createElement("div");
      offlineBar.className = "offline-bar";
      offlineBar.setAttribute("role", "status");
      offlineBar.textContent = "Senza rete: stai vedendo l'ultima versione salvata di questa pagina. Le modifiche tornano disponibili con la connessione.";
      document.body.insertBefore(offlineBar, document.body.firstChild);
    } else if (!off && offlineBar) {
      offlineBar.remove(); offlineBar = null;
    }
  }
  window.addEventListener("offline", function () { setOffline(true); });
  window.addEventListener("online", function () { setOffline(false); });
  if (navigator.onLine === false) setOffline(true);
  document.addEventListener("submit", function (e) {
    var method = (e.target.getAttribute && e.target.getAttribute("method") || "get").toLowerCase();
    if (method === "post" && navigator.onLine === false) {
      e.preventDefault(); e.stopImmediatePropagation();
      MAG.toast("Senza rete non si possono salvare modifiche. Riprova quando torna la connessione.", "error");
    }
  }, true);

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
