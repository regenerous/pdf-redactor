#!/bin/bash
# Combine an Apple silicon PDFRedactor.app and an Intel one into one app.
# Usage: merge_mac_apps.sh arm64.app x86_64.app output.app
set -euo pipefail

arm=$1
x86=$2
out=$3

if [[ ! -d "$arm" || ! -d "$x86" ]]; then
  echo "Both inputs must be PDFRedactor.app bundles." >&2
  exit 1
fi

rm -rf "$out"
mkdir -p "$(dirname "$out")"
cp -R "$arm" "$out"
rm -rf "$out/Contents/_CodeSignature"

is_macho() {
  file -b "$1" | grep -q 'Mach-O'
}

merge_file() {
  local rel=$1
  local a="$arm/$rel"
  local b="$x86/$rel"
  local dest="$out/$rel"

  case "$rel" in
    Contents/_CodeSignature|Contents/_CodeSignature/*) return ;;
  esac

  if [[ -d "$b" && ! -L "$b" ]]; then
    mkdir -p "$dest"
    return
  fi
  if [[ ! -e "$a" ]]; then
    mkdir -p "$(dirname "$dest")"
    cp -R "$b" "$dest"
    return
  fi
  if [[ -d "$a" && ! -L "$a" ]]; then
    return
  fi
  if [[ -L "$a" || -L "$b" ]]; then
    if [[ -L "$a" && -L "$b" && "$(readlink "$a")" == "$(readlink "$b")" ]]; then
      return
    fi
    echo "Symlink differs: $rel" >&2
    exit 1
  fi
  if cmp -s "$a" "$b"; then
    return
  fi
  if is_macho "$a" && is_macho "$b"; then
    lipo -create "$a" "$b" -output "$dest.universal"
    mv "$dest.universal" "$dest"
    return
  fi
  echo "Keeping the Apple silicon copy of $rel"
}

while IFS= read -r -d '' path; do
  rel="${path#"$x86"/}"
  if [[ -z "$rel" || "$rel" == "$path" ]]; then
    continue
  fi
  merge_file "$rel"
done < <(find "$x86" -print0)

fail=0
checked=0
while IFS= read -r -d '' path; do
  if ! is_macho "$path"; then
    continue
  fi
  checked=$((checked + 1))
  archs=$(lipo -archs "$path")
  echo "$archs  ${path#"$out"/}"
  case "$archs" in
    *x86_64*) ;;
    *) echo "Missing Intel slice: $path" >&2; fail=1 ;;
  esac
  case "$archs" in
    *arm64*) ;;
    *) echo "Missing Apple silicon slice: $path" >&2; fail=1 ;;
  esac
done < <(find "$out" -type f -print0)

echo "Checked $checked native files."
if [[ "$fail" -ne 0 || "$checked" -eq 0 ]]; then
  echo "The merged app is not universal." >&2
  exit 1
fi

codesign --force --deep --sign - "$out"
codesign --verify --verbose=2 "$out"
echo "Universal app: $out"
