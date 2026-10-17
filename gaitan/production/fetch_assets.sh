#!/usr/bin/env bash
# Download the archival photographs listed in assets/manifest.json.
# Needs network access to upload.wikimedia.org. Re-check each licence on its Commons page first.
set -euo pipefail
cd "$(dirname "$0")/../assets/archival"
UA="GaitanDocumentary/1.0 (educational short; contact: repository owner)"
fetch() { curl -fsSL -A "$UA" -o "$1" "$2" && echo "ok  $1  $(identify -format '%wx%h' "$1" 2>/dev/null)"; }
fetch gaitan_1936.jpg               "https://upload.wikimedia.org/wikipedia/commons/3/3c/Jorge_Eli%C3%A9cer_Gait%C3%A1n_%281936%29.jpg"
fetch bogotazo_tranvia_1948.jpg     "https://upload.wikimedia.org/wikipedia/commons/5/57/Bogotazo.jpg"
# Provenance of this one is unverified (unknown author); uncomment only after checking it:
# fetch marcha_del_silencio_1948.jpg "https://upload.wikimedia.org/wikipedia/commons/9/90/Jorge-eliecer-gait%C3%A1n.jpg"
