#!/usr/bin/env bash
# Build the BITS final dissertation PDF.
set -euo pipefail
cd "$(dirname "$0")"

# Also expose figures folder next to main.tex via symlink for graphicspath fallback
if [ ! -e figures ] && [ -d ../../figures ]; then
  ln -s ../../figures figures
fi

echo "== Pass 1: xelatex =="
xelatex -interaction=nonstopmode -halt-on-error main.tex >/dev/null

echo "== bibtex =="
bibtex main >/dev/null || true

echo "== Pass 2: xelatex =="
xelatex -interaction=nonstopmode -halt-on-error main.tex >/dev/null

echo "== Pass 3: xelatex =="
xelatex -interaction=nonstopmode -halt-on-error main.tex >/dev/null

echo "\n== SUCCESS =="
ls -la main.pdf
