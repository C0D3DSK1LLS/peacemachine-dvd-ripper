#!/bin/sh
# One install layout, shared by every package format.
#   usage: install-files.sh SOURCE_TREE DESTDIR [PREFIX]
# SOURCE_TREE is the checked-out project (the directory holding app.py).
set -eu

SRC="${1:?source tree}"
DEST="${2:?destdir}"
PREFIX="${3:-/usr}"
NAME=peacemachine-dvd-ripper

datadir="$DEST$PREFIX/share/$NAME"
docdir="$DEST$PREFIX/share/doc/$NAME"

install -d "$datadir/gtk-4.0" "$docdir" \
           "$DEST$PREFIX/bin" "$DEST$PREFIX/share/applications"

install -m644 "$SRC/app.py" "$SRC/ripper.py" "$SRC/names.py" "$datadir/"
install -m644 "$SRC/LICENSE" "$datadir/LICENSE"
install -m644 "$SRC/README.md" "$docdir/README.md"
install -m644 "$SRC/LICENSE" "$docdir/copyright"

install -m644 "$SRC/theme/gtk-4.0/"*.css "$datadir/gtk-4.0/"
install -m644 "$SRC/theme/gtk-4.0/settings.ini" "$datadir/gtk-4.0/"
install -d "$datadir/gtk-4.0/art"
install -m644 "$SRC/theme/gtk-4.0/art/"*.png "$datadir/gtk-4.0/art/"

install -Dm755 "$SRC/packaging/launcher/peacemachine-dvd-ripper" \
    "$DEST$PREFIX/bin/$NAME"
install -Dm644 "$SRC/packaging/desktop/org.jimmy.DvdRipper.desktop" \
    "$DEST$PREFIX/share/applications/org.jimmy.DvdRipper.desktop"

# Optional speech-to-text helper. Its virtualenv and models are never shipped.
if [ -f "$SRC/asr/transcribe.py" ]; then
    install -d "$datadir/asr"
    install -m644 "$SRC/asr/transcribe.py" "$datadir/asr/transcribe.py"
fi
