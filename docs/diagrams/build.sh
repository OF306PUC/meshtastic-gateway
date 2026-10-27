#!/usr/bin/env bash
# Rebuild every TikZ diagram in this folder as <name>.png (300 dpi) and <name>.pdf.
#     docs/diagrams/build.sh            # all of them
#     docs/diagrams/build.sh membership # one
# Needs pdflatex and pdftoppm (poppler-utils). palette.tex is shared, not a diagram.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
cd "$here"

# A scratch output directory with no .tex in it: TeX also looks for its input
# files in the output directory, and would pick up a stale copy from there.
out="$(mktemp -d)"
trap 'rm -rf -- "$out"' EXIT

names=("$@")
if [ ${#names[@]} -eq 0 ]; then
  for f in *.tex; do [ "$f" = palette.tex ] || names+=("${f%.tex}"); done
fi

for name in "${names[@]}"; do
  if ! pdflatex -interaction=nonstopmode -halt-on-error -output-directory="$out" \
       "$name.tex" > "$out/$name.out" 2>&1; then
    grep -A5 '^!' "$out/$name.out" >&2 || tail -20 "$out/$name.out" >&2
    echo "FAILED: $name.tex" >&2
    exit 1
  fi
  cp "$out/$name.pdf" "$name.pdf"
  pdftoppm -png -r 300 -singlefile "$name.pdf" "$name"
  echo "built $name.png, $name.pdf"
done
