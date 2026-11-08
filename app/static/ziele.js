"use strict";

var ziele = [];
var hubs = [];
var speicherorte = [];
var gewaehlterPfad = "";

function speicherortOptionen() {
  return speicherorte.map(function (s) {
    return '<option value="' + esc(s.name) + '">' + esc(s.name) + "</option>";
  }).join("");
}

function aktuellerSpeicherort() {
  var sel = document.getElementById("speicherort");
  return sel.value || (speicherorte.length ? speicherorte[0].name : "standard");
}

function speicherortByName(name) {
  for (var i = 0; i < speicherorte.length; i++) {
    if (speicherorte[i].name === name) return speicherorte[i];
  }
  return null;
}

function pfadZuString(arr) { return arr.join("/"); }

function hostPfadFuerZiel(z) {
  var s = speicherortByName(z.speicherort || "standard");
  var host = s ? s.host_pfad : "";
  var pfad = z.pfad || "";
  return host + (pfad ? "/" + pfad : "");
}

async function loadSpeicherorte() {
  try {
    var j = await api("/api/speicherorte", "GET");
    speicherorte = j.speicherorte || [];
    document.getElementById("speicherort").innerHTML = speicherortOptionen();
    var liste = document.getElementById("speicherorte-liste");
    liste.innerHTML = speicherorte.map(function (s) {
      return '<li><strong>' + esc(s.name) + '</strong> <span class="klein">(' +
        esc(s.label || "") + ") – " + esc(s.host_pfad) + "</span></li>";
    }).join("");
  } catch (e) {
    setStatus("Speicherorte konnten nicht geladen werden: " + e.message, "error");
  }
}

async function loadHubs() {
  try {
    var j = await api("/api/hubs", "GET");
    hubs = j.hubs || [];
    var sel = document.getElementById("hub");
    sel.innerHTML = '<option value="">–</option>' + hubs.map(function (h) {
      return '<option value="' + esc(h.name) + '">' + esc(h.name) + "</option>";
    }).join("");
  } catch (e) {
    setStatus("Hub-Liste konnte nicht geladen werden: " + e.message, "error");
  }
}

async function loadZiele() {
  try {
    var j = await api("/api/ziele", "GET");
    ziele = j.ziele || [];
    renderZiele();
  } catch (e) {
    setStatus("Ziele konnten nicht geladen werden: " + e.message, "error");
  }
}

function renderZiele() {
  var liste = document.getElementById("ziele-liste");
  liste.innerHTML = "";
  var badge = document.getElementById("ziele-count");
  if (badge) badge.textContent = String(ziele.length);
  document.getElementById("hinweis").innerHTML = ziele.length
    ? ""
    : '<div class="empty-state">Noch keine Ziele angelegt. Bis ein aktives Ziel existiert, landen alle Dokumente in data/zur-pruefung/.</div>';
  for (var i = 0; i < ziele.length; i++) {
    var z = ziele[i];
    var div = document.createElement("div");
    div.className = "ziel";

    var plaquen = "";
    plaquen += z.aktiv
      ? '<span class="plakette plakette-aktiv">Aktiv</span>'
      : '<span class="plakette plakette-inaktiv">Inaktiv</span>';
    plaquen += '<span class="plakette">' + esc(z.speicherort || "standard") + "</span>";
    if (z.jahresordner) plaquen += '<span class="plakette">Jahresordner</span>';
    if (z.hub) plaquen += '<span class="plakette">' + esc(z.hub) + "</span>";

    var beschreibung = z.beschreibung
      ? '<div class="ziel-beschreibung">' + esc(z.beschreibung) + "</div>"
      : "";

    div.innerHTML =
      '<div class="ziel-kopf"><strong class="ziel-name">' + esc(z.name) + "</strong>" + plaquen + "</div>" +
      '<div class="ziel-pfad">' + esc(hostPfadFuerZiel(z)) + "</div>" +
      beschreibung +
      '<div class="ziel-aktionen">' +
      '<button class="btn btn-secondary" onclick="editZiel(\'' + z.id + '\')">Bearbeiten</button>' +
      '<button class="btn btn-secondary" onclick="toggleZiel(\'' + z.id + '\')">' + (z.aktiv ? "Deaktivieren" : "Aktivieren") + "</button>" +
      '<button class="btn btn-danger" onclick="deleteZiel(\'' + z.id + '\')">Löschen</button>' +
      "</div>";
    liste.appendChild(div);
  }
}

function editZiel(id) {
  var z = null;
  for (var i = 0; i < ziele.length; i++) { if (ziele[i].id === id) { z = ziele[i]; break; } }
  if (!z) return;
  document.getElementById("ziel-id").value = z.id;
  document.getElementById("name").value = z.name || "";
  document.getElementById("speicherort").value = z.speicherort || "standard";
  document.getElementById("hub").value = z.hub || "";
  document.getElementById("beschreibung").value = z.beschreibung || "";
  document.getElementById("jahresordner").checked = !!z.jahresordner;
  document.getElementById("aktiv").checked = !!z.aktiv;
  gewaehlterPfad = z.pfad || "";
  document.getElementById("form-titel").textContent = "Ziel bearbeiten";
  loadOrdnerListe(z.pfad || "");
}

function resetForm() {
  document.getElementById("ziel-form").reset();
  document.getElementById("ziel-id").value = "";
  document.getElementById("aktiv").checked = true;
  if (speicherorte.length) document.getElementById("speicherort").value = speicherorte[0].name;
  gewaehlterPfad = "";
  document.getElementById("form-titel").textContent = "Ziel anlegen";
  loadOrdnerListe();
}

async function saveZiel() {
  var id = document.getElementById("ziel-id").value;
  var body = {
    name: document.getElementById("name").value,
    speicherort: aktuellerSpeicherort(),
    pfad: gewaehlterPfad,
    hub: document.getElementById("hub").value,
    beschreibung: document.getElementById("beschreibung").value,
    jahresordner: document.getElementById("jahresordner").checked,
    aktiv: document.getElementById("aktiv").checked
  };
  if (!body.name) { setStatus("Name ist Pflicht.", "error"); return; }
  try {
    if (id) { await api("/api/ziele/" + id, "PUT", body); } else { await api("/api/ziele", "POST", body); }
    resetForm();
    loadZiele();
    setStatus("Ziel gespeichert: " + body.name, "ok");
  } catch (e) { setStatus("Speichern fehlgeschlagen: " + e.message, "error"); }
}

async function deleteZiel(id) {
  if (!confirm("Ziel wirklich löschen? Es werden keine Dateien oder Ordner gelöscht.")) return;
  try {
    await api("/api/ziele/" + id, "DELETE");
    loadZiele();
    setStatus("Ziel gelöscht.", "ok");
  } catch (e) { setStatus("Löschen fehlgeschlagen: " + e.message, "error"); }
}

async function toggleZiel(id) {
  var z = null;
  for (var i = 0; i < ziele.length; i++) { if (ziele[i].id === id) { z = ziele[i]; break; } }
  if (!z) return;
  try {
    await api("/api/ziele/" + id, "PUT", { aktiv: !z.aktiv });
    loadZiele();
    setStatus("Ziel " + (z.aktiv ? "deaktiviert" : "aktiviert") + ".", "ok");
  } catch (e) { setStatus("Ändern fehlgeschlagen: " + e.message, "error"); }
}

// ---------------------------------------------------------------------------
// Ablageort: Speicherort + Ordner als zwei Auswahllisten.
// Kein Navigator: der Ordner wird gewählt, nicht durchgeklickt.
// ---------------------------------------------------------------------------

function renderHostPfad() {
  var el = document.getElementById("host-pfad");
  var s = speicherortByName(aktuellerSpeicherort());
  var host = s ? s.host_pfad : "";
  el.textContent = host + (gewaehlterPfad ? "/" + gewaehlterPfad : "");
}

// Füllt die Ordner-Auswahl mit allen Ordnern im gewählten Speicherort.
async function loadOrdnerListe(bevorzugt) {
  var sel = document.getElementById("ordner-wahl");
  sel.innerHTML = '<option value="">(direkt im Speicherort)</option>';
  try {
    var j = await api(
      "/api/ablage/ordner?speicherort=" + encodeURIComponent(aktuellerSpeicherort()) +
      "&pfad=",
      "GET"
    );
    var ordner = j.ordner || [];
    ordner.forEach(function (name) {
      var o = document.createElement("option");
      o.value = name;
      o.textContent = name;
      sel.appendChild(o);
    });
    if (bevorzugt) {
      sel.value = bevorzugt;
      // Falls der Ordner nicht in der Liste steht, trotzdem übernehmen.
      if (sel.value !== bevorzugt) {
        var o2 = document.createElement("option");
        o2.value = bevorzugt;
        o2.textContent = bevorzugt;
        sel.appendChild(o2);
        sel.value = bevorzugt;
      }
    }
    ordnerUebernommen();
  } catch (e) {
    setStatus("Ordner konnten nicht geladen werden: " + e.message, "error");
  }
}

function ordnerUebernommen() {
  gewaehlterPfad = document.getElementById("ordner-wahl").value || "";
  renderHostPfad();
}

async function neuerOrdner() {
  var feld = document.getElementById("neuer-ordner");
  var name = feld.value.trim();
  if (!name) { setStatus("Bitte einen Namen für den neuen Ordner angeben.", "error"); return; }
  try {
    await api("/api/ablage/ordner", "POST", {
      speicherort: aktuellerSpeicherort(),
      pfad: "",
      name: name
    });
    feld.value = "";
    // Neu anlegen heisst: sofort auswählen.
    await loadOrdnerListe(name);
    setStatus("Ordner angelegt und gewählt: " + name, "ok");
  } catch (e) {
    setStatus("Ordner anlegen fehlgeschlagen: " + e.message, "error");
  }
}

document.getElementById("ordner-wahl").addEventListener("change", ordnerUebernommen);

document.getElementById("speicherort").addEventListener("change", function () {
  gewaehlterPfad = "";
  loadOrdnerListe();
});

document.getElementById("neuer-ordner").addEventListener("keydown", function (e) {
  if (e.key === "Enter") { e.preventDefault(); neuerOrdner(); }
});

loadSpeicherorte().then(function () {
  loadHubs();
  loadZiele();
  loadOrdnerListe();
});
