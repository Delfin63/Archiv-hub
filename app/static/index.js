"use strict";

// Geführter Ablauf: 1 Material einfügen -> 2 Ablageort -> 3 Ablegen.
// Die Schritte werden nacheinander eingeblendet; es gibt keine Navigation
// zwischen einzelnen Seiten.

var gewaehlt = null; // {name, quelle: "korb" | "upload"}
var vorschlag = null;

function zeigeSchritt(n) {
  [1, 2, 3].forEach(function (i) {
    var el = document.getElementById("schritt-" + i);
    if (el) el.hidden = i > n;
  });
}

function zeigeErgebnis(text, fehler) {
  var erg = document.getElementById("ergebnis");
  erg.className = fehler ? "msg error" : "msg ok";
  erg.textContent = text;
}

function leereErgebnis() {
  var erg = document.getElementById("ergebnis");
  erg.className = "msg";
  erg.textContent = "";
}

// --- Schritt 1: Korb --------------------------------------------------------

var korbHostPfad = "";

function loadKorb() {
  var liste = document.getElementById("korb-liste");
  var badge = document.getElementById("korb-count");
  fetch("/api/korb", { credentials: "same-origin" })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      var dateien = (d && d.dateien) || [];
      if (d && d.host_pfad) {
        korbHostPfad = d.host_pfad;
        var el = document.getElementById("korb-pfad");
        if (el) el.textContent = korbHostPfad;
      }
      if (badge) badge.textContent = String(dateien.length);
      if (!dateien.length) {
        liste.innerHTML = '<li class="klein">Der Korb ist leer.</li>';
        return;
      }
      liste.innerHTML = dateien.map(function (f) {
        return (
          '<li class="korb-eintrag">' +
            '<div class="korb-name">' + esc(f.name) + "</div>" +
            '<div class="klein korb-meta">' + groesse(f.groesse) + " · " + datum(f.geaendert) + "</div>" +
            '<button type="button" class="btn btn-primary btn-klein" data-waehlen="' + esc(f.name) + '">Wählen</button>' +
            '<button type="button" class="btn btn-still btn-klein" data-ablehnen="' + esc(f.name) + '">Weglegen</button>' +
          "</li>"
        );
      }).join("");
    })
    .catch(function () {
      liste.innerHTML = '<li class="klein">Liste nicht ladbar.</li>';
    });
}

function groesse(bytes) {
  if (bytes == null) return "";
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return zahl(bytes / 1024, 0) + " KB";
  return zahl(bytes / (1024 * 1024), 1) + " MB";
}

// Zahl mit Komma als Dezimaltrennzeichen (deutsche Schreibweise).
function zahl(wert, stellen) {
  return wert.toFixed(stellen).replace(".", ",");
}

// "2026-11-08T11:28:10" -> "08.11.2026, 11:28"
function datum(iso) {
  if (!iso) return "";
  var m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (!m) return esc(iso);
  return m[3] + "." + m[2] + "." + m[1] + ", " + m[4] + ":" + m[5];
}

document.getElementById("korb-liste").addEventListener("click", function (e) {
  var waehlen = e.target.getAttribute && e.target.getAttribute("data-waehlen");
  var ablehnen = e.target.getAttribute && e.target.getAttribute("data-ablehnen");

  if (waehlen) {
    starteSchritt2({ name: waehlen, quelle: "korb" });
    return;
  }
  if (ablehnen) {
    if (!window.confirm("»" + ablehnen + "« aus dem Korb weglegen?\n\nDie Datei wird nach data/input/erledigt/ verschoben, nicht gelöscht.")) {
      return;
    }
    api("/api/korb/" + encodeURIComponent(ablehnen), "DELETE")
      .then(function () { loadKorb(); })
      .catch(function (err) { zeigeErgebnis(err.message, true); });
  }
});

document.getElementById("korb-neu").addEventListener("click", loadKorb);

// Öffnet den Eingangskorb im Finder (file://-URL, nur auf dem Mac sinnvoll).
document.getElementById("korb-finder").addEventListener("click", function () {
  if (!korbHostPfad) {
    zeigeErgebnis(
      "Der Ordnerpfad ist nicht bekannt. Starte den Hub über " +
      "60-archiv-hub-A-starten.command.",
      true
    );
    return;
  }
  window.location.href = "file://" + encodeURI(korbHostPfad);
});

// Upload: Datei landet im Korb, damit sie dort geprüft werden kann.
document.getElementById("upload-form").addEventListener("submit", function (event) {
  event.preventDefault();
  var file = document.getElementById("datei").files[0];
  if (!file) return;
  var fd = new FormData();
  fd.append("file", file);
  zeigeErgebnis("Lade hoch …", false);

  fetch("/api/upload-ablage", {
    method: "POST",
    body: fd,
    credentials: "same-origin",
    headers: { "X-CSRF-Token": archivCsrf() }
  })
    .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
    .then(function (res) {
      if (!res.ok) {
        zeigeErgebnis(res.d.error || "Fehler beim Hochladen.", true);
        return;
      }
      leereErgebnis();
      document.getElementById("datei").value = "";
      loadKorb();
      zeigeErgebnis("Im Korb abgelegt. Jetzt »Wählen« antippen.", false);
    })
    .catch(function () { zeigeErgebnis("Fehler beim Hochladen.", true); });
});

// --- Schritt 2: Ablegen -----------------------------------------------------
//
// Alles auf einer Seite: Datei waehlen, Ablageort bestimmen, ablegen.
// Kein Seitenwechsel, keine getrennte Verwaltung. Ein neuer Ordner wird hier
// direkt angelegt.

var speicherortDaten = [];

function starteSchritt2(auswahl) {
  gewaehlt = auswahl;
  leereErgebnis();
  document.getElementById("gewaehlte-datei").textContent = "Datei: " + auswahl.name;
  document.getElementById("vorschlag-bereich").innerHTML =
    '<p class="klein">Analysiere … (Texterkennung und Einordnung)</p>';
  zeigeSchritt(2);

  ladeAblageOrte().then(function () {
    return api("/api/korb/" + encodeURIComponent(auswahl.name) + "/vorschlag", "POST");
  })
    .then(function (d) {
      if (d.vorschlag) {
        document.getElementById("vorschlag-bereich").innerHTML =
          '<div class="vorschlag">Vorschlag: <strong>' +
          esc(d.vorschlag.ziel_name) + "</strong></div>";
      } else {
        document.getElementById("vorschlag-bereich").innerHTML =
          '<p class="klein">Keine automatische Zuordnung – bitte unten den ' +
          "Ablageort wählen.</p>";
      }
    })
    .catch(function (err) {
      document.getElementById("vorschlag-bereich").innerHTML =
        '<p class="klein">' + esc(err.message) + "</p>";
    });
}

// Speicherorte und deren Ordner laden.
function ladeAblageOrte() {
  return api("/api/ablage/ordner-liste", "GET").then(function (d) {
    speicherortDaten = d.speicherorte || [];
    var sel = document.getElementById("wahl-speicherort");
    sel.innerHTML = speicherortDaten.map(function (s) {
      var anzahl = (s.ordner || []).length;
      return '<option value="' + esc(s.speicherort) + '">' +
        esc(s.label) + (anzahl ? " (" + anzahl + " Ordner)" : "") +
        "</option>";
    }).join("");
    ladeOrdnerAuswahl();
  });
}

function aktuelleSpeicherortDaten() {
  var name = document.getElementById("wahl-speicherort").value;
  for (var i = 0; i < speicherortDaten.length; i++) {
    if (speicherortDaten[i].speicherort === name) return speicherortDaten[i];
  }
  return null;
}

function ladeOrdnerAuswahl(bevorzugt) {
  var sel = document.getElementById("wahl-ordner");
  var daten = aktuelleSpeicherortDaten();
  var ordner = daten ? daten.ordner || [] : [];
  sel.innerHTML = '<option value="">(direkt im Speicherort)</option>' +
    ordner.map(function (o) {
      return '<option value="' + esc(o) + '">' + esc(o) + "</option>";
    }).join("");
  if (bevorzugt) sel.value = bevorzugt;
  zeigeWahlPfad();
}

function zeigeWahlPfad() {
  var daten = aktuelleSpeicherortDaten();
  var el = document.getElementById("wahl-pfad");
  if (!daten) { el.textContent = ""; return; }
  var ordner = document.getElementById("wahl-ordner").value;
  el.textContent = daten.host_pfad + (ordner ? "/" + ordner : "");
}

function neuenOrdnerAnlegen() {
  var feld = document.getElementById("neuer-ordner");
  var name = feld.value.trim();
  var daten = aktuelleSpeicherortDaten();
  if (!name) { zeigeErgebnis("Bitte einen Namen für den Ordner angeben.", true); return; }
  if (!daten) { zeigeErgebnis("Kein Speicherort gewählt.", true); return; }

  api("/api/ablage/ordner", "POST", {
    speicherort: daten.speicherort,
    pfad: "",
    name: name
  })
    .then(function () {
      feld.value = "";
      // Ordner neu laden und sofort auswählen.
      return api("/api/ablage/ordner-liste", "GET");
    })
    .then(function (d) {
      speicherortDaten = d.speicherorte || [];
      ladeOrdnerAuswahl(name);
      zeigeErgebnis("Ordner angelegt: " + name, false);
    })
    .catch(function (err) { zeigeErgebnis(err.message, true); });
}

document.getElementById("wahl-speicherort").addEventListener("change", function () {
  ladeOrdnerAuswahl();
});
document.getElementById("wahl-ordner").addEventListener("change", zeigeWahlPfad);
document.getElementById("neuer-ordner").addEventListener("keydown", function (e) {
  if (e.key === "Enter") { e.preventDefault(); neuenOrdnerAnlegen(); }
});

document.getElementById("btn-abbrechen").addEventListener("click", function () {
  gewaehlt = null;
  leereErgebnis();
  zeigeSchritt(1);
});

document.getElementById("btn-ablegen").addEventListener("click", function () {
  if (!gewaehlt) return;
  var daten = aktuelleSpeicherortDaten();
  if (!daten) { zeigeErgebnis("Kein Speicherort gewählt.", true); return; }

  var ordner = document.getElementById("wahl-ordner").value || "";
  zeigeErgebnis("Lege ab … (Texterkennung läuft)", false);

  api("/api/korb/" + encodeURIComponent(gewaehlt.name) + "/ablegen", "POST", {
    speicherort: daten.speicherort,
    pfad: ordner
  })
    .then(function (d) {
      zeigeErgebnis("Abgelegt: " + d.ziel, false);
      gewaehlt = null;
      zeigeSchritt(1);
      loadKorb();
    })
    .catch(function (err) { zeigeErgebnis(err.message, true); });
});

// --- Zur Prüfung ------------------------------------------------------------

function loadPruefung() {
  var liste = document.getElementById("pruef-liste");
  var badge = document.getElementById("pruef-count");
  fetch("/api/zur-pruefung", { credentials: "same-origin" })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      var files = (d && d.dateien) || [];
      if (badge) badge.textContent = String(files.length);
      liste.innerHTML = files.length
        ? files.map(function (f) {
            return "<li>" + esc(f.name) + ' <span class="klein">(' + esc(f.geaendert) + ")</span></li>";
          }).join("")
        : '<li class="klein">keine Dateien</li>';
    })
    .catch(function () {
      liste.innerHTML = '<li class="klein">Liste nicht ladbar</li>';
    });
}

zeigeSchritt(1);
loadKorb();
loadPruefung();
