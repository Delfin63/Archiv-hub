"use strict";

// Ablage-Werkzeug: Quelle wählen, Vorschlag prüfen, ablegen.
// Alles auf einer Seite. Die KI schlägt Ordner und Dateinamen vor; beides
// lässt sich überschreiben.

var gewaehlt = null;          // {name}
var speicherortDaten = [];
var korbHostPfad = "";

// --- Schrittleiste ----------------------------------------------------------

function zeigeSchritt(n) {
  [1, 2].forEach(function (i) {
    var el = document.getElementById("schritt-" + i);
    if (el) el.hidden = i > n;
  });
  var punkte = document.querySelectorAll(".sl-punkt");
  for (var i = 0; i < punkte.length; i++) {
    var nr = parseInt(punkte[i].getAttribute("data-schritt"), 10);
    punkte[i].className = "sl-punkt" + (nr === n ? " aktiv" : (nr < n ? " erledigt" : ""));
  }
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

// --- Schritt 1: Quelle ------------------------------------------------------

function zeigeQuelle(art) {
  document.getElementById("upload-bereich").hidden = art !== "upload";
  document.getElementById("scan-bereich").hidden = art !== "scan";
  document.getElementById("kachel-upload").className =
    "kachel" + (art === "upload" ? " gewaehlt" : "");
  document.getElementById("kachel-scan").className =
    "kachel" + (art === "scan" ? " gewaehlt" : "");
  // Die Statusabfrage läuft nur, solange der Scan-Bereich offen ist.
  if (art !== "scan") stoppeScannerPruefung();
}

document.getElementById("kachel-scan").addEventListener("click", function () {
  zeigeQuelle("scan");
  pruefeScanner();
});
document.getElementById("kachel-upload").addEventListener("click", function () {
  zeigeQuelle("upload");
});

document.getElementById("pruef-zeigen").addEventListener("click", function () {
  var l = document.getElementById("pruef-liste");
  var b = document.getElementById("pruef-zeigen");
  l.hidden = !l.hidden;
  b.textContent = l.hidden ? "Anzeigen" : "Ausblenden";
});

// --- Direktscan über eSCL ---------------------------------------------------

var scannerBereit = false;
var scannerTimer = null;

function pruefeScanner() {
  var el = document.getElementById("scanner-status");
  el.textContent = "Prüfe Scanner …";
  api("/api/scanner/status", "GET")
    .then(function (d) {
      if (!d.konfiguriert) {
        scannerBereit = false;
        el.textContent =
          "Kein Scanner eingerichtet. Nutze die Anleitung unten für " +
          "„Digitale Bilder“.";
        document.getElementById("scan-start").disabled = true;
        stoppeScannerPruefung();
        return;
      }
      scannerBereit = d.bereit;
      el.textContent = d.bereit
        ? d.name + " ist bereit."
        : d.name + ": " + d.zustand + " – bitte warten …";
      document.getElementById("scan-start").disabled = !d.bereit;

      // Solange der Scanner arbeitet, weiter nachfragen: nach einem Scan
      // meldet das Gerät rund eine Minute "Processing", bevor es frei wird.
      if (d.bereit) {
        stoppeScannerPruefung();
      } else {
        starteScannerPruefung();
      }
    })
    .catch(function (err) {
      scannerBereit = false;
      el.textContent = "Scanner nicht erreichbar: " + err.message;
      document.getElementById("scan-start").disabled = true;
      starteScannerPruefung();
    });
}

function starteScannerPruefung() {
  if (scannerTimer) return;
  scannerTimer = window.setInterval(function () {
    // Nur nachfragen, solange der Scan-Bereich sichtbar ist.
    if (document.getElementById("scan-bereich").hidden) {
      stoppeScannerPruefung();
      return;
    }
    pruefeScanner();
  }, 5000);
}

function stoppeScannerPruefung() {
  if (scannerTimer) {
    window.clearInterval(scannerTimer);
    scannerTimer = null;
  }
}

document.getElementById("scan-skript-zeigen").addEventListener("click", function () {
  var h = document.getElementById("scan-hilfe");
  h.hidden = !h.hidden;
});

document.getElementById("scan-start").addEventListener("click", function () {
  if (!scannerBereit) return;
  var btn = document.getElementById("scan-start");
  btn.disabled = true;
  zeigeErgebnis("Scanne … das kann bis zu einer Minute dauern.", false);

  api("/api/scanner/scan", "POST", {
    quelle: document.getElementById("scan-quelle").value,
    aufloesung: parseInt(document.getElementById("scan-aufloesung").value, 10),
    farbmodus: document.getElementById("scan-farbe").value,
    duplex: document.getElementById("scan-duplex").checked
  })
    .then(function (d) {
      zeigeErgebnis(
        "Gescannt: " + d.name + " (" + groesse(d.groesse) +
        "). Jetzt »Wählen« antippen.", false
      );
      loadKorb();
    })
    .catch(function (err) { zeigeErgebnis(err.message, true); })
    .then(function () { pruefeScanner(); });
});

function loadKorb() {
  var liste = document.getElementById("korb-liste");
  var badge = document.getElementById("korb-count");
  var hinweis = document.getElementById("korb-hinweis");
  fetch("/api/korb", { credentials: "same-origin" })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      var dateien = (d && d.dateien) || [];
      if (d && d.host_pfad) korbHostPfad = d.host_pfad;
      if (badge) badge.textContent = String(dateien.length);
      if (hinweis) {
        hinweis.textContent = dateien.length
          ? ""
          : "Keine offenen Dokumente";
      }
      if (!dateien.length) {
        liste.innerHTML = "";
        return;
      }
      liste.innerHTML = dateien.map(function (f) {
        return (
          '<li class="korb-eintrag">' +
            '<div class="korb-name">' + esc(f.name) + "</div>" +
            '<div class="klein korb-meta">' + groesse(f.groesse) +
              " · " + datum(f.geaendert) + "</div>" +
            '<button type="button" class="btn btn-primary btn-klein" data-waehlen="' +
              esc(f.name) + '">Wählen</button>' +
            '<button type="button" class="btn btn-still btn-klein" data-ablehnen="' +
              esc(f.name) + '">Weglegen</button>' +
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

function zahl(wert, stellen) {
  return wert.toFixed(stellen).replace(".", ",");
}

function datum(iso) {
  if (!iso) return "";
  var m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (!m) return esc(iso);
  return m[3] + "." + m[2] + "." + m[1] + ", " + m[4] + ":" + m[5];
}

document.getElementById("korb-liste").addEventListener("click", function (e) {
  var w = e.target.getAttribute && e.target.getAttribute("data-waehlen");
  var a = e.target.getAttribute && e.target.getAttribute("data-ablehnen");
  if (w) { starteSchritt2({ name: w }); return; }
  if (a) {
    if (!window.confirm("»" + a + "« weglegen?\n\nDie Datei wird nach " +
        "data/input/erledigt/ verschoben, nicht gelöscht.")) return;
    api("/api/korb/" + encodeURIComponent(a), "DELETE")
      .then(loadKorb)
      .catch(function (err) { zeigeErgebnis(err.message, true); });
  }
});

document.getElementById("korb-neu").addEventListener("click", loadKorb);

document.getElementById("korb-finder").addEventListener("click", function () {
  if (!korbHostPfad) {
    zeigeErgebnis("Ordnerpfad unbekannt. Hub über Skript 60 starten.", true);
    return;
  }
  window.location.href = "file://" + encodeURI(korbHostPfad);
});

document.getElementById("upload-form").addEventListener("submit", function (e) {
  e.preventDefault();
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
      if (!res.ok) { zeigeErgebnis(res.d.error || "Fehler beim Hochladen.", true); return; }
      document.getElementById("datei").value = "";
      leereErgebnis();
      loadKorb();
      zeigeErgebnis("Im Eingangskorb abgelegt. Jetzt »Wählen« antippen.", false);
    })
    .catch(function () { zeigeErgebnis("Fehler beim Hochladen.", true); });
});

// --- Schritt 2: Vorschlag prüfen --------------------------------------------

function starteSchritt2(auswahl) {
  gewaehlt = auswahl;
  leereErgebnis();
  document.getElementById("gewaehlte-datei").textContent = "Datei: " + auswahl.name;
  document.getElementById("vorschlag-bereich").innerHTML =
    '<p class="klein">Analysiere … (Texterkennung und Einordnung)</p>';
  zeigeSchritt(2);

  ladeAblageOrte()
    .then(function () {
      return api("/api/korb/" + encodeURIComponent(auswahl.name) + "/vorschlag", "POST");
    })
    .then(function (d) {
      if (d.vorschlag) {
        var s = d.vorschlag.speicherort;
        if (s) {
          document.getElementById("wahl-speicherort").value = s;
        }
        ladeOrdnerAuswahl(d.vorschlag.pfad || "");
        // Dateiname-Vorschlag der KI ins Feld übernehmen (überschreibbar).
        document.getElementById("wahl-dateiname").value = d.vorschlag.dateiname || "";
        document.getElementById("vorschlag-bereich").innerHTML =
          '<div class="vorschlag">Vorschlag: <strong>' +
            esc(d.vorschlag.ziel_name) + "</strong>" +
            (d.vorschlag.sicherheit != null
              ? ' <span class="klein">(Sicherheit ' +
                esc(String(d.vorschlag.sicherheit)) + ")</span>"
              : "") +
          "</div>";
      } else {
        document.getElementById("vorschlag-bereich").innerHTML =
          '<p class="klein">Keine automatische Zuordnung – bitte unten ' +
          "Ordner und Dateiname selbst bestimmen.</p>";
        var stamm = auswahl.name.replace(/\.[^.]+$/, "");
        var heute = new Date().toISOString().slice(0, 10);
        document.getElementById("wahl-dateiname").value = heute + " – " + stamm + ".pdf";
      }
    })
    .catch(function (err) {
      document.getElementById("vorschlag-bereich").innerHTML =
        '<p class="klein">' + esc(err.message) + "</p>";
    });
}

function ladeAblageOrte() {
  return api("/api/ablage/ordner-liste", "GET").then(function (d) {
    speicherortDaten = d.speicherorte || [];
    var sel = document.getElementById("wahl-speicherort");
    sel.innerHTML = speicherortDaten.map(function (s) {
      return '<option value="' + esc(s.speicherort) + '">' + esc(s.label) + "</option>";
    }).join("");
  });
}

function aktuelleSpeicherortDaten() {
  var name = document.getElementById("wahl-speicherort").value;
  for (var i = 0; i < speicherortDaten.length; i++) {
    if (speicherortDaten[i].speicherort === name) return speicherortDaten[i];
  }
  return speicherortDaten.length ? speicherortDaten[0] : null;
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
  if (!name) { zeigeErgebnis("Bitte einen Ordnernamen angeben.", true); return; }
  if (!daten) { zeigeErgebnis("Kein Speicherort verfügbar.", true); return; }

  api("/api/ablage/ordner", "POST", {
    speicherort: daten.speicherort, pfad: "", name: name
  })
    .then(function () { return api("/api/ablage/ordner-liste", "GET"); })
    .then(function (d) {
      speicherortDaten = d.speicherorte || [];
      ladeOrdnerAuswahl(name);
      feld.value = "";
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
  if (!daten) { zeigeErgebnis("Kein Speicherort verfügbar.", true); return; }

  var ordner = document.getElementById("wahl-ordner").value || "";
  var dateiname = document.getElementById("wahl-dateiname").value.trim();
  if (!dateiname) { zeigeErgebnis("Bitte einen Dateinamen angeben.", true); return; }

  zeigeErgebnis("Lege ab … (Texterkennung läuft)", false);
  api("/api/korb/" + encodeURIComponent(gewaehlt.name) + "/ablegen", "POST", {
    speicherort: daten.speicherort,
    pfad: ordner,
    dateiname: dateiname
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
            return "<li>" + esc(f.name) +
              ' <span class="klein">(' + esc(f.geaendert) + ")</span></li>";
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
