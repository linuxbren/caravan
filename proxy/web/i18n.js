// Caravan's user-facing text, looked up by key (Day 32 localization).
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
  const lang = root.CARAVAN_LANG || "en";
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
  T.has = has;

  function primary(code) {
    return String(code || lang || "en").split("-")[0].toLowerCase();
  }
  // CLDR cardinals: es/en one/other; ru one/few/many/other; ja/zh other only.
  T.pluralForm = (count, code) => {
    const p = primary(code);
    const n = Number(count);
    const i = Math.trunc(Math.abs(n));
    const s = String(count).replace(/^[+-]/, "");
    const v = s.includes(".") ? s.split(".")[1].length : 0;
    if (p === "ja" || p === "zh" || p === "ko" || p === "vi" || p === "th" || p === "id" || p === "ms") return "other";
    if (p === "ru") {
      if (v !== 0) return "other";
      if (i % 10 === 1 && i % 100 !== 11) return "one";
      if ([2, 3, 4].includes(i % 10) && ![12, 13, 14].includes(i % 100)) return "few";
      return "many";
    }
    if (v === 0 && i === 1) return "one";
    return "other";
  };
  T.plural = (key, count, vars) => {
    const form = T.pluralForm(count, lang);
    const full = `${key}_${form}`;
    const fallback = `${key}_other`;
    const use = has(full) ? full : fallback;
    return T(use, Object.assign({count}, vars || {}));
  };

  function regroup(out, dec, grp) {
    let sign = "";
    let body = out;
    if (body[0] === "+" || body[0] === "-") { sign = body[0]; body = body.slice(1); }
    let whole, frac = "";
    if (body.includes(".")) { const p = body.split("."); whole = p[0]; frac = dec + p[1]; }
    else whole = body;
    if (grp) {
      const parts = [];
      let digits = whole;
      while (digits.length > 3) { parts.push(digits.slice(-3)); digits = digits.slice(0, -3); }
      if (digits) parts.push(digits);
      whole = parts.reverse().join(grp);
    }
    return sign + whole + frac;
  }
  T.num = (value, digits) => {
    const out = Number(value).toFixed(digits || 0);
    const dec = has("fmt.decimal") ? table["fmt.decimal"] : ".";
    const grp = has("fmt.thousands") ? table["fmt.thousands"] : "";
    if (dec === "." && !grp) return out;
    return regroup(out, dec, grp);
  };
  T.unit = (unit, value, digits) => T(`fmt.${unit}`, {n: T.num(value, digits)});
  T.join = (items, kind) => Array.from(items || []).join(T(`fmt.${kind || "list"}_sep`));
  T.andList = (items) => {
    const xs = Array.from(items || []).map(String);
    return xs.length < 2 ? xs.join("") : T("fmt.and_list", {rest: T.join(xs.slice(0, -1)), last: xs[xs.length - 1]});
  };
  T.ordinalForm = (n, code) => {
    const p = primary(code);
    const a = Math.abs(Math.trunc(Number(n))), m10 = a % 10, m100 = a % 100;
    if (p === "ja" || p === "zh" || p === "ko" || p === "vi" || p === "th" || p === "id" || p === "ms" || p === "es" || p === "ru") return "other";
    return m10 === 1 && m100 !== 11 ? "one" : m10 === 2 && m100 !== 12 ? "two" : m10 === 3 && m100 !== 13 ? "few" : "other";
  };
  T.ordinal = (n) => {
    const form = T.ordinalForm(n, lang);
    const key = has(`fmt.ordinal_${form}`) ? `fmt.ordinal_${form}` : "fmt.ordinal_other";
    return T(key, {n: Math.trunc(Number(n))});
  };
  T.month = (month, abbr) => T(abbr ? `fmt.month_abbr_${month}` : `fmt.month_${month}`);
  T.date = (dt, style) => {
    const d = (dt instanceof Date) ? dt : new Date(dt);
    const styleKey = style === "month_year" ? "fmt.date_month_year" : style === "short" ? "fmt.date_short" : "fmt.date_month_day";
    const pad = (n) => String(n).padStart(2, "0");
    return T(styleKey, {
      month: T.month(d.getMonth() + 1, false),
      month_abbr: T.month(d.getMonth() + 1, true),
      day: String(d.getDate()),
      year: String(d.getFullYear()),
      time: `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`,
    });
  };
  root.T = T;
  root.caravanLang = lang;
  if (typeof module === "object" && module.exports) module.exports = {T};
})(typeof window !== "undefined" ? window : globalThis);
