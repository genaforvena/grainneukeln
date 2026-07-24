#!/usr/bin/env bash
# gong_grind.sh — grind a curated set of GONG-CHIME recordings at their FULL 3-4 minute length
# (2026-07-24). Sibling to ethnic_grind.sh, which grinds 35s clips; the point of this one is that
# the whole source goes on the grind, not an excerpt.
#
# WHY FULL LENGTH IS ITS OWN CLAIM: the mesh's standing grind path (mesh-room-music) trims its feed
# to CAP_SECS=90 before it ever reaches the mixer, so every mix the reflex has ever shipped is a
# 35-90s excerpt. That cap belongs to the reflex, not to the mixer — measured here 2026-07-24:
# 96s source -> 102s render (8s wall, 650MB RSS); 224s source -> 236s render (16s wall, 1.05GB RSS).
# Cost is linear, so a 4-minute grind is ~30s and ~1.2GB. The gate below asserts the render actually
# came back at source length: a mix silently truncated to an excerpt is exactly the failure this
# script exists to rule out, and it is invisible in the audio.
#
# THE PAIRING: gong-chime traditions carry the cycle in COLOTOMIC PUNCTUATION — which gong sounds on
# which slot of the cycle — not in a stroke-density groove. So the Balinese/Javanese/Maguindanao
# sources ride `colotomic` (gong on 1, kenong on the 4s, kempul between), the Burmese hsaing waing
# sources ride an explicit si/wa clapper cycle, and the Vietnamese/Bidayuh sources ride an explicit
# interlocking-hocket cycle. Named-library entries are reductions, not transcriptions (see
# automixer/iterators/patterns.py) — the point is to put the grid in the right metric universe.
#
# Every render is verified against ITS OWN source with mesh-song-verify before it counts.
#
#   usage: ./gong_grind.sh [outdir]
set -uo pipefail
cd "$(dirname "$0")"

FULL=downloads/ethnic/gong/full
OUT="${1:-output/gong}"
PY=.venv/bin/python
LOG="$OUT/grind.log"
mkdir -p "$OUT"

# A render is only "full length" if it came back at least this fraction of the source. The grind
# stretches slightly (grain overlap), so the real risk is truncation, never overrun.
MIN_RATIO=0.80

# slug | source (basename in $FULL) | amc params
RECIPES=(
  # -- each gong tradition on the colotomic/punctuation grid it actually plays ---------------
  "besakih-colotomic   | gonggede-besakih | m q pat colotomic env 16 s 0.95 seed 901"
  "pura-colo-rot8      | gonggede-pura    | m q pat colotomic rot 8 ss 1.1 s 0.92 seed 902"
  "javanese-colotomic  | javanese-bronze  | m q pat colotomic snap env 14 seed 903"
  "kulintang-colotomic | kulintang-chime  | m q pat colotomic snap ss 1.15 seed 904"
  # kulintang binalig: the agong pair marks a duple cycle under the melodic kulintang row —
  # explicit rather than the Javanese reduction, since the punctuation is 2-gong not 3.
  "kulintangph-binalig | kulintang-ph     | m q pat xx.xx.x. cyc 2 acc 0,-13,-13,-6,-13,-13 c 300,14000 seed 905"
  # hsaing waing: the si (bell) / wa (clapper) cycle — all slots struck, the cycle lives in which
  # slot is si and which is wa. Same shape as a theka: accent, not density.
  "hsaingwaing-siwa    | hsaingwaing      | m q pat xxxxxxxx cyc 4 acc 0,-12,-6,-12,-3,-12,-6,-12 snap seed 906"
  "natpwe-siwa-rot4    | natpwe-kyiwaing  | m q pat xxxxxxxx cyc 4 rot 4 acc 0,-12,-6,-12,-3,-12,-6,-12 ss 1.2 seed 907"
  # Central Highlands cong chieng / Bidayuh: interlocking hocket — each player owns one gong and
  # one slot, so the cycle is a handoff, modelled as a 6-slot pattern with a 3-value accent cycle.
  "vietnam-hocket      | vietnam-gong     | m q pat xx.xx. cyc 2 acc 0,-10,-5 snap seed 908"
  "bidayuh-hocket-rot2 | bidayuh-gongs    | m q pat xx.xx. cyc 2 rot 2 acc 0,-10,-5 s 0.9 env 18 seed 909"

  # -- the same material, the other regime: heavy warp + rotation ---------------------------
  "besakih-slow-r8     | gonggede-besakih | m q pat colotomic rot 8 s 0.75 ss 0.7 rv 0.35 env 22 seed 921"
  "kulintang-aksak9    | kulintang-chime  | m q pat aksak9 snap sw 58 seed 922"
  "hsaingwaing-jaji    | hsaingwaing      | m q pat jajinmori snap s 0.88 env 16 seed 923"

  # -- cross-tradition grafts: one gong culture's GRID, another's BRONZE in the top band -----
  "graft-bali-x-burma    | gonggede-besakih | m q pat colotomic src2 $FULL/hsaingwaing.wav c 1,900;2:900,14000 snap seed 931"
  "graft-kulintang-x-viet| kulintang-chime  | m q pat colotomic src2 $FULL/vietnam-gong.wav c 1,800;2:800,13000 seed 932"
  "graft-java-x-bidayuh  | javanese-bronze  | m q pat colotomic src2 $FULL/bidayuh-gongs.wav c 2:1,700;700,12000 s 0.9 seed 933"
)

printf '=== gong grind (full length) %s ===\n' "$(date -Is)" | tee -a "$LOG"
pass=0; fail=0; unver=0; short=0

for r in "${RECIPES[@]}"; do
  slug=$(echo "${r%%|*}" | xargs)
  rest="${r#*|}"
  src=$(echo "${rest%%|*}" | xargs)
  amc=$(echo "${rest#*|}" | xargs)
  wav="$FULL/$src.wav"
  [ -s "$wav" ] || { echo "SKIP $slug (no source $wav)" | tee -a "$LOG"; continue; }
  sdur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$wav")

  before=$(ls -t "$OUT"/*.mp3 2>/dev/null | head -1)
  t0=$(date +%s)
  if ! timeout 1800 $PY main.py "$wav" "$OUT/" amc $amc >"$OUT/.$slug.render.log" 2>&1; then
    echo "RENDER-FAIL $slug (see $OUT/.$slug.render.log)" | tee -a "$LOG"; fail=$((fail+1)); continue
  fi
  t1=$(date +%s)
  newest=$(ls -t "$OUT"/*.mp3 2>/dev/null | head -1)
  # A rejected amc config still exits 0 and leaves the PREVIOUS render newest — which would then be
  # renamed under this slug (caught 2026-07-24 in the ethnic run). Freshness, not exit code.
  if [ -z "$newest" ] || [ "$newest" = "$before" ]; then
    echo "NO-OUTPUT $slug — render exited 0 but wrote nothing" | tee -a "$LOG"; fail=$((fail+1)); continue
  fi
  final="$OUT/$slug.mp3"
  mv -f "$newest" "$final"

  # THE FULL-LENGTH GATE — the whole point of this script. A truncated mix is inaudible as a fault.
  odur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$final")
  # Compare at FULL precision and round only for display. Deciding from the rounded string lets
  # 179/224 = 0.7991 print as "0.80" and pass a 0.80 floor — the verdict must come from the number,
  # never from its printed form.
  ratio=$(awk -v o="$odur" -v s="$sdur" 'BEGIN{ if(s+0>0) printf "%.2f", o/s; else print "0" }')
  if awk -v o="$odur" -v s="$sdur" -v m="$MIN_RATIO" 'BEGIN{exit !(s+0>0 && o/s < m+0)}'; then
    printf 'SHORT %-20s render %.0fs vs source %.0fs (%sx) — TRUNCATED, not a full-length mix\n' \
      "$slug" "$odur" "$sdur" "$ratio" | tee -a "$LOG"
    short=$((short+1)); continue
  fi

  verdict=$(mesh-song-verify "$wav" "$final" 2>&1 | tail -1); vrc=$?
  case $vrc in
    0) pass=$((pass+1)); tag=SONG ;;
    2) unver=$((unver+1)); tag="N/A " ;;
    *) fail=$((fail+1)); tag=DROP ;;
  esac
  printf '%-4s %-20s %4ss  %3.0fs/%3.0fs (%sx) %7s  amc %s\n    %s\n' \
    "$tag" "$slug" "$((t1-t0))" "$odur" "$sdur" "$ratio" "$(du -h "$final" | cut -f1)" "$amc" "$verdict" \
    | tee -a "$LOG"
done

printf '=== %d song / %d dropped / %d truncated / %d unverifiable ===\n' \
  "$pass" "$fail" "$short" "$unver" | tee -a "$LOG"
