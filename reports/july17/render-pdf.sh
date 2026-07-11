#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

mkdir -p .texcache/texmf-var .texcache/texmf-cache
export TEXMFVAR="$PWD/.texcache/texmf-var"
export TEXMFCACHE="$PWD/.texcache/texmf-cache"

pandoc gridpool-july17-handout.md \
  --from markdown+yaml_metadata_block \
  --to pdf \
  --pdf-engine=lualatex \
  --toc \
  --number-sections \
  -o gridpool-july17-handout.pdf
