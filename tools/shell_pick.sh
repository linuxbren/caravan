_caravan_ui_lang() {
  _caravan_norm_lang() {
    c=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr '_' '-' | cut -d. -f1)
    case "$c" in
      es|es-*) printf '%s' es ;;
      en|en-*) printf '%s' en ;;
      ja|ja-*) printf '%s' ja ;;
      ru|ru-*) printf '%s' ru ;;
      zh-hant|zh-hant-*) printf '%s' zh-Hant ;;
      zh-hans|zh-hans-*) printf '%s' zh-Hans ;;
      zh-tw|zh-tw-*|zh-hk|zh-hk-*|zh-mo|zh-mo-*) printf '%s' zh-Hant ;;
      zh-cn|zh-cn-*|zh-sg|zh-sg-*|zh) printf '%s' zh-Hans ;;
      *) printf '%s' "$c" ;;
    esac
  }
  _caravan_have_lang() {
    case "$1" in
      __HAVE__) return 0 ;;
      *) return 1 ;;
    esac
  }
  if [ -n "${CARAVAN_LANG:-}" ]; then
    n=$(_caravan_norm_lang "$CARAVAN_LANG")
    if _caravan_have_lang "$n"; then printf '%s' "$n"; return; fi
  fi
  if [ -f "${HOME}/.caravan/prefs" ]; then
    p=$(sed -n 's/.*"language"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "${HOME}/.caravan/prefs" | head -n 1)
    if [ -n "$p" ]; then
      n=$(_caravan_norm_lang "$p")
      if _caravan_have_lang "$n"; then printf '%s' "$n"; return; fi
    fi
  fi
  if command -v defaults >/dev/null 2>&1; then
    for tag in $(defaults read -g AppleLanguages 2>/dev/null | tr -d '"(),' ); do
      [ -n "$tag" ] || continue
      n=$(_caravan_norm_lang "$tag")
      if _caravan_have_lang "$n"; then printf '%s' "$n"; return; fi
    done
  fi
  if [ -n "${LC_ALL:-}" ] && [ "${LC_ALL}" != "C" ] && [ "${LC_ALL}" != "POSIX" ]; then
    n=$(_caravan_norm_lang "$LC_ALL")
    if _caravan_have_lang "$n"; then printf '%s' "$n"; return; fi
  fi
  if [ -n "${LANG:-}" ] && [ "${LANG}" != "C" ] && [ "${LANG}" != "POSIX" ]; then
    n=$(_caravan_norm_lang "$LANG")
    if _caravan_have_lang "$n"; then printf '%s' "$n"; return; fi
  fi
  printf '%s' en
}
CARAVAN_UI_LANG=$(_caravan_ui_lang)
