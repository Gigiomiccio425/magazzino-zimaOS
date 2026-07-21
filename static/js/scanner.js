// Scanner barcode/QR con fotocamera telefono.
// Usa l'API nativa BarcodeDetector (nessuna libreria esterna, funziona offline).
// NB: la fotocamera richiede un contesto sicuro (HTTPS o localhost). Su http://IP
// il browser la blocca -> mostriamo un messaggio chiaro.
(function () {
  "use strict";

  function supportInfo() {
    if (!window.isSecureContext) {
      return { ok: false, msg:
        "Fotocamera bloccata: l'app e' su HTTP.\n\n" +
        "Serve HTTPS (o localhost). Apri l'app tramite un indirizzo sicuro " +
        "(HTTPS / accesso remoto ZimaOS) e riprova.\n\n" +
        "Intanto puoi inserire il codice a mano." };
    }
    if (!("BarcodeDetector" in window)) {
      return { ok: false, msg:
        "Questo browser non supporta la scansione (BarcodeDetector).\n" +
        "Usa Chrome su Android, oppure inserisci il codice a mano." };
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      return { ok: false, msg: "Fotocamera non disponibile su questo dispositivo." };
    }
    return { ok: true };
  }

  var overlay, video, statusEl, stream, detector, running, rafId;

  function buildOverlay() {
    overlay = document.createElement("div");
    overlay.className = "scanner-overlay";
    overlay.innerHTML =
      '<div class="scanner-box">' +
      '  <div class="scanner-head">' +
      '    <span class="scanner-title">SCANSIONA CODICE</span>' +
      '    <button type="button" class="scanner-close" aria-label="Chiudi">&times;</button>' +
      '  </div>' +
      '  <div class="scanner-view">' +
      '    <video class="scanner-video" playsinline muted></video>' +
      '    <div class="scanner-reticle"></div>' +
      '  </div>' +
      '  <div class="scanner-status">Inquadra il codice a barre o QR...</div>' +
      '</div>';
    document.body.appendChild(overlay);
    video = overlay.querySelector(".scanner-video");
    statusEl = overlay.querySelector(".scanner-status");
    overlay.querySelector(".scanner-close").addEventListener("click", close);
    overlay.addEventListener("click", function (e) { if (e.target === overlay) close(); });
  }

  function close() {
    running = false;
    if (rafId) cancelAnimationFrame(rafId);
    if (stream) { stream.getTracks().forEach(function (t) { t.stop(); }); stream = null; }
    if (overlay) { overlay.remove(); overlay = null; }
  }

  async function scan(onResult) {
    var info = supportInfo();
    if (!info.ok) { alert(info.msg); return; }

    buildOverlay();
    try {
      detector = new window.BarcodeDetector();
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" } }
      });
      video.srcObject = stream;
      await video.play();
    } catch (err) {
      statusEl && (statusEl.textContent = "Errore fotocamera: " + err.message);
      setTimeout(close, 2500);
      return;
    }

    running = true;
    var last = 0;
    async function tick(ts) {
      if (!running) return;
      // ~5 letture/sec
      if (ts - last > 180 && video.readyState >= 2) {
        last = ts;
        try {
          var codes = await detector.detect(video);
          if (codes && codes.length) {
            var value = (codes[0].rawValue || "").trim();
            if (value) {
              statusEl.textContent = "Letto: " + value;
              if (navigator.vibrate) navigator.vibrate(120);
              close();
              onResult(value);
              return;
            }
          }
        } catch (e) { /* frame non pronto, continua */ }
      }
      rafId = requestAnimationFrame(tick);
    }
    rafId = requestAnimationFrame(tick);
  }

  // ---- Aggancio ai pulsanti ----
  // <button data-scan-target="serial_number">  -> riempie l'input name=serial_number
  // <button data-scan-search>                  -> riempie la ricerca e invia il form
  document.addEventListener("click", function (e) {
    var t = e.target.closest("[data-scan-target]");
    if (t) {
      e.preventDefault();
      var name = t.getAttribute("data-scan-target");
      var input = t.closest("form").querySelector('[name="' + name + '"]');
      scan(function (value) {
        if (input) { input.value = value; input.dispatchEvent(new Event("input", { bubbles: true })); input.focus(); }
      });
      return;
    }
    var s = e.target.closest("[data-scan-search]");
    if (s) {
      e.preventDefault();
      var form = s.closest("form");
      var box = form.querySelector('[name="q"]');
      scan(function (value) {
        if (box) { box.value = value; form.submit(); }
      });
    }
  });
})();
