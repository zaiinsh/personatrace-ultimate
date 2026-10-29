/* PersonaTrace v9 GUI i18n — UI chrome only.
   Translations live in /static/i18n.json (en/ur/ar/es/fr/de, full key
   parity). The chosen language persists in localStorage; ur/ar switch
   the document to RTL. Live investigation content is NOT translated. */
(function () {
  var RTL = { ur: true, ar: true };
  var dict = null;
  function apply(lang) {
    if (!dict || !dict.strings[lang]) lang = "en";
    var strings = dict.strings[lang];
    document.documentElement.lang = lang;
    document.documentElement.dir = RTL[lang] ? "rtl" : "ltr";
    document.querySelectorAll("[data-i18n]").forEach(function (el) {
      var key = el.getAttribute("data-i18n");
      if (strings[key]) el.textContent = strings[key];
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach(function (el) {
      var key = el.getAttribute("data-i18n-placeholder");
      if (strings[key]) el.setAttribute("placeholder", strings[key]);
    });
    var sel = document.getElementById("lang-select");
    if (sel) sel.value = lang;
    try { localStorage.setItem("pt-lang", lang); } catch (e) {}
  }
  function init() {
    var saved = "en";
    try { saved = localStorage.getItem("pt-lang") || "en"; } catch (e) {}
    fetch("/static/i18n.json").then(function (r) { return r.json(); }).then(function (data) {
      dict = data;
      var sel = document.getElementById("lang-select");
      if (sel) sel.addEventListener("change", function () { apply(sel.value); });
      apply(saved);
    }).catch(function () { /* English static HTML remains */ });
  }
  window.PT_I18N = { apply: apply, init: init };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
