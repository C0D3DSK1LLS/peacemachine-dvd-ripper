#!/bin/sh
# Build the source tarball that AUR, COPR and the OBS all consume.
# Only tracked files go in, so untracked state and virtualenvs can never leak.
#
#   usage: make-tarball.sh [OUTPUT_DIR]
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VERSION=$(sed -n 's/^APP_VERSION *= *"\(.*\)"/\1/p' "$ROOT/app.py" | head -n 1)
[ -n "$VERSION" ] || { echo "no APP_VERSION in app.py" >&2; exit 1; }

OUT=${1:-"$ROOT/dist"}
mkdir -p "$OUT"

NAME="peacemachine-dvd-ripper-$VERSION"
TARBALL="$OUT/$NAME.tar.gz"

git -C "$ROOT" archive \
    --format=tar.gz \
    --prefix="$NAME/" \
    -o "$TARBALL" HEAD

echo "$TARBALL"
( cd "$OUT" && sha256sum "$NAME.tar.gz" )
