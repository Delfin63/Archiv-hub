"use strict";

var uploadForm = document.getElementById("upload-form");
uploadForm.addEventListener("submit", function (event) {
  event.preventDefault();
  var file = document.getElementById("datei").files[0];
  if (!file) return;
  var fd = new FormData();
  fd.append("file", file);
  var erg = document.getElementById("ergebnis");
  erg.className = "msg";
  erg.textContent = "Verarbeite …";

  fetch("/api/upload", { method: "POST", body: fd, credentials: "same-origin" })
    .then(function (r) {
      return r.json().then(function (d) { return { ok: r.ok, d: d }; });
    })
    .then(function (res) {
      if (!res.ok) {
        erg.className = "msg error";
        erg.textContent = res.d.error || "Fehler beim Upload.";
        return;
      }
      if (res.d.status === "abgelegt") {
        var zeilen = "Abgelegt – Datei: " + esc(res.d.original_filename);
        zeilen += " – Ziel: " + esc(res.d.ziel);
        if (res.d.sicherheit != null) zeilen += " – Sicherheit: " + res.d.sicherheit;
        erg.className = "msg ok";
        erg.textContent = zeilen;
      } else {
        erg.className = "msg ok";
        erg.textContent = "Zur Prüfung abgelegt – Datei: " + esc(res.d.original_filename);
      }
      loadPruefung();
    })
    .catch(function () {
      erg.className = "msg error";
      erg.textContent = "Fehler beim Upload.";
    });
});

function loadPruefung() {
  var liste = document.getElementById("pruef-liste");
  var badge = document.getElementById("pruef-count");
  fetch("/api/zur-pruefung", { credentials: "same-origin" })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      var files = d.dateien || [];
      if (badge) badge.textContent = String(files.length);
      liste.innerHTML = files.length
        ? files.map(function (f) {
            return '<li>' + esc(f.name) + ' <span class="klein">(' + esc(f.geaendert) + ')</span></li>';
          }).join("")
        : '<li class="klein">keine Dateien</li>';
    })
    .catch(function () {
      liste.innerHTML = '<li class="klein">Liste nicht ladbar</li>';
    });
}

loadPruefung();
