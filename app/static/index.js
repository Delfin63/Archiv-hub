"use strict";

// Ablage-Werkzeug: Quelle wählen, Vorschlag prüfen, ablegen.
// Alles auf einer Seite. Die KI schlägt Ordner und Dateinamen vor; beides
// lässt sich überschreiben.

var gewaehlt = null;          // {name}
var speicherortDaten = [];
var korbHostPfad = "";

// --- Schrittleiste ----------------------------------------------------------

// Die Schrittleiste passt sich dem Weg an:
//   Scannen:   Einstellungen -> Scannen -> Ziel
//   Hochladen: Datei -> Ziel -> ablegen
var SCHRITTE = {
  // Scannen: einstellen, scannen, dann Ziel und Ablegen.
  scan: [
    "Quelle wählen",
    "Einstellungen",
    "Scannen",
    "Name & Ziel wählen",
    "Ablegen"
  ],
  // Hochladen: keine Einstellungen, kein Scanschritt.
  upload: [
    "Quelle wählen",
    "Hochladen",
    "Name & Ziel wählen",
    "Ablegen"
  ]
};
var aktuellerWeg = null;

function setzeWeg(weg) {
  aktuellerWeg = weg;
  var leiste = document.getElementById("schrittleiste");
  if (!leiste) return;
  var namen = SCHRITTE[weg] || SCHRITTE.upload;
  var teile = [];
  for (var i = 0; i < namen.length; i++) {
    if (i > 0) teile.push('<span class="sl-sep">›</span>');
    teile.push(
      '<span class="sl-punkt" data-nr="' + (i + 1) + '">' +
      (i + 1) + ". " + namen[i] + "</span>"
    );
  }
  leiste.innerHTML = teile.join("");
  setzeUeberschriftNummern();
}

// Nummer des Schritts "Ziel wählen" und "Ausführen" je Weg.
function zielSchrittNr() {
  return aktuellerWeg === "scan" ? 4 : 3;
}

// Die Nummern in den Überschriften richten sich nach dem Weg.
function setzeUeberschriftNummern() {
  var z = document.getElementById("nr-ziel");
  var a = document.getElementById("nr-ausfuehren");
  if (z) z.textContent = String(zielSchrittNr());
  if (a) a.textContent = String(ausfuehrSchrittNr());
}
function ausfuehrSchrittNr() {
  return aktuellerWeg === "scan" ? 5 : 4;
}

// Markiert den aktuellen Schritt. Es wird NICHTS ausgeblendet, was zur
// Orientierung dient; nur die beiden Arbeitsbereiche erscheinen bei Bedarf.
function zeigeSchritt(n) {
  var punkte = document.querySelectorAll(".sl-punkt");
  for (var i = 0; i < punkte.length; i++) {
    var nr = parseInt(punkte[i].getAttribute("data-nr"), 10);
    punkte[i].className = "sl-punkt" +
      (nr === n ? " aktiv" : (nr < n ? " erledigt" : ""));
  }
}

function zeigeArbeitsbereiche(zielSichtbar, ausfuehrSichtbar) {
  document.getElementById("schritt-2").hidden = !zielSichtbar;
  document.getElementById("schritt-3").hidden = !ausfuehrSichtbar;
  // Erst wenn die Bereiche stehen, ist der Knopfzustand eindeutig.
  setzeKnopfZustand();
}

// Graut die Knöpfe erledigter Schritte aus. Sie werden erst wieder aktiv,
// wenn man mit "Zurück" in den Schritt zurückkehrt.
function setzeKnopfZustand() {
  var einstOffen = !document.getElementById("scan-einstellungen").hidden;
  var scanOffen = !document.getElementById("scan-ausfuehren").hidden;
  var zielOffen = !document.getElementById("schritt-2").hidden;
  var ablageOffen = !document.getElementById("schritt-3").hidden;

  // "Weiter" (Einstellungen) ist aktiv, solange der Scan-Schritt zu ist.
  setzeAktiv("scan-weiter", einstOffen && !scanOffen);
  // "Scannen" ist nur aktiv, wenn der Schritt offen UND das Gerät bereit ist.
  setzeAktiv("scan-start", scanOffen && scannerBereit);
  // "Weiter" (Ziel) ist aktiv, solange der Ablage-Schritt zu ist.
  setzeAktiv("btn-weiter", zielOffen && !ablageOffen);
  // "Ablegen" ist aktiv, solange der Schritt offen und noch nicht abgelegt.
  setzeAktiv("btn-ablegen", ablageOffen && !bereitsAbgelegt);
}

function setzeAktiv(id, aktiv) {
  var el = document.getElementById(id);
  if (!el) return;
  el.disabled = !aktiv;
  if (aktiv) {
    el.classList.remove("btn-erledigt");
  } else {
    el.classList.add("btn-erledigt");
  }
}

// Statusmeldung unter dem Formular.
function zeigeErgebnis(text, fehler) {
  var el = document.getElementById("ergebnis");
  if (!el) return;
  el.className = fehler ? "msg error" : "msg ok";
  el.textContent = text;
}

function leereErgebnis() {
  var el = document.getElementById("ergebnis");
  if (!el) return;
  el.className = "msg";
  el.textContent = "";
}

function zeigeQuelle(art) {
  // Schritt 1: nur die Kacheln. Nach der Wahl erscheint der passende
  // Unterbereich (Einstellungen bzw. Dateiauswahl).
  document.getElementById("upload-bereich").hidden = art !== "upload";
  document.getElementById("scan-bereich").hidden = art !== "scan";
  document.getElementById("kachel-upload").className =
    "kachel" + (art === "upload" ? " gewaehlt" : "");
  document.getElementById("kachel-scan").className =
    "kachel" + (art === "scan" ? " gewaehlt" : "");
  // Die Statusabfrage läuft nur, solange der Scan-Bereich offen ist.
  if (art !== "scan") stoppeScannerPruefung();
  // Ablauf und Schrittleiste richten sich nach dem gewählten Weg.
  setzeWeg(art === "scan" ? "scan" : "upload");
  // Beim Wegwechsel immer bei den Einstellungen (Schritt 2) beginnen.
  document.getElementById("scan-ausfuehren").hidden = true;

  // Neue Quelle: der Merker wird zurückgesetzt.
  bereitsAbgelegt = false;
  // Noch kein Dokument gewählt: die Bereiche 4 und 5 bleiben verborgen.
  zeigeArbeitsbereiche(false, false);
  // Schritt 1 ist erledigt, Schritt 2 (Einstellungen bzw. Dateiauswahl) aktiv.
  zeigeSchritt(2);
  // Überschriften-Nummern an den Weg anpassen.
  var nrUpload = document.getElementById("nr-upload");
  var nrScan = document.getElementById("nr-scan");
  if (nrUpload) nrUpload.textContent = "2";
  if (nrScan) nrScan.textContent = "2";
}

function korbZeigen(zeigen) {
  document.getElementById("korb-bereich").hidden = !zeigen;
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
// Merkt sich, ob der aktuelle Vorgang bereits abgelegt wurde. Dann bleibt
// "Ablegen" ausgegraut, bis man mit "Zurück" zurückgeht.
var bereitsAbgelegt = false;
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
        setzeKnopfZustand();
        stoppeScannerPruefung();
        return;
      }
      scannerBereit = d.bereit;
      el.textContent = d.bereit
        ? d.name + " ist bereit."
        : d.name + ": " + d.zustand + " – bitte warten …";
      setzeKnopfZustand();

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
      setzeKnopfZustand();
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

// Kurzfassung der aktuellen Scan-Einstellungen (für Schritt 3).
function scanKurzfassung() {
  var aufl = document.getElementById("scan-aufloesung").value;
  var vorlage = document.getElementById("scan-quelle");
  var farbe = document.getElementById("scan-farbe");
  var format = document.getElementById("scan-format");
  return aufl + " dpi · " + vorlage.options[vorlage.selectedIndex].text +
    " · " + farbe.options[farbe.selectedIndex].text +
    " · " + format.options[format.selectedIndex].text +
    (document.getElementById("scan-duplex").checked ? " · beidseitig" : "");
}

// Schritt 2 -> 3: Einstellungen bleiben sichtbar, der Scan-Knopf erscheint.
document.getElementById("scan-weiter").addEventListener("click", function () {
  document.getElementById("scan-zusammenfassung").textContent = scanKurzfassung();
  document.getElementById("scan-ausfuehren").hidden = false;
  zeigeSchritt(3);
  // Knopfzustand an den neuen Schritt anpassen (Scan wird aktiv).
  setzeKnopfZustand();
  document.getElementById("scan-ausfuehren").scrollIntoView({ block: "start" });
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
    duplex: document.getElementById("scan-duplex").checked,
    format: document.getElementById("scan-format").value
  })
    .then(function (d) {
      leereErgebnis();
      korbZeigen(true);
      loadKorb();
      // Schritt 3 (Scannen) ist erledigt -> weiter zu "Ziel wählen".
      starteSchritt2({ name: d.name });
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
      if (d && d.host_pfad) {
        korbHostPfad = d.host_pfad;
        var pe = document.getElementById("korb-pfad");
        if (pe) pe.textContent = "📁 " + korbHostPfad;
      }
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
  if (w) {
    if (!aktuellerWeg) setzeWeg("upload");
    starteSchritt2({ name: w });
    return;
  }
  if (a) {
    if (!window.confirm("»" + a + "« weglegen?\n\nDie Datei wird nach " +
        "data/input/erledigt/ verschoben, nicht gelöscht.")) return;
    api("/api/korb/" + encodeURIComponent(a), "DELETE")
      .then(loadKorb)
      .catch(function (err) { zeigeErgebnis(err.message, true); });
  }
});

document.getElementById("korb-neu").addEventListener("click", loadKorb);

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
      // Direkt weiter zu Schritt 2 (Ziel): der Upload ist im Korb.
      starteSchritt2({ name: res.d.name });
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
  zeigeSchritt(zielSchrittNr());
  zeigeArbeitsbereiche(true, false);
  document.getElementById("schritt-2").scrollIntoView({ block: "start" });

  ladeAblageOrte()
    .then(function () {
      return api("/api/korb/" + encodeURIComponent(auswahl.name) + "/vorschlag", "POST");
    })
    .then(function (d) {
      var v = d.vorschlag || {};
      if (v.speicherort) {
        document.getElementById("wahl-speicherort").value = v.speicherort;
      }
      ladeOrdnerVorschlaege();
      setzeOrdner(v.ordner || "");
      document.getElementById("wahl-dateiname").value = v.dateiname || "";

      // Hinweis, woher das Datum im Dateinamen stammt.
      var dh = document.getElementById("datum-hinweis");
      if (v.datum_aus_dokument) {
        dh.textContent = "Datum aus dem Dokument: " + v.datum;
      } else {
        dh.textContent =
          "Kein Datum im Dokument gefunden – es wurde das Scan-Datum " +
          "verwendet. Du kannst den Namen oben anpassen.";
      }

      if (v.ordner) {
        document.getElementById("vorschlag-bereich").innerHTML =
          '<div class="vorschlag">Vorschlag: <strong>' + esc(v.ordner) +
          "</strong>" +
          (v.ordner_vorhanden ? ' <span class="klein">(vorhanden)</span>'
                              : ' <span class="klein">(wird neu angelegt)</span>') +
          (v.dokumenttyp
            ? '<div class="klein">' + esc(v.dokumenttyp) +
              (v.absender ? " · " + esc(v.absender) : "") + "</div>"
            : "") +
          "</div>";
      } else {
        document.getElementById("vorschlag-bereich").innerHTML =
          '<p class="klein">Kein Vorschlag möglich – bitte Ordner und ' +
          "Dateiname selbst bestimmen.</p>";
      }
    })
    .catch(function (err) {
      document.getElementById("vorschlag-bereich").innerHTML =
        '<p class="klein">' + esc(err.message) + "</p>";
    });
}

// Baut einen Dateinamen-Vorschlag für den Fall, dass die KI keinen liefert.
// Ein bereits vorhandenes Datum im Namen (z. B. "Scan_2026-11-08_14-01-32")
// wird NICHT durch ein zweites Datum ergänzt.
function vorschlagDateiname(korbName) {
  var stamm = String(korbName || "").replace(/\.[^.]+$/, "");
  if (/\d{4}-\d{2}-\d{2}/.test(stamm)) {
    return stamm + ".pdf";
  }
  var heute = new Date().toLocaleDateString("sv-SE"); // YYYY-MM-DD
  return heute + " – " + stamm + ".pdf";
}

function ladeAblageOrte() {
  return api("/api/ablage/ordner-liste", "GET").then(function (d) {
    speicherortDaten = d.speicherorte || [];
    var sel = document.getElementById("wahl-speicherort");
    sel.innerHTML = speicherortDaten.map(function (s) {
      return '<option value="' + esc(s.speicherort) + '">' + esc(s.label) + "</option>";
    }).join("");
    // Vorschlagsliste füllen; der Ordnername selbst bleibt zunaechst leer.
    ladeOrdnerVorschlaege();
  });
}

function aktuelleSpeicherortDaten() {
  var name = document.getElementById("wahl-speicherort").value;
  for (var i = 0; i < speicherortDaten.length; i++) {
    if (speicherortDaten[i].speicherort === name) return speicherortDaten[i];
  }
  return speicherortDaten.length ? speicherortDaten[0] : null;
}

// Füllt die Vorschlagsliste der vorhandenen Ordner (datalist).
function ladeOrdnerVorschlaege() {
  var daten = aktuelleSpeicherortDaten();
  var ordner = daten ? daten.ordner || [] : [];
  var dl = document.getElementById("ordner-vorschlaege");
  dl.innerHTML = ordner.map(function (o) {
    return '<option value="' + esc(o) + '"></option>';
  }).join("");
  var hinweis = document.getElementById("ordner-hinweis");
  hinweis.textContent = ordner.length
    ? "Vorhanden: " + ordner.join(", ") +
      " – oder einen neuen Namen eingeben."
    : "Noch keine Ordner vorhanden – der Name wird beim Ablegen angelegt.";
}

function setzeOrdner(name) {
  document.getElementById("wahl-ordner").value = name || "";
  zeigeWahlPfad();
}

function zeigeWahlPfad() {
  var daten = aktuelleSpeicherortDaten();
  var el = document.getElementById("wahl-pfad");
  if (!daten) { el.textContent = ""; return; }
  var ordner = document.getElementById("wahl-ordner").value.trim();
  var voll = daten.host_pfad + (ordner ? "/" + ordner : "");
  var vorhanden = ordner && (daten.ordner || []).indexOf(ordner) !== -1;
  el.textContent = voll + (ordner && !vorhanden ? "  (wird neu angelegt)" : "");
}

document.getElementById("wahl-speicherort").addEventListener("change", function () {
  ladeOrdnerVorschlaege();
  zeigeWahlPfad();
});
document.getElementById("wahl-ordner").addEventListener("input", zeigeWahlPfad);

// Zurück aus Schritt 4 zur Quelle (Scanner-Einstellungen bzw. Dateiauswahl).
document.getElementById("btn-zurueck-4").addEventListener("click", function () {
  leereErgebnis();
  // Schritte 4 und 5 bleiben sichtbar stehen.
  zeigeSchritt(2);
  document.getElementById("scan-einstellungen").scrollIntoView({ block: "start" });
});

// Scanner-Schritt: zurück zu den Einstellungen.
document.getElementById("scan-zurueck-2").addEventListener("click", function () {
  document.getElementById("scan-ausfuehren").hidden = true;
  zeigeSchritt(2);
  setzeKnopfZustand();
  document.getElementById("scan-einstellungen").scrollIntoView({ block: "start" });
});

// Zurück zur Quellauswahl (Scanner- bzw. Upload-Schritt verlassen).
document.getElementById("scan-zurueck-1").addEventListener("click", function () {
  document.getElementById("scan-ausfuehren").hidden = true;
  // Schritte 4 und 5 bleiben sichtbar stehen.
  zeigeSchritt(2);
  setzeKnopfZustand();
  document.getElementById("scan-einstellungen").scrollIntoView({ block: "start" });
});

// Schritt "Ziel wählen" -> weiter zur Zusammenfassung.
document.getElementById("btn-weiter").addEventListener("click", function () {
  if (!gewaehlt) return;
  var fehler = pruefeAngaben();
  if (fehler) { zeigeErgebnis(fehler, true); return; }

  var daten = aktuelleSpeicherortDaten();
  var ordner = document.getElementById("wahl-ordner").value.trim();
  var dateiname = document.getElementById("wahl-dateiname").value.trim();
  var vorhanden = (daten.ordner || []).indexOf(ordner) !== -1;

  document.getElementById("zusammenfassung").innerHTML =
    "<div><strong>" + esc(dateiname) + "</strong></div>" +
    '<div class="klein">' + esc(daten.host_pfad + "/" + ordner) + "</div>" +
    '<div class="klein">' +
      (vorhanden ? "Ordner ist vorhanden." : "Ordner wird neu angelegt.") +
    "</div>";

  leereErgebnis();
  bereitsAbgelegt = false;
  zeigeSchritt(ausfuehrSchrittNr());
  // "Ziel wählen" bleibt sichtbar; der Ausfuehrbereich kommt dazu.
  zeigeArbeitsbereiche(true, true);
  setzeKnopfZustand();
  document.getElementById("schritt-3").scrollIntoView({ block: "start" });
});

document.getElementById("btn-zurueck").addEventListener("click", function () {
  zeigeSchritt(zielSchrittNr());
  // Zurück heisst: der Schritt ist wieder bearbeitbar.
  bereitsAbgelegt = false;
  setzeKnopfZustand();
  // Beide Bereiche bleiben sichtbar – es wird nichts ausgeblendet.
  document.getElementById("schritt-2").scrollIntoView({ block: "start" });
});

// Prüft Ordner und Dateiname; liefert eine Meldung oder null.
function pruefeAngaben() {
  var daten = aktuelleSpeicherortDaten();
  if (!daten) return "Kein Speicherort verfügbar.";
  if (!document.getElementById("wahl-ordner").value.trim()) {
    return "Bitte einen Ordnernamen angeben.";
  }
  if (!document.getElementById("wahl-dateiname").value.trim()) {
    return "Bitte einen Dateinamen angeben.";
  }
  return null;
}

document.getElementById("btn-ablegen").addEventListener("click", function () {
  if (!gewaehlt) return;
  var fehler = pruefeAngaben();
  if (fehler) { zeigeErgebnis(fehler, true); return; }

  var daten = aktuelleSpeicherortDaten();
  var ordner = document.getElementById("wahl-ordner").value.trim();
  var dateiname = document.getElementById("wahl-dateiname").value.trim();

  zeigeErgebnis("Lege ab … (Texterkennung läuft)", false);
  api("/api/korb/" + encodeURIComponent(gewaehlt.name) + "/ablegen", "POST", {
    speicherort: daten.speicherort,
    pfad: ordner,
    dateiname: dateiname
  })
    .then(function (d) {
      zeigeErgebnis("Abgelegt: " + d.ziel, false);
      gewaehlt = null;
      bereitsAbgelegt = true;
      // NICHTS ausblenden: die Schritte 4 und 5 bleiben sichtbar stehen.
      zeigeSchritt(ausfuehrSchrittNr());
      setzeKnopfZustand();
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

setzeWeg("upload");
zeigeSchritt(1);
// Bereiche 4 und 5 erst zeigen, wenn ein Dokument gewählt wurde.
zeigeArbeitsbereiche(false, false);
loadKorb();
loadPruefung();
