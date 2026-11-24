// Firma operatori: intercetta i form POST, invia via fetch, apre il pannello di firma
// quando il server risponde 428, poi reinvia lo stesso form (dati non persi).
// Form esclusi: data-nosign. Il passkey (impronta) e' aggiunto da MAG.passkey (sign-passkey.js).
(function () {
  "use strict";
  var MAG = window.MAG;
  var dlg = document.getElementById("sign-dialog");
  if (!MAG || !dlg) return;

  var $ = function (id) { return document.getElementById(id); };
  var state = null; // {critical, action, resolve, op: {id,name,has_password,passkey_here} | {new:name}}

  function setError(msg) { $("sign-error").textContent = msg || ""; }

  function showStep(step) {
    $("sign-step-choose").hidden = step !== "choose";
    $("sign-step-verify").hidden = step !== "verify";
    setError("");
  }

  function passkeyAvailable() {
    return !!(window.isSecureContext && window.PublicKeyCredential && MAG.passkey);
  }

  function renderOps(ops) {
    var box = $("sign-ops");
    box.innerHTML = "";
    if (!ops.length) {
      var p = document.createElement("p");
      p.className = "sign-hint";
      p.textContent = "Nessun operatore ancora: registra il primo (sarà amministratore).";
      box.appendChild(p);
    }
    ops.forEach(function (op) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "btn btn--outline sign-op";
      b.setAttribute("role", "listitem");
      b.textContent = op.name;
      b.addEventListener("click", function () { chooseExisting(op); });
      box.appendChild(b);
    });
  }

  function chooseExisting(op) {
    state.op = op;
    $("sign-who").textContent = op.name;
    var canPasskey = passkeyAvailable() && op.passkey_here;
    $("sign-passkey-box").hidden = !canPasskey;
    $("sign-password-field").hidden = !op.has_password;
    $("sign-password-label").textContent = "Password";
    $("sign-password").autocomplete = "current-password";
    var hint = "";
    if (!canPasskey && !op.has_password) {
      hint = "Nessuna impronta registrata per questo indirizzo e nessuna password: chiedi a un amministratore di impostarne una.";
    } else if (!canPasskey && !passkeyAvailable()) {
      hint = "Su questo indirizzo l'impronta non è disponibile (serve HTTPS): usa la password.";
    } else if (!canPasskey && op.passkey_here === false) {
      hint = "Nessuna impronta registrata per questo indirizzo: usa la password.";
    }
    $("sign-hint").textContent = hint;
    $("sign-submit").hidden = !op.has_password;
    showStep("verify");
    (canPasskey ? $("sign-passkey") : $("sign-password")).focus();
  }

  function chooseNew() {
    var name = $("sign-new-name").value.trim();
    if (!name) { $("sign-new-name").focus(); return; }
    state.op = { "new": name };
    $("sign-who").textContent = name + " (nuovo)";
    var canPasskey = passkeyAvailable();
    $("sign-passkey-box").hidden = !canPasskey;
    $("sign-password-field").hidden = false;
    $("sign-password-label").textContent = canPasskey ? "Password (consigliata, almeno 6 caratteri)" : "Password (almeno 6 caratteri)";
    $("sign-password").autocomplete = "new-password";
    $("sign-hint").textContent = canPasskey
      ? "Registra l'impronta e/o una password: la password serve dove l'impronta non è disponibile."
      : "Su questo indirizzo l'impronta non è disponibile (serve HTTPS): imposta una password.";
    $("sign-submit").hidden = false;
    showStep("verify");
    (canPasskey ? $("sign-passkey") : $("sign-password")).focus();
  }

  function finish(result) {
    var s = state;
    state = null;
    if (dlg.open) dlg.close();
    if (s) s.resolve(result);
  }

  function handleResponse(r) {
    if (r.status === 200 && r.data && r.data.ok) { finish(r.data); return; }
    if (r.status === 403 && r.data && r.data.error === "csrf") { window.location.reload(); return; }
    setError((r.data && r.data.message) || "Firma non riuscita.");
  }

  function submitPassword(e) {
    if (e) e.preventDefault();
    var body = { password: $("sign-password").value, action: state.action };
    if (state.op["new"]) body.new_name = state.op["new"]; else body.operator_id = state.op.id;
    $("sign-submit").disabled = true;
    MAG.fetchJSON("/sign/password", { method: "POST", body: body })
      .then(handleResponse)
      .catch(function () { setError("Errore di rete."); })
      .then(function () { $("sign-submit").disabled = false; });
  }

  // API usata da sign-passkey.js
  MAG.signState = function () { return state; };
  MAG.signHandleResponse = handleResponse;
  MAG.signPasswordValue = function () { return $("sign-password").value; };
  MAG.signSetError = setError;

  MAG.openSign = function (opts) {
    opts = opts || {};
    return new Promise(function (resolve) {
      state = { critical: !!opts.critical, action: opts.action || null, resolve: resolve, op: null };
      $("sign-critical").hidden = !opts.critical;
      $("sign-new-name").value = "";
      $("sign-password").value = "";
      showStep("choose");
      dlg.showModal();
      MAG.fetchJSON("/sign/operators").then(function (r) {
        renderOps(Array.isArray(r.data) ? r.data : []);
        var first = document.querySelector("#sign-ops .sign-op") || $("sign-new-name");
        first.focus();
      });
    });
  };

  $("sign-new-go").addEventListener("click", chooseNew);
  $("sign-new-name").addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); chooseNew(); } });
  $("sign-back").addEventListener("click", function () { showStep("choose"); });
  $("sign-step-verify").addEventListener("submit", submitPassword);
  $("sign-cancel").addEventListener("click", function () { finish(null); });
  dlg.addEventListener("cancel", function () { finish(null); });

  // ---- Invio dei form con firma ----
  function actionOf(form) {
    var url = new URL(form.getAttribute("action") || window.location.pathname, window.location.href);
    return (form.getAttribute("method") || "post").toUpperCase() + " " + url.pathname;
  }

  function send(form, token) {
    var submitter = form.querySelector('[type="submit"]');
    if (submitter) submitter.disabled = true;
    return MAG.submitForm(form, token ? { sig_token: token } : {})
      .then(function (r) {
        if (r.status === 428) {
          return MAG.openSign({ critical: r.data && r.data.critical, action: actionOf(form) })
            .then(function (res) { if (res) return send(form, res.action_token); });
        }
        if (r.status === 403 && r.data && r.data.error === "csrf") { window.location.reload(); return; }
        if (r.data && r.data.redirect) return;
        if (r.status >= 400) {
          MAG.toast((r.data && r.data.message) || "Operazione non riuscita (" + r.status + ").", "error");
          return;
        }
        window.location.reload();
      })
      .catch(function () { MAG.toast("Errore di rete: modifica non salvata.", "error"); })
      .then(function () { if (submitter) submitter.disabled = false; });
  }

  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form.matches || !form.matches('form[method="post"]:not([data-nosign])')) return;
    if (form.getAttribute("data-confirm") && form.dataset.confirmed !== "1") return;
    e.preventDefault();
    delete form.dataset.confirmed;
    form._submitter = e.submitter || null;  // il pulsante premuto porta il suo name/value
    send(form);
  });

  // ---- Uscita operatore (barra in alto) ----
  var out = document.getElementById("signer-logout");
  if (out) {
    out.addEventListener("click", function () {
      MAG.fetchJSON("/sign/logout", { method: "POST" }).then(function () { window.location.reload(); });
    });
  }
})();
