#!/bin/bash
# One-command, per-user Apple Silicon installer. Compatible with macOS Bash 3.2.
set -euo pipefail
say() { printf '[Caravan] %s\n' "$*"; }
trap 'code=$?; say "Setup stopped. Models and existing settings were not removed. Fix the error above, then rerun the same command." >&2; exit "$code"' ERR
fail() { say "$*" >&2; exit 1; }
usage() {
  printf '%s\n' 'Usage: bash scripts/install.sh [--role lead|worker] [--repo PATH] [--ref REF]' \
    '       [--python PATH] [--check] [--dry-run] [--no-start] [--update] [--use-existing]' \
    'Worker plan: --model PATH [--counts K,K,... --stage-index I --listen HOST:PORT]' \
    '             [--upstream HOST:PORT | --peer HOST:PORT] [--name ID] [--port PORT]' \
    'Each Mac gets its browser page; a fixed-model worker is a developer option.'
}
ROLE=lead
WEB_PORT=8190
REPO="$HOME/.caravan/src/caravan"
REF=caravan-v3-mlx-split
PYTHON=""
DRY=0
START=1
UPDATE=0
EXISTING=0
CHECK=0
MODEL=0
STAGE=0
SERVICE_ARGS=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --check) CHECK=1; shift ;;
    --dry-run) DRY=1; shift ;;
    --no-start) START=0; shift ;;
    --update) UPDATE=1; shift ;;
    --use-existing) EXISTING=1; shift ;;
    --replace-old-services) SERVICE_ARGS+=(--replace-old-services); shift ;;
    --role|--repo|--ref|--python)
      [ "$#" -ge 2 ] || fail "$1 needs a value."
      case "$1" in
        --role) ROLE=$2 ;; --repo) REPO=$2 ;; --ref) REF=$2 ;; --python) PYTHON=$2 ;;
      esac
      shift 2 ;;
    --model|--counts|--stage-index|--listen|--upstream|--peer|--name|--port|--host|--lead-port)
      [ "$#" -ge 2 ] || fail "$1 needs a value."
      [ "$1" != --model ] || MODEL=1
      case "$1" in --counts|--stage-index|--listen|--upstream|--peer) STAGE=1 ;; esac
      [ "$1" != --port ] || WEB_PORT=$2
      SERVICE_ARGS+=("$1" "$2"); shift 2 ;;
    *) fail "Unknown option: $1. Use --help." ;;
  esac
done
case "$WEB_PORT" in ''|*[!0-9]*|??????*) fail 'Choose a port number from 1 to 65535.' ;; esac
[ "$WEB_PORT" -ge 1 ] && [ "$WEB_PORT" -le 65535 ] || fail 'Choose a port number from 1 to 65535.'
[ "$ROLE" = lead ] || [ "$ROLE" = worker ] || fail 'Choose --role lead or --role worker.'
[ "$ROLE" != lead ] || [ "$MODEL" = 0 ] || fail 'Install the web UI as lead first; use caravan_service.py for an optional model auto-start plan.'
if [ "$ROLE" = worker ] && [ "$MODEL" = 0 ] && [ "$STAGE" = 1 ]; then
  fail 'Worker stage options need an installed --model folder. No worker was configured.'
fi
case "$REPO" in /*) ;; *) fail '--repo must be an absolute path (use "$HOME/...", not a literal ~).' ;; esac
case "$REF" in ''|-*) fail '--ref must name a Git branch or tag.' ;; esac
[ "$REPO" != / ] && [ "$REPO" != "$HOME" ] || fail 'Choose a dedicated Caravan folder, not / or your home folder.'
if [ "$DRY" = 1 ]; then
  say 'PREVIEW ONLY: no directories, downloads, packages, config or launchd jobs will change.'
else
  [ "$(uname -s)" = Darwin ] || fail 'This installer needs macOS. Nothing was installed.'
  [ "$(uname -m)" = arm64 ] || fail 'Use an Apple Silicon Mac and a native Terminal (not Rosetta). Nothing was installed.'
  MACOS=$(sw_vers -productVersion)
  [ "${MACOS%%.*}" -ge 14 ] || fail "macOS 14 or newer is required (found $MACOS)."
  [ "$(id -u)" != 0 ] || fail 'Run as your normal macOS user, not sudo/root.'
fi
if [ -z "$PYTHON" ]; then
  for candidate in /opt/homebrew/bin/python3 /Library/Frameworks/Python.framework/Versions/Current/bin/python3 "$(command -v python3 || true)"; do
    if [ -x "$candidate" ] && "$candidate" -c 'import sys;sys.exit(sys.version_info < (3,10))' >/dev/null 2>&1; then
      PYTHON=$candidate; break
    fi
  done
fi
[ -n "$PYTHON" ] && [ -x "$PYTHON" ] || fail 'Use the no-prerequisites Mac bootstrap in INSTALL.md, or pass --python /absolute/path/python3 (3.10+).'
"$PYTHON" -c 'import sys;sys.exit(sys.version_info < (3,10))' || fail 'Python 3.10 or newer is required.'
if [ "$DRY" = 0 ]; then
  "$PYTHON" -c 'import platform,sys;sys.exit(platform.machine() != "arm64")' || fail 'This Python is running under Rosetta. Choose a native arm64 Python.'
fi
if [ "$CHECK" = 1 ]; then
  exec "$PYTHON" "$(cd "$(dirname "$0")/.." && pwd)/tools/caravan_doctor.py" --port "$WEB_PORT"
fi
if [ "$DRY" = 0 ]; then
  FREE=$(df -Pk "$HOME" | awk 'END {print $4}')
  [ "$FREE" -ge 8388608 ] || fail 'Free at least 8 GB before installing; models need more.'
fi
say "Python: $PYTHON"
say "Source folder: $REPO ($REF)"
run() {
  if [ "$DRY" = 1 ]; then printf '[Caravan] Would run: '; printf '%q ' "$@"; printf '\n'; else "$@"; fi
}
# Reuse matching checkouts. Never reset, force, change branches or overwrite work.
if [ -d "$REPO/.git" ]; then
  REMOTE=$(git -C "$REPO" remote get-url origin)
  case "$REMOTE" in https://github.com/linuxbren/caravan.git|git@github.com:linuxbren/caravan.git|https://github.com/linuxbren/caravan) ;;
    *) fail "That checkout has a different origin. Reuse it manually or choose a new folder." ;;
  esac
  [ -z "$(git -C "$REPO" status --porcelain)" ] || fail 'Your checkout has local changes. Keep them; commit or choose a different folder before installing.'
  CURRENT=$(git -C "$REPO" symbolic-ref --short -q HEAD || git -C "$REPO" describe --tags --exact-match HEAD || true)
  [ "$CURRENT" = "$REF" ] || fail "Checkout is $CURRENT, not $REF. No branch was changed."
  if [ "$UPDATE" = 1 ]; then
    git -C "$REPO" symbolic-ref -q HEAD >/dev/null || fail 'A release tag is immutable; choose a new install folder to change releases.'
    run git -C "$REPO" pull --ff-only origin "$REF"
  else
    say 'Matching clean checkout found; leaving its code unchanged. Use --update for a clean fast-forward pull.'
  fi
elif [ -e "$REPO" ]; then
  if [ "$EXISTING" = 1 ] && [ -f "$REPO/proxy/web_server.py" ] && [ -f "$REPO/tools/caravan_service.py" ]; then
    say 'Using existing extracted source; no Git operations.'
  else
    fail 'That folder already exists and is not a recognized checkout. Use --use-existing for an extracted release, or choose an empty path.'
  fi
else
  [ "$EXISTING" = 0 ] || fail '--use-existing needs an existing Caravan source folder.'
  if [ "$DRY" = 0 ]; then
    command -v git >/dev/null || fail 'Git is missing. Install Apple Command Line Tools first (xcode-select --install), then retry.'
    git --version >/dev/null || fail 'Finish installing Apple Command Line Tools, then retry.'
  fi
  run mkdir -p "$(dirname "$REPO")"
  run git clone --branch "$REF" --single-branch https://github.com/linuxbren/caravan.git "$REPO"
fi
VENV="$HOME/.caravan/venvs/mlx"
if [ ! -x "$VENV/bin/python" ]; then
  run "$PYTHON" -m venv "$VENV"
else
  say 'Reusing the MLX virtual environment.'
  if [ "$DRY" = 0 ]; then
    "$VENV/bin/python" -c 'import sys,platform;sys.exit(sys.version_info < (3,10) or platform.machine() != "arm64")' || fail 'Existing venv is incompatible; choose a compatible environment manually. It was not removed.'
  fi
fi
say 'Installing tested dependencies; this may use the internet.'
if [ -f "$REPO/.caravan-package" ]; then
  [ -f "$REPO/requirements-mac.lock" ] || fail 'Package dependency lock is missing. Download a current package.'
  "$PYTHON" -c 'import sys;sys.exit(sys.version_info[:2] != (3,12))' || fail 'The easy package needs its managed Python 3.12. Rerun the Mac bootstrap.'
  run "$VENV/bin/python" -m pip install --only-binary=:all: -r "$REPO/requirements-mac.lock"
else
  # Developer source installs retain the documented Python 3.10+ path.
  run "$VENV/bin/python" -m pip install -r "$REPO/requirements-mac.txt"
fi
run "$VENV/bin/python" -m pip check
run "$VENV/bin/python" -c 'import mlx.core, mlx_lm, huggingface_hub, spake2, cryptography;print("Mac environment imports OK")'
run "$VENV/bin/python" "$REPO/agent/llama_runtime.py"
run "$VENV/bin/python" "$REPO/tools/caravan_path.py" install
# Every fresh browser install gets a single-local-node config. Never replace existing settings.
CONFIG="$HOME/.caravan/config.toml"
FRESH_CONFIG=0
if { [ "$ROLE" = lead ] || [ "$MODEL" = 0 ]; } && [ ! -e "$CONFIG" ]; then
  FRESH_CONFIG=1
  if [ "$DRY" = 1 ]; then
    say 'Would create a single-local-Mac config (no lab SSH defaults).'
  else
    mkdir -p "$HOME/.caravan"
    (set -o noclobber; printf '%s\n' '[web.nodes.local]' 'label = "My Mac"' 'role = "lead"' 'host = "local"' > "$CONFIG")
    say 'Created the local Mac config. Existing configs are never replaced.'
  fi
fi
# Stable command location; only publish after successful install/preparation.
register_command() {
if [ "$DRY" = 0 ]; then
  mkdir -p "$HOME/.caravan/bin"
  WRAPPER="$HOME/.caravan/bin/caravan"
  if [ -e "$WRAPPER" ] && ! /usr/bin/grep -q '^# Caravan managed command$' "$WRAPPER"; then
    fail 'An unrelated ~/.caravan/bin/caravan exists. Keep it; choose a different command path manually.'
  fi
  { printf '%s\n' '#!/bin/bash' '# Caravan managed command'; printf 'exec %q %q "$@"\n' "$VENV/bin/python" "$REPO/tools/caravan.py"; } > "$WRAPPER"
  chmod 755 "$WRAPPER"
  if [ -f "$REPO/.caravan-package" ]; then printf '%s\n' "$ROLE" > "$REPO/.caravan-role"; fi
fi
}
if [ "$ROLE" = lead ]; then
  KIND=web
elif [ "$MODEL" = 1 ]; then
  KIND=worker
else
  KIND=web
  say "Preparing this Mac’s browser page so it can join your other Macs."
fi
SERVICE=("$VENV/bin/python" "$REPO/tools/caravan_service.py" install --kind "$KIND" --repo "$REPO" --python "$VENV/bin/python")
if [ "$START" = 0 ]; then SERVICE+=(--no-start); fi
if [ "$DRY" = 1 ]; then
  SERVICE+=(--dry-run)
  run "${SERVICE[@]}" ${SERVICE_ARGS[@]+"${SERVICE_ARGS[@]}"}
else
  "${SERVICE[@]}" ${SERVICE_ARGS[@]+"${SERVICE_ARGS[@]}"}
fi
register_command
say 'Open a new Terminal window to use caravan (for example: caravan status).'
say 'Done. Caravan starts at user login, not before login. Choose a model in the browser.'
if [ "$KIND" = web ]; then
  if [ "$FRESH_CONFIG" = 1 ]; then run "$VENV/bin/python" "$REPO/tools/caravan_pairing.py" prepare; fi
  say "Open http://127.0.0.1:$WEB_PORT/ (local browser). To add a Mac, choose Add Macs. Logs: ~/.caravan/logs/"
fi
