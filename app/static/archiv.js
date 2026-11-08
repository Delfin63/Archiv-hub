"use strict";

// Gemeinsame Helfer für alle Seiten des Archiv-Hub.

function esc(s) {
  return String(s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}

function archivLogout() {
  fetch("/logout", { method: "POST", credentials: "same-origin" })
    .finally(function () { window.location.href = "/login"; });
}

// fetch-JSON-Helfer: liefert das JSON, wirft bei !ok und leitet bei 401 auf
// die Anmeldung um.
function api(url, method, body) {
  var opt = { method: method, headers: {} };
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
