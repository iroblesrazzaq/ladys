#!/usr/bin/env bash
# Download public FALCON calibration NWBs into the layout the inventory notebook expects:
#   data/falcon/{H1,H2,M1-A,M1-B,M2,B1}/<dandiset-id>/sub-*/...
#
# From the repo root:
#   pip install dandi          # already a LaDyS dependency
#   bash data/download_falcon.sh
#
# ~19 GB total. M2 is ~16 GB because it includes 30 kHz fullband voltage.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${ROOT}/data/falcon"

if ! command -v dandi >/dev/null 2>&1; then
  echo "dandi not found. Install with: pip install dandi" >&2
  exit 1
fi

# dandi download DANDI:<id> -o <folder> writes <folder>/<id>/sub-...
datasets=(
  "000954:H1"
  "000950:H2"
  "000941:M1-A"
  "001209:M1-B"
  "000953:M2"
  "001046:B1"
)

echo "Downloading public FALCON NWBs into ${DEST}"
echo "About 19 GB total (M2 alone is ~16 GB)."
for item in "${datasets[@]}"; do
  dandiset="${item%%:*}"
  name="${item##*:}"
  out="${DEST}/${name}"
  mkdir -p "${out}"
  echo "==> DANDI:${dandiset} -> ${out}"
  dandi download "DANDI:${dandiset}" -o "${out}"
done

echo "Done. Expected tree:"
echo "  data/falcon/H1/000954/sub-HumanPitt-held-in-calib/*.nwb"
echo "  data/falcon/H2/000950/sub-T5-held-in-calib/*.nwb"
echo "  data/falcon/M1-A/000941/sub-MonkeyL-held-in-calib/*.nwb"
echo "  data/falcon/M1-B/001209/sub-MonkeyX-held-in-calib/*.nwb"
echo "  data/falcon/M2/000953/sub-MonkeyN-held-in-calib/*.nwb"
echo "  data/falcon/B1/001046/sub-Finch-z-r12r13-21-held-in-calib/*.nwb"
