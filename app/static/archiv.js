"use strict";

// Gemeinsame Helfer für alle Seiten des Archiv-Hub.

function esc(s) {
  return String(s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}

// CSRF-Token der Sitzung (von base.html als window.ARCHIV_HUB_CSRF gesetzt).
// Wird bei allen zustandsändernden Anfragen als Header mitgeschickt.
function archivCsrf() {
  return window.ARCHIV_HUB_CSRF || "";
}

function archivLogout() {
  fetch("/logout", {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": archivCsrf() }
  }).finally(function () { window.location.href = "/login"; });
}

// fetch-JSON-Helfer: liefert das JSON, wirft bei !ok und leitet bei 401 auf
// die Anmeldung um.
function api(url, method, body) {
  var opt = {
    method: method,
    credentials: "same-origin",
    headers: { "X-CSRF-Token": archivCsrf() }
  };
  if (body) {
    opt.headers["Content-Type"] = "application/json";
    opt.body = JSON.stringify(body);
  }
  return fetch(url, opt).then(function (r) {
    if (r.status === 401) {
      window.location.href = "/login";
      throw new Error("nicht angemeldet");
    }
    return r.json().then(function (j) {
      if (!j.ok) { throw new Error(j.error || "Fehler"); }
      return j;
    });
  });
}

function setStatus(msg, kind) {
  var el = document.getElementById("status");
  if (!el) return;
  el.className = kind === "error" ? "msg error" : "msg ok";
  el.textContent = msg;
}
