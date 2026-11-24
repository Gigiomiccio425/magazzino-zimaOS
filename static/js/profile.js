// Profilo: aggiunta impronta per l'indirizzo corrente (richiede operatore firmato).
(function () {
  "use strict";
  var MAG = window.MAG, btn = document.getElementById("profile-add-passkey");
  if (!btn || !MAG || !MAG.passkeyCreate) return;
  btn.hidden = false;
  document.getElementById("profile-passkey-hint").hidden = true;
  btn.addEventListener("click", function () {
    MAG.fetchJSON("/sign/passkey/register/begin", { method: "POST", body: {} }).then(function (r) {
      if (r.status === 428) {
        return MAG.openSign({}).then(function (ok) { if (ok) btn.click(); });
      }
      if (r.status !== 200) { MAG.toast(r.data.message || "Errore", "error"); return; }
      return MAG.passkeyCreate(r.data.options).then(function (res) {
        if (res.status === 200) window.location.reload(); else MAG.toast(res.data.message || "Errore", "error");
      });
    }).catch(function () { MAG.toast("Impronta non registrata.", "error"); });
  });
})();
