// Caravan's user-facing text, looked up by key (Day 32 localization, step 1).
// The server puts English plus the chosen language into window.CARAVAN_STRINGS
// (see tools/caravan_i18n.py). T("key") returns that text; T("key", {n: 3})
// fills {n}. (Named T, not t: many functions already use t as a local.) A missing key falls back to English, then to the key itself.
// In Node (tests) the English file is read directly.
(function (root) {
  let table = root.CARAVAN_STRINGS;
  if (!table && typeof require === "function") {
    try { table = require("../../locales/en.json"); } catch (e) { table = {}; }
  }
  table = table || {};
  function fill(text, vars) {
    return text.replace(/\{\{|\}\}|\{([A-Za-z0-9_]+)\}/g, (m, name) => {
      if (m === "{{") return "{";
      if (m === "}}") return "}";
      return Object.prototype.hasOwnProperty.call(vars, name) ? String(vars[name]) : m;
    });
  }
  function T(key, vars) {
    const text = Object.prototype.hasOwnProperty.call(table, key) ? table[key] : key;
    return vars ? fill(text, vars) : text;
  }
  root.T = T;
  root.caravanLang = root.CARAVAN_LANG || "en";
  if (typeof module === "object" && module.exports) module.exports = {T};
})(typeof window !== "undefined" ? window : globalThis);
