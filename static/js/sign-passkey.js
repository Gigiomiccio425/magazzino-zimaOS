// Impronta / passkey (WebAuthn) per il pannello di firma. Richiede HTTPS (o localhost).
(function () {
  "use strict";
  var MAG = window.MAG;
  if (!MAG || !window.PublicKeyCredential || !window.isSecureContext) return;

  function b64urlToBuf(s) {
    s = s.replace(/-/g, "+").replace(/_/g, "/");
    while (s.length % 4) s += "=";
    var bin = atob(s), out = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out.buffer;
  }
  function bufToB64url(buf) {
    var bytes = new Uint8Array(buf), bin = "";
    for (var i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  function creationOptions(o) {
    o.challenge = b64urlToBuf(o.challenge);
    o.user.id = b64urlToBuf(o.user.id);
    (o.excludeCredentials || []).forEach(function (c) { c.id = b64urlToBuf(c.id); });
    return o;
  }
  function requestOptions(o) {
    o.challenge = b64urlToBuf(o.challenge);
    (o.allowCredentials || []).forEach(function (c) { c.id = b64urlToBuf(c.id); });
    return o;
  }

  function credentialToJSON(cred) {
    var r = cred.response, out = {
      id: cred.id, rawId: bufToB64url(cred.rawId), type: cred.type,
      clientExtensionResults: cred.getClientExtensionResults ? cred.getClientExtensionResults() : {},
      response: { clientDataJSON: bufToB64url(r.clientDataJSON) }
    };
    if (r.attestationObject) {
      out.response.attestationObject = bufToB64url(r.attestationObject);
      out.response.transports = r.getTransports ? r.getTransports() : [];
    } else {
      out.response.authenticatorData = bufToB64url(r.authenticatorData);
      out.response.signature = bufToB64url(r.signature);
      out.response.userHandle = r.userHandle ? bufToB64url(r.userHandle) : null;
    }
    return out;
  }

  function parse(opts) { return typeof opts === "string" ? JSON.parse(opts) : opts; }

  function register(state) {
    var body = { new_name: state.op["new"], action: state.action };
    return MAG.fetchJSON("/sign/passkey/register/begin", { method: "POST", body: body }).then(function (r) {
      if (r.status !== 200) { MAG.signSetError(r.data.message || "Errore"); return; }
      return navigator.credentials.create({ publicKey: creationOptions(parse(r.data.options)) })
        .then(function (cred) {
          var pw = MAG.signPasswordValue();
          return MAG.fetchJSON("/sign/passkey/register/finish", {
            method: "POST", body: { credential: credentialToJSON(cred), password: pw || null }
          });
        })
        .then(function (res) { if (res) MAG.signHandleResponse(res); });
    });
  }

  function authenticate(state) {
    var body = { operator_id: state.op.id, action: state.action };
    return MAG.fetchJSON("/sign/passkey/auth/begin", { method: "POST", body: body }).then(function (r) {
      if (r.status !== 200) { MAG.signSetError(r.data.message || "Errore"); return; }
      return navigator.credentials.get({ publicKey: requestOptions(parse(r.data.options)) })
        .then(function (cred) {
          return MAG.fetchJSON("/sign/passkey/auth/finish", {
            method: "POST", body: { credential: credentialToJSON(cred) }
          });
        })
        .then(function (res) { if (res) MAG.signHandleResponse(res); });
    });
  }

  MAG.passkey = { register: register, authenticate: authenticate };

  var btn = document.getElementById("sign-passkey");
  if (btn) {
    btn.addEventListener("click", function () {
      var state = MAG.signState();
      if (!state || !state.op) return;
      MAG.signSetError("");
      btn.disabled = true;
      (state.op["new"] ? register(state) : authenticate(state))
        .catch(function (err) {
          MAG.signSetError(err && err.name === "NotAllowedError"
            ? "Operazione annullata o scaduta." : "Impronta non disponibile: usa la password.");
        })
        .then(function () { btn.disabled = false; });
    });
  }
})();
