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
  const has = (key) => Object.prototype.hasOwnProperty.call(table, key);
  // T.has: is there text for this key (for keys built from a server code).
  T.has = has;
  // Plurals: "<key>_one" / "<key>_other", filled with {count} (Day 32).
  // English: "one" only for exactly 1. Other languages can add forms here.
  T.pluralForm = (count) => (Number(count) === 1 ? "one" : "other");
  T.plural = (key, count, vars) => {
    const full = `${key}_${T.pluralForm(count)}`;
    return T(has(full) ? full : `${key}_other`, Object.assign({count}, vars || {}));
  };
  // Numbers: T.num(x, 1) is x.toFixed(1) with the language's decimal mark
  // (fmt.decimal, "." in English). Units come from fmt.* keys.
  T.num = (value, digits) => {
    const out = Number(value).toFixed(digits || 0);
    const dec = has("fmt.decimal") ? table["fmt.decimal"] : ".";
    return dec === "." ? out : out.replace(".", dec);
  };
  T.unit = (unit, value, digits) => T(`fmt.${unit}`, {n: T.num(value, digits)});
  // Lists: T.join(items) uses fmt.list_sep (", "); kind "clause" ("; "),
  // "and" (" and ") or "or" (" or "). T.andList(["a","b","c"]) is "a, b and c".
  T.join = (items, kind) => Array.from(items || []).join(T(`fmt.${kind || "list"}_sep`));
  T.andList = (items) => {
    const xs = Array.from(items || []).map(String);
    return xs.length < 2 ? xs.join("") : T("fmt.and_list", {rest: T.join(xs.slice(0, -1)), last: xs[xs.length - 1]});
  };
  // Ordinals: T.ordinal(2) is "2nd" (fmt.ordinal_one/two/few/other).
  T.ordinal = (n) => {
    const a = Math.abs(Math.trunc(Number(n))), m10 = a % 10, m100 = a % 100;
    const form = m10 === 1 && m100 !== 11 ? "one" : m10 === 2 && m100 !== 12 ? "two" : m10 === 3 && m100 !== 13 ? "few" : "other";
    return T(`fmt.ordinal_${form}`, {n: Math.trunc(Number(n))});
  };
  root.T = T;
  root.caravanLang = root.CARAVAN_LANG || "en";
  if (typeof module === "object" && module.exports) module.exports = {T};
})(typeof window !== "undefined" ? window : globalThis);
