// Scanner codici a barre / QR con la fotocamera.
// BarcodeDetector nativo (Chrome Android) oppure ponyfill zxing-wasm locale (iOS Safari, Firefox).
// Richiede HTTPS (o localhost). Modalita' singola e a raffica. Nessuna CDN: il .wasm e' servito dall'app.
//
// Codici vicini (QR e codice a barre sulla stessa etichetta): se nell'inquadratura ce n'e' piu' di uno,
// lo scanner si ferma, li evidenzia e chiede quale usare (tocco sul riquadro o sulla lista).
(function () {
  "use strict";
  var MAG = window.MAG = window.MAG || {};
  var WASM_DIR = "/static/vendor/zxing/";
  var FORMATS = ["qr_code", "data_matrix", "code_128", "code_39", "code_93", "ean_13", "ean_8", "upc_a", "upc_e", "itf"];
  var FORMAT_LABELS = { qr_code: "QR", data_matrix: "DataMatrix", code_128: "Code 128", code_39: "Code 39",
    code_93: "Code 93", ean_13: "EAN-13", ean_8: "EAN-8", upc_a: "UPC-A", upc_e: "UPC-E", itf: "ITF" };
  var GATHER_MS = 350; // dopo la prima lettura si aspetta un attimo per vedere se ci sono altri codici vicini

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

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function formatLabel(code) { return FORMAT_LABELS[code.format] || "Codice"; }

  function buildUI(continuous, title) {
    var dlg = el("dialog", "mag-dialog scanner-dialog");
    dlg.setAttribute("aria-label", "Scanner codici");
    dlg.innerHTML =
      '<div class="scanner-box">' +
      '  <div class="scanner-head"><h2 class="scanner-title"></h2>' +
      '    <button type="button" class="scanner-close btn btn--outline btn--sm" aria-label="Chiudi scanner">Chiudi</button></div>' +
      '  <div class="scanner-view"><video class="scanner-video" playsinline muted></video>' +
      '    <div class="scanner-reticle" aria-hidden="true"></div><div class="scanner-boxes"></div>' +
      '    <div class="scanner-tools">' +
      '      <button type="button" class="scanner-tool scanner-torch" aria-pressed="false" hidden>Torcia</button>' +
      '      <label class="scanner-tool scanner-zoom" hidden>Zoom <input type="range" min="1" max="1" step="0.1" value="1"></label>' +
      '    </div></div>' +
      '  <p class="scanner-status" aria-live="polite">Avvio fotocamera…</p>' +
      '  <div class="scanner-choices" hidden><p class="scanner-choices__title">Più codici vicini: tocca quello giusto</p>' +
      '    <ul class="scanner-choice-list"></ul>' +
      '    <button type="button" class="btn btn--outline btn--sm scanner-again">Riprova a inquadrare</button></div>' +
      '  <form class="scanner-manual" data-nosign><label class="sr-only" for="scan-manual">Codice a mano</label>' +
      '    <input id="scan-manual" class="input" placeholder="…oppure scrivi il codice" autocomplete="off" enterkeyhint="go">' +
      '    <button type="submit" class="btn btn--black btn--sm">OK</button></form>' +
      (continuous ? '  <ol class="scanner-list" aria-label="Codici letti"></ol>' +
        '  <div class="scanner-actions"><button type="button" class="btn btn--red scanner-done">Fine</button></div>' : "") +
      '</div>';
    dlg.querySelector(".scanner-title").textContent = title || (continuous ? "Scansione a raffica" : "Scansiona codice");
    document.body.appendChild(dlg);
    var q = function (s) { return dlg.querySelector(s); };
    return {
      dlg: dlg, video: q("video"), status: q(".scanner-status"), boxes: q(".scanner-boxes"),
      list: q(".scanner-list"), manual: q(".scanner-manual"), done: q(".scanner-done"), close: q(".scanner-close"),
      choices: q(".scanner-choices"), choiceList: q(".scanner-choice-list"), again: q(".scanner-again"),
      torch: q(".scanner-torch"), zoom: q(".scanner-zoom"), zoomInput: q(".scanner-zoom input"), view: q(".scanner-view")
    };
  }

  // Riquadro del codice dalle coordinate del video a quelle mostrate (video in object-fit: cover)
  function toView(ui, box) {
    var vw = ui.video.videoWidth, vh = ui.video.videoHeight, cw = ui.view.clientWidth, ch = ui.view.clientHeight;
    if (!vw || !vh || !box) return null;
    var scale = Math.max(cw / vw, ch / vh), dx = (cw - vw * scale) / 2, dy = (ch - vh * scale) / 2;
    return { left: box.x * scale + dx, top: box.y * scale + dy, width: box.width * scale, height: box.height * scale };
  }

  // MAG.scan({continuous, title, onResult(value), onEach(value) -> Promise<label>, onDone(values)})
  MAG.scan = function (opts) {
    opts = opts || {};
    var problem = support();
    var running = true, paused = false, stream = null, raf = null, lastValue = "", lastAt = 0, values = [];
    var gathering = null; // {until, codes: {value: code}}
    var ui = buildUI(!!opts.continuous, opts.title);
    ui.dlg.showModal();

    function stop() {
      running = false;
      if (raf) cancelAnimationFrame(raf);
      if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
      if (ui.dlg.open) ui.dlg.close();
      ui.dlg.remove();
    }

    function clearBoxes() { ui.boxes.textContent = ""; }

    function accept(value) {
      value = (value || "").trim();
      if (!value) return;
      var now = Date.now();
      if (value === lastValue && now - lastAt < 2000) return; // anti-doppione
      lastValue = value; lastAt = now;
      beep();
      if (!opts.continuous) { stop(); if (opts.onResult) opts.onResult(value); return; }
      values.push(value);
      var li = el("li", null, value);
      ui.list.prepend(li);
      ui.status.textContent = "Letti: " + values.length;
      if (opts.onEach) {
        Promise.resolve(opts.onEach(value)).then(function (label) { if (label) li.textContent = label; });
      }
    }

    function showChoices(codes) {
      paused = true;
      clearBoxes();
      ui.choiceList.textContent = "";
      ui.reticleHidden = true;
      ui.view.classList.add("is-choosing");
      codes.forEach(function (code, i) {
        var n = String(i + 1);
        var r = toView(ui, code.boundingBox);
        if (r) {
          var b = el("button", "scanner-hit");
          b.type = "button";
          b.style.left = r.left + "px"; b.style.top = r.top + "px";
          b.style.width = Math.max(r.width, 28) + "px"; b.style.height = Math.max(r.height, 28) + "px";
          b.setAttribute("aria-label", "Usa il codice " + n + ": " + formatLabel(code) + " " + code.rawValue);
          b.appendChild(el("span", "scanner-hit__n", n));
          b.addEventListener("click", function () { choose(code.rawValue); });
          ui.boxes.appendChild(b);
        }
        var li = el("li");
        var btn = el("button", "scanner-choice");
        btn.type = "button";
        btn.appendChild(el("span", "scanner-choice__n", n));
        btn.appendChild(el("span", "scanner-choice__kind", formatLabel(code)));
        btn.appendChild(el("span", "scanner-choice__value", code.rawValue));
        btn.addEventListener("click", function () { choose(code.rawValue); });
        li.appendChild(btn);
        ui.choiceList.appendChild(li);
      });
      ui.choices.hidden = false;
      ui.status.textContent = codes.length + " codici trovati.";
      var first = ui.choiceList.querySelector("button");
      if (first) first.focus();
    }

    function resume() {
      paused = false; gathering = null;
      ui.choices.hidden = true;
      ui.view.classList.remove("is-choosing");
      clearBoxes();
      ui.status.textContent = "Inquadra il codice a barre o QR…";
    }

    function choose(value) {
      if (opts.continuous) { accept(value); resume(); } else { accept(value); }
    }

    function handle(codes, now) {
      if (paused || !codes || !codes.length) return;
      if (opts.continuous) { codes.forEach(function (c) { accept(c.rawValue); }); return; }
      if (!gathering) gathering = { until: now + GATHER_MS, codes: {} };
      codes.forEach(function (c) { gathering.codes[c.rawValue] = c; });
      if (now < gathering.until) return;
      var found = Object.keys(gathering.codes).map(function (k) { return gathering.codes[k]; });
      gathering = null;
      if (found.length === 1) accept(found[0].rawValue); else showChoices(found);
    }

    function setupTools(track) {
      var caps = track && track.getCapabilities ? track.getCapabilities() : {};
      if (caps.torch) {
        ui.torch.hidden = false;
        ui.torch.addEventListener("click", function () {
          var on = ui.torch.getAttribute("aria-pressed") !== "true";
          track.applyConstraints({ advanced: [{ torch: on }] }).then(function () {
            ui.torch.setAttribute("aria-pressed", on ? "true" : "false");
          }).catch(function () { /* non supportato */ });
        });
      }
      if (caps.zoom && caps.zoom.max > caps.zoom.min) {
        ui.zoom.hidden = false;
        ui.zoomInput.min = caps.zoom.min; ui.zoomInput.max = caps.zoom.max; ui.zoomInput.step = caps.zoom.step || 0.1;
        ui.zoomInput.value = caps.zoom.min;
        ui.zoomInput.addEventListener("input", function () {
          track.applyConstraints({ advanced: [{ zoom: Number(ui.zoomInput.value) }] }).catch(function () {});
        });
      }
    }

    ui.close.addEventListener("click", function () { stop(); });
    ui.again.addEventListener("click", resume);
    ui.dlg.addEventListener("cancel", function () { stop(); });
    ui.manual.addEventListener("submit", function (e) {
      e.preventDefault();
      var input = ui.manual.querySelector("input");
      accept(input.value);
      if (running) { input.value = ""; input.focus(); }
    });
    if (ui.done) ui.done.addEventListener("click", function () { var v = values.slice(); stop(); if (opts.onDone) opts.onDone(v); });

    if (problem) { ui.status.textContent = problem; ui.manual.querySelector("input").focus(); return; }

    var constraints = { video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1080 } } };
    Promise.all([getDetector(), navigator.mediaDevices.getUserMedia(constraints)])
      .then(function (res) {
        var detector = res[0];
        stream = res[1];
        if (!running) { stream.getTracks().forEach(function (t) { t.stop(); }); return; }
        ui.video.srcObject = stream;
        setupTools(stream.getVideoTracks()[0]);
        return ui.video.play().then(function () {
          ui.status.textContent = opts.continuous ? "Inquadra i codici uno dopo l'altro…" : "Inquadra il codice a barre o QR…";
          var last = 0, busy = false;
          function tick(ts) {
            if (!running) return;
            if (!paused && !busy && ts - last > 150 && ui.video.readyState >= 2) {
              last = ts; busy = true;
              detector.detect(ui.video).then(function (codes) {
                busy = false;
                if (running) handle(codes, performance.now());
              }).catch(function () { busy = false; /* frame non pronto */ });
            }
            raf = requestAnimationFrame(tick);
          }
          raf = requestAnimationFrame(tick);
        });
      })
      .catch(function (err) {
        if (running) ui.status.textContent = "Fotocamera non disponibile (" + (err && err.name || "errore") + "). Scrivi il codice a mano.";
      });
  };

  MAG.resolveScan = function (value) {
    return MAG.fetchJSON("/scan/resolve?v=" + encodeURIComponent(value)).then(function (r) { return r.data; });
  };

  // ---- Aggancio ai pulsanti ----
  // [data-scan-target="campo"] riempie l'input del form; [data-scan-search] apre la scheda o cerca;
  // [data-scan-batch] scansione a raffica; [data-scan-model] riconosce il modello e apre il nuovo componente.
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
    if (e.target.closest("[data-scan-model]")) {
      e.preventDefault();
      MAG.scan({ title: "Scansiona l'etichetta del pezzo", onResult: function (v) {
        window.location.assign("/components/new?part=" + encodeURIComponent(v));
      } });
      return;
    }
    if (e.target.closest("[data-scan-search]")) {
      e.preventDefault();
      MAG.scan({ onResult: function (v) {
        MAG.resolveScan(v).then(function (r) {
          if (r.url) { window.location.assign(r.url); return; }
          if (r.new) {
            MAG.confirm("Riconosciuto il modello " + r.model + ".\nNon è ancora in magazzino con questo codice: vuoi aggiungerlo?",
              { title: "Modello riconosciuto", okLabel: "Nuovo componente" })
              .then(function (yes) { window.location.assign(yes ? r.new : r.search); });
            return;
          }
          window.location.assign(r.search);
        });
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
