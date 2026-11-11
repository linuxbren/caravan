#!/bin/bash
# Reproducible source artifact from committed Git tree, never working files.
set -euo pipefail
REF=${1:?Usage: package.sh REF OUTPUT_DIRECTORY}
OUT=${2:?Usage: package.sh REF OUTPUT_DIRECTORY}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
SHA=$(git -C "$ROOT" rev-parse --verify "$REF^{commit}")
mkdir -p "$OUT"; OUT=$(cd "$OUT" && pwd)
FILE="caravan-mac-source-$SHA.tar.gz"
[ ! -e "$OUT/$FILE" ] || { printf '%s\n' 'Artifact exists; choose a fresh output folder.' >&2; exit 1; }
git -C "$ROOT" archive --format=tar --prefix=caravan/ "$SHA" | gzip -n > "$OUT/$FILE"
(cd "$OUT" && shasum -a 256 "$FILE" > "$FILE.sha256")
printf 'Source commit: %s\nArchive: %s/%s\n' "$SHA" "$OUT" "$FILE"
printf '%s\n' 'Not a signed Mac app. Models/Python/runtime downloaded separately; see INSTALL.md.'
