"use strict";

(function () {
  var form = document.querySelector(".login-form");
  var input = document.getElementById("password");
  var msg = document.getElementById("msg");
  if (!form || !input) return;

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    if (form.dataset.submitting === "1") return;
    form.dataset.submitting = "1";

    var password = input.value;
    input.value = "";

    var body = new URLSearchParams();
    body.append("password", password);

    fetch("/login", {
      method: "POST",
      headers: {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded"
      },
      body: body.toString(),
      credentials: "same-origin"
    })
      .then(function (response) {
        return response.json().then(function (data) {
          return { ok: response.ok, data: data };
        });
      })
      .then(function (result) {
        if (result.ok && result.data.ok) {
          window.location.href = result.data.next || "/";
          return;
        }
        msg.textContent = result.data.error || "Anmeldung fehlgeschlagen.";
        input.focus();
      })
      .catch(function () {
        msg.textContent = "Anmeldung fehlgeschlagen. Bitte versuche es erneut.";
        input.focus();
      })
      .then(function () {
        form.dataset.submitting = "";
      });
  });
})();
