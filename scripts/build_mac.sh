#!/bin/bash
# Build PDFRedactor.app. Run this on a Mac. Python is needed only for this step.
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt -r requirements-mac.txt

iconset="build/icon.iconset"
mkdir -p "$iconset"
src="redactor/static/icon.png"
for size in 16 32 128 256 512; do
  sips -z "$size" "$size" "$src" --out "$iconset/icon_${size}x${size}.png" >/dev/null
  double=$((size * 2))
  sips -z "$double" "$double" "$src" --out "$iconset/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$iconset" -o redactor/static/icon.icns

python3 -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name PDFRedactor \
  --icon redactor/static/icon.icns \
  --osx-bundle-identifier regenerous.PDFRedactor \
  --collect-all pymupdf \
  --collect-all webview \
  --hidden-import webview.platforms.cocoa \
  --add-data "redactor/static:redactor/static" \
  launch.py

test -d dist/PDFRedactor.app
test -x dist/PDFRedactor.app/Contents/MacOS/PDFRedactor
find dist/PDFRedactor.app -name index.html | grep -q index.html

rm -f dist/PDFRedactor-mac.zip
ditto -c -k --keepParent dist/PDFRedactor.app dist/PDFRedactor-mac.zip
echo "Mac app: $(pwd)/dist/PDFRedactor-mac.zip"
