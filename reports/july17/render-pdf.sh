#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

document="${1:-gridpool-july17-research-update-v1}"
input="${document%.md}.md"
output="${document%.md}.pdf"

if [[ ! -f "$input" ]]; then
  echo "Input document not found: $input" >&2
  exit 1
fi

mkdir -p .texcache/texmf-var .texcache/texmf-cache
export TEXMFVAR="$PWD/.texcache/texmf-var"
export TEXMFCACHE="$PWD/.texcache/texmf-cache"

pandoc "$input" \
  --from markdown+yaml_metadata_block \
  --to pdf \
  --pdf-engine=lualatex \
  --toc \
  --number-sections \
  -o "$output"
