"use strict";

// Scan-Seite: Quellen-Auswahl oben, darunter Scan-Einstellungen und der
// Aufnahmebereich der Quelle. Weitere Quellen werden über data/scanner.json
// ergänzt; diese Datei und /scan bleiben unverändert. Alle Quellen laufen am
// Ende über /api/upload (Texterkennung, Klassifizierung, Ablage).

var SCANNER_KEY = "archiv-hub.scanner";

var quellen = [];
var aktuelleQuelle = null;
var vorschauUrls = [];

// Aufbau je Quelltyp (nur der Aufnahmebereich). Für unbekannte Typen fällt der
// Browser auf "kamera" zurück (einfache Dateiauswahl).
var QUELLEN_UI = {
  kamera: function () {
    return '<input type="file" id="scan-datei" accept="image/*,.pdf" multiple>';
  },

  netzwerk: function () {
    return '<p class="klein">Netzwerk-Scanner (Scan-to-Folder): Die Dateien werden über einen Netzwerkordner bereitgestellt.</p>';
  }
};

function quelleById(id) {
  for (var i = 0; i < quellen.length; i++) {
    if (quellen[i].id === id) return quellen[i];
  }
  return null;
}

function merkeQuelle(id) {
  try {
    localStorage.setItem(SCANNER_KEY, id);
  } catch (e) {
    /* localStorage nicht verfügbar – ignorieren */
  }
}

function letzteQuelle() {
  try {
    return localStorage.getItem(SCANNER_KEY);
  } catch (e) {
    return null;
  }
}

function setErgebnis(text, kind) {
  var el = document.getElementById("ergebnis");
  el.className = kind === "error" ? "msg error" : kind === "ok" ? "msg ok" : "msg";
  el.textContent = text;
}

function leseEinstellungen() {
  return {
    quelle: document.getElementById("scan-quelle").value,
    aufloesung: document.getElementById("scan-aufloesung").value,
    groesse: document.getElementById("scan-groesse").value,
    format: document.getElementById("scan-format").value,
    duplex: document.getElementById("scan-duplex").checked,
    ocr: document.getElementById("scan-ocr").checked
  };
}

function renderQuelle(id) {
  var q = quelleById(id) || quellen[0];
  if (!q) return;

  aktuelleQuelle = q;
  document.getElementById("scan-titel").textContent = q.name;
  var inhalt = document.getElementById("scan-inhalt");
  var builder = QUELLEN_UI[q.typ] || QUELLEN_UI.kamera;
  inhalt.innerHTML = builder();

  clearVorschau();
  bindAufnahme(q);
}

function bindAufnahme(q) {
  if (q.typ !== "kamera") return;
  var input = document.getElementById("scan-datei");
  if (input) {
    input.addEventListener("change", function () {
      renderVorschau(Array.prototype.slice.call(input.files || []));
    });
  }
}

function clearVorschau() {
  vorschauUrls.forEach(function (url) { URL.revokeObjectURL(url); });
  vorschauUrls = [];
  var el = document.getElementById("scan-vorschau");
  if (el) el.innerHTML = "";
}

function renderVorschau(files) {
  clearVorschau();
  var el = document.getElementById("scan-vorschau");
  if (!el) return;

  el.innerHTML = files.map(function (file) {
    var name = esc(file.name);
    if (file.type && file.type.indexOf("image/") === 0) {
      var url = URL.createObjectURL(file);
      vorschauUrls.push(url);
      return (
        '<div class="vorschau-eintrag">' +
        '<img src="' + url + '" alt="">' +
        '<div class="vorschau-name">' + name + "</div>" +
        "</div>"
      );
    }
    return (
      '<div class="vorschau-eintrag">' +
      '<div class="vorschau-icon">PDF</div>' +
      '<div class="vorschau-name">' + name + "</div>" +
      "</div>"
    );
  }).join("");
}

function scanAusfuehren() {
  var q = aktuelleQuelle;
  if (!q) return;

  var einstellungen = leseEinstellungen();

  if (q.typ === "kamera") {
    var input = document.getElementById("scan-datei");
    var files = input && input.files ? Array.prototype.slice.call(input.files) : [];
    if (!files.length) {
      setErgebnis("Keine Datei gewählt.", "error");
      return;
    }
    var kette = Promise.resolve();
    files.forEach(function (file) {
      kette = kette.then(function () { return verarbeiteDatei(file, einstellungen); });
    });
  } else {
    setErgebnis("Scan-Auslösung für dieses Gerät ist noch nicht eingerichtet.", "error");
  }
}

function verarbeiteDatei(file, einstellungen) {
  var fd = new FormData();
  fd.append("file", file);
  if (einstellungen) {
    fd.append("ocr", einstellungen.ocr ? "1" : "0");
    fd.append("format", einstellungen.format);
    fd.append("aufloesung", einstellungen.aufloesung);
    fd.append("groesse", einstellungen.groesse);
    fd.append("quelle", einstellungen.quelle);
    fd.append("duplex", einstellungen.duplex ? "1" : "0");
  }
  setErgebnis("Verarbeite " + file.name + " …", "");
  return fetch("/api/upload", { method: "POST", body: fd, credentials: "same-origin" })
    .then(function (r) {
      return r.json().then(function (d) { return { ok: r.ok, d: d }; });
    })
    .then(function (res) {
      if (!res.ok) {
        setErgebnis(res.d.error || "Fehler bei der Verarbeitung.", "error");
        return;
      }
      if (res.d.status === "abgelegt") {
        setErgebnis("Abgelegt – " + esc(res.d.original_filename) + " → " + esc(res.d.ziel), "ok");
      } else {
        setErgebnis("Zur Prüfung – " + esc(res.d.original_filename), "ok");
      }
    })
    .catch(function () {
      setErgebnis("Fehler bei der Verarbeitung.", "error");
    });
}

async function loadScanner() {
  try {
    var j = await api("/api/scanner", "GET");
    quellen = j.scanner || [];
  } catch (e) {
    setErgebnis("Scanner konnten nicht geladen werden: " + e.message, "error");
    return;
  }

  var sel = document.getElementById("scanner-wahl");
  sel.innerHTML = quellen.map(function (q) {
    return '<option value="' + esc(q.id) + '">' + esc(q.name) + "</option>";
  }).join("");

  var letzte = letzteQuelle();
  if (letzte && quelleById(letzte)) {
    sel.value = letzte;
  }
  sel.addEventListener("change", function () {
    merkeQuelle(sel.value);
    renderQuelle(sel.value);
  });

  document.getElementById("scan-btn").addEventListener("click", scanAusfuehren);

  renderQuelle(sel.value);
}

loadScanner();
