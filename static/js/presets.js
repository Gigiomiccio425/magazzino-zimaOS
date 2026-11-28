// Nuovo componente: ricerca tra i modelli pronti. Un clic apre il modulo già compilato.
(function () {
  "use strict";
  var MAG = window.MAG, input = document.getElementById("preset-q"), list = document.getElementById("preset-results");
  if (!input || !list) return;
  var timer = null, lastQ = null;

  function render(items, q) {
    list.textContent = "";
    if (!q) return;
    if (!items.length) {
      var none = document.createElement("li");
      none.className = "preset-results__empty";
      none.textContent = "Nessun modello trovato. Puoi scansionare l'etichetta o compilare a mano.";
      list.appendChild(none);
      return;
    }
    items.forEach(function (p) {
      var li = document.createElement("li");
      var a = document.createElement("a");
      a.href = "/components/new?preset=" + encodeURIComponent(p.id);
      a.className = "preset-result";
      var name = document.createElement("span");
      name.className = "preset-result__name";
      name.textContent = p.name;
      var meta = document.createElement("span");
      meta.className = "preset-result__meta mono";
      meta.textContent = [p.part, p.category].filter(Boolean).join(" · ");
      a.appendChild(name); a.appendChild(meta);
      li.appendChild(a);
      list.appendChild(li);
    });
  }

  function lookup() {
    var q = input.value.trim();
    if (q === lastQ) return;
    lastQ = q;
    if (!q) { render([], ""); return; }
    MAG.fetchJSON("/presets?q=" + encodeURIComponent(q)).then(function (r) {
      if (input.value.trim() === q) render(Array.isArray(r.data) ? r.data : [], q);
    });
  }

  input.addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(lookup, 180); });
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter") {
      e.preventDefault();
      var first = list.querySelector("a");
      if (first) window.location.assign(first.href);
    }
  });
})();

// Scheda tecnica da Icecat: solo su richiesta, propone dati da copiare nel modulo.
(function () {
  "use strict";
  var MAG = window.MAG, btn = document.querySelector("[data-icecat]");
  if (!btn) return;
  var box = document.querySelector("[data-icecat-result]"), form = btn.closest("form");
  function field(name) { return form.querySelector('[name="' + name + '"]'); }
  function el(tag, cls, text) { var n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; }
  function action(label, fn) { var b = el("button", "btn btn--outline btn--sm", label); b.type = "button"; b.addEventListener("click", fn); return b; }
  function appendNotes(text) {
    var notes = field("notes");
    if (!notes) return;
    notes.value = (notes.value ? notes.value.replace(/\s+$/, "") + "\n\n" : "") + text;
    MAG.toast("Aggiunto alle note.");
  }

  btn.addEventListener("click", function () {
    var brand = (field("manufacturer").value || "").trim();
    var part = (field("object_code").value || field("model").value || "").trim();
    box.hidden = false; box.textContent = "Cerco su Icecat…";
    btn.disabled = true;
    MAG.fetchJSON("/presets/icecat?brand=" + encodeURIComponent(brand) + "&part=" + encodeURIComponent(part))
      .then(function (r) {
        btn.disabled = false;
        box.textContent = "";
        var d = r.data || {};
        if (!d.found) { box.appendChild(el("p", "muted", d.message || "Nessun risultato.")); return; }
        var f = d.found;
        box.appendChild(el("p", "icecat-result__title strong", f.title));
        var acts = el("div", "icecat-result__actions");
        acts.appendChild(action("Usa come nome", function () { field("name").value = f.title; MAG.toast("Nome aggiornato."); }));
        if (f.description) acts.appendChild(action("Descrizione nelle note", function () { appendNotes(f.description); }));
        if (f.specs.length) acts.appendChild(action("Specifiche nelle note", function () {
          appendNotes("Scheda Icecat:\n" + f.specs.map(function (s) { return "- " + s.name + ": " + s.value; }).join("\n"));
        }));
        var link = el("a", "link", "Apri su Icecat");
        link.href = "https://icecat.biz/it/search?keyword=" + encodeURIComponent(f.part || part);
        link.target = "_blank"; link.rel = "noopener noreferrer";
        acts.appendChild(link);
        box.appendChild(acts);
        if (f.specs.length) {
          var dl = el("dl", "icecat-result__specs");
          f.specs.slice(0, 14).forEach(function (s) { dl.appendChild(el("dt", null, s.name)); dl.appendChild(el("dd", null, s.value)); });
          box.appendChild(dl);
        }
      })
      .catch(function () { btn.disabled = false; box.textContent = "Errore di rete."; });
  });
})();
