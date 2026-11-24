// Scanner codici a barre / QR con la fotocamera.
// BarcodeDetector nativo (Chrome Android) oppure ponyfill zxing-wasm locale (iOS Safari, Firefox).
// Richiede HTTPS (o localhost). Modalita' singola e a raffica. Nessuna CDN: il .wasm e' servito dall'app.
(function () {
  "use strict";
  var MAG = window.MAG = window.MAG || {};
  var WASM_DIR = "/static/vendor/zxing/";
  var FORMATS = ["qr_code", "code_128", "code_39", "ean_13", "ean_8", "upc_a", "data_matrix"];

  function support() {
    if (!window.isSecureContext) {
      return "Fotocamera bloccata: l'app è aperta in HTTP.\nApri l'indirizzo HTTPS e riprova, oppure scrivi il codice a mano.";
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      return "Fotocamera non disponibile su questo dispositivo.";
    }
    if (!("BarcodeDetector" in window) && !window.BarcodeDetectionAPI) {
      return "Scanner non disponibile in questo browser: scrivi il codice a mano.";
    }
    return null;
  }

  var detectorPromise = null;
  function getDetector() {
    if (detectorPromise) return detectorPromise;
    detectorPromise = Promise.resolve().then(function () {
      if ("BarcodeDetector" in window) return new window.BarcodeDetector();
      var api = window.BarcodeDetectionAPI;
      api.prepareZXingModule({
        overrides: { locateFile: function (path, prefix) { return path.endsWith(".wasm") ? WASM_DIR + path : prefix + path; } },
        fireImmediately: true
      });
      return new api.BarcodeDetector({ formats: FORMATS });
    });
    return detectorPromise;
  }

  function beep() {
    if (navigator.vibrate) navigator.vibrate(90);
    try {
      var Ctx = window.AudioContext || window.webkitAudioContext, ctx = new Ctx(), o = ctx.createOscillator();
      o.frequency.value = 880; o.connect(ctx.destination); o.start(); o.stop(ctx.currentTime + 0.08);
    } catch (e) { /* audio non disponibile */ }
  }

  var ui = null;
  function buildUI(continuous) {
    var dlg = document.createElement("dialog");
    dlg.className = "mag-dialog scanner-dialog";
    dlg.setAttribute("aria-label", "Scanner codici");
    dlg.innerHTML =
      '<div class="scanner-box">' +
      '  <div class="scanner-head"><h2 class="scanner-title">' + (continuous ? "Scansione a raffica" : "Scansiona codice") + '</h2>' +
      '    <button type="button" class="scanner-close btn btn--ghost btn--sm" aria-label="Chiudi scanner">Chiudi</button></div>' +
      '  <div class="scanner-view"><video class="scanner-video" playsinline muted></video><div class="scanner-reticle"></div></div>' +
      '  <p class="scanner-status" aria-live="polite">Avvio fotocamera…</p>' +
      '  <form class="scanner-manual" data-nosign><label class="sr-only" for="scan-manual">Codice a mano</label>' +
      '    <input id="scan-manual" class="input" placeholder="…oppure scrivi il codice" autocomplete="off" enterkeyhint="go">' +
      '    <button type="submit" class="btn btn--black btn--sm">OK</button></form>' +
      (continuous ? '  <ol class="scanner-list" aria-label="Codici letti"></ol>' +
        '  <div class="scanner-actions"><button type="button" class="btn btn--red scanner-done">Fine</button></div>' : "") +
      '</div>';
    document.body.appendChild(dlg);
    return {
      dlg: dlg, video: dlg.querySelector("video"), status: dlg.querySelector(".scanner-status"),
      list: dlg.querySelector(".scanner-list"), manual: dlg.querySelector(".scanner-manual"),
      done: dlg.querySelector(".scanner-done"), close: dlg.querySelector(".scanner-close")
    };
  }

  // MAG.scan({continuous, onResult(value), onEach(value) -> Promise<label>, onDone(values)})
  MAG.scan = function (opts) {
    opts = opts || {};
    var problem = support();
    var running = true, stream = null, raf = null, lastValue = "", lastAt = 0, values = [];
    ui = buildUI(!!opts.continuous);
    ui.dlg.showModal();

    function stop() {
      running = false;
      if (raf) cancelAnimationFrame(raf);
      if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
      if (ui && ui.dlg.open) ui.dlg.close();
      if (ui) ui.dlg.remove();
      ui = null;
    }

    function accept(value) {
      value = (value || "").trim();
      if (!value) return;
      var now = Date.now();
      if (value === lastValue && now - lastAt < 2000) return; // anti-doppione
      lastValue = value; lastAt = now;
      beep();
      if (!opts.continuous) { stop(); if (opts.onResult) opts.onResult(value); return; }
      values.push(value);
      var li = document.createElement("li");
      li.textContent = value;
      ui.list.prepend(li);
      ui.status.textContent = "Letti: " + values.length;
      if (opts.onEach) {
        Promise.resolve(opts.onEach(value)).then(function (label) { if (label) li.textContent = label; });
      }
    }

    ui.close.addEventListener("click", function () { stop(); });
    ui.dlg.addEventListener("cancel", function () { stop(); });
    ui.manual.addEventListener("submit", function (e) {
      e.preventDefault();
      var input = ui.manual.querySelector("input");
      accept(input.value);
      if (ui) { input.value = ""; input.focus(); }
    });
    if (ui.done) ui.done.addEventListener("click", function () { var v = values.slice(); stop(); if (opts.onDone) opts.onDone(v); });

    if (problem) { ui.status.textContent = problem; ui.manual.querySelector("input").focus(); return; }

    Promise.all([getDetector(), navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } } })])
      .then(function (res) {
        var detector = res[0];
        stream = res[1];
        if (!running) { stream.getTracks().forEach(function (t) { t.stop(); }); return; }
        ui.video.srcObject = stream;
        return ui.video.play().then(function () {
          ui.status.textContent = opts.continuous ? "Inquadra i codici uno dopo l'altro…" : "Inquadra il codice a barre o QR…";
          var last = 0;
          function tick(ts) {
            if (!running) return;
            if (ts - last > 180 && ui.video.readyState >= 2) {
              last = ts;
              detector.detect(ui.video).then(function (codes) {
                if (running && codes && codes.length) accept(codes[0].rawValue);
              }).catch(function () { /* frame non pronto */ });
            }
            raf = requestAnimationFrame(tick);
          }
          raf = requestAnimationFrame(tick);
        });
      })
      .catch(function (err) {
        if (ui) ui.status.textContent = "Fotocamera non disponibile (" + (err && err.name || "errore") + "). Scrivi il codice a mano.";
      });
  };

  MAG.resolveScan = function (value) {
    return MAG.fetchJSON("/scan/resolve?v=" + encodeURIComponent(value)).then(function (r) { return r.data; });
  };

  // ---- Aggancio ai pulsanti ----
  // [data-scan-target="campo"] riempie l'input del form; [data-scan-search] apre la scheda o cerca;
  // [data-scan-batch] scansione a raffica: le schede trovate vengono selezionate per la modifica di massa.
  document.addEventListener("click", function (e) {
    var t = e.target.closest("[data-scan-target]");
    if (t) {
      e.preventDefault();
      var input = t.closest("form").querySelector('[name="' + t.getAttribute("data-scan-target") + '"]');
      MAG.scan({ onResult: function (v) {
        if (input) { input.value = v; input.dispatchEvent(new Event("input", { bubbles: true })); input.focus(); }
      } });
      return;
    }
    if (e.target.closest("[data-scan-search]")) {
      e.preventDefault();
      MAG.scan({ onResult: function (v) {
        MAG.resolveScan(v).then(function (r) { window.location.assign(r.url || r.search); });
      } });
      return;
    }
    if (e.target.closest("[data-scan-batch]")) {
      e.preventDefault();
      var ids = [];
      MAG.scan({
        continuous: true,
        onEach: function (v) {
          return MAG.resolveScan(v).then(function (r) {
            var m = r.url && r.url.match(/^\/components\/(\d+)$/);
            if (m) { ids.push(m[1]); return v + " ✓"; }
            return v + " — non trovato";
          });
        },
        onDone: function () {
          if (ids.length && MAG.bulkSelect) MAG.bulkSelect(ids);
          else if (ids.length) MAG.toast(ids.length + " componenti letti.");
        }
      });
    }
  });
})();
