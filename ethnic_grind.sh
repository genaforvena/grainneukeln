#!/usr/bin/env bash
# ethnic_grind.sh — grind a curated set of Asian/African rhythmic-instrument recordings through the
# cyclic pattern engine (`amc pat/cyc/rot/acc`, 2026-07-24).
#
# The pairing is the point: each source is ground on a timeline from ITS OWN tradition (djembe on the
# 12/8 standard bell, tabla on the teental theka with its khali, doira on a 9/8 aksak), so the grid
# the grains land on is the grid the material was played against — instead of the euclidean
# generator's one-beat E(k,n), which is a different metric universe from most of this music.
# The last block is the opposite move on purpose: deliberate cross-continental grafts via `src2`
# (one tradition's grid, another's material in the upper band).
#
# Every render is verified against its source with mesh-song-verify before it counts — the
# repo/mesh rule that a grind is not shipped unheard.
#
#   usage: ./ethnic_grind.sh [outdir]
set -uo pipefail
cd "$(dirname "$0")"

CLIPS=downloads/ethnic/clips
OUT="${1:-output/ethnic}"
PY=.venv/bin/python
LOG="$OUT/grind.log"
mkdir -p "$OUT"

# slug | source clip | amc params  (the recipe; `m q` unless stated)
RECIPES=(
  # -- source ground on its own tradition's timeline -----------------------------------------
  "djembe-bembe      | djembe  | m q pat bembe snap rv 0.15 s 0.95 env 10 seed 101"
  "sabar-tresillo    | sabar   | m q pat tresillo cyc 2 sw 58 acc 0,-7,-4 snap seed 102"
  "balafon-bell6     | balafon | m q pat bell6 c 300,12000 ss 1.15 seed 103"
  "mbira-bembe-rot4  | mbira   | m q pat bembe rot 4 ss 0.9 s 0.92 env 14 seed 104"
  "qraqeb-gnawa      | qraqeb  | m q pat gnawa snap rv 0.1 seed 105"
  "kebero-bell6      | kebero  | m q pat bell6 sw 66 snap s 0.9 seed 106"
  "tabla-teental     | tabla   | m q pat teental snap env 12 seed 107"
  "taiko-tresillo    | taiko   | m q pat tresillo cyc 2 rv 0.3 s 0.88 ss 0.85 seed 108"
  "janggu-jajinmori  | janggu  | m q pat jajinmori snap seed 109"
  # kendang is a bass drum (spectral centroid 776 Hz — the darkest source in the set), so the
  # raw-band render came back BELOW mesh-song-verify's mud floor (rolloff 624 < 700 Hz) — a
  # property of the material, not of the grind. The 400 Hz band-pass low cut lifts it clear
  # (1055 Hz) instead of shipping mud or, worse, relaxing the floor to make the render "pass".
  "kendang-colotomic | kendang | m q pat colotomic c 400,13000 ss 1.1 env 12 seed 110"
  "gamelan-colo-rot8 | gamelan | m q pat colotomic rot 8 env 16 s 0.95 seed 111"
  "doira-aksak9      | doira   | m q pat aksak9 snap sw 0 seed 112"
  "paigu-aksak7      | paigu   | m q pat aksak7 snap ss 1.2 seed 113"

  # -- the same material, the OTHER regime: rotation + heavy warp ----------------------------
  "djembe-bell-r6-slow | djembe | m q pat bembe rot 6 s 0.75 ss 0.7 rv 0.35 env 20 seed 201"
  "tabla-clave32       | tabla  | m q pat clave32 snap acc 0,-10,-6,-10 s 0.9 seed 202"
  "qraqeb-aksak5       | qraqeb | m q pat aksak5 sw 62 ss 1.3 seed 203"
  "mbira-khandachapu   | mbira  | m q pat khandachapu snap s 0.85 env 18 seed 204"

  # -- cross-continental grafts: one tradition's GRID, another's MATERIAL in the top band ----
  "graft-tabla-x-djembe  | tabla   | m q pat teental src2 $CLIPS/djembe.wav c 1,600;2:600,13000 snap seed 301"
  "graft-gamelan-x-qraqeb| gamelan | m q pat colotomic src2 $CLIPS/qraqeb.wav c 1,900;2:900,14000 seed 302"
  "graft-mbira-x-taiko   | mbira   | m q pat bembe src2 $CLIPS/taiko.wav c 2:1,700;700,12000 s 0.9 seed 303"
  "graft-doira-x-balafon | doira   | m q pat aksak9 src2 $CLIPS/balafon.wav c 1,800;2:800,13000 snap seed 304"
)

printf '=== ethnic grind %s ===\n' "$(date -Is)" | tee -a "$LOG"
pass=0; fail=0; unver=0

for r in "${RECIPES[@]}"; do
  slug=$(echo "${r%%|*}" | xargs)
  rest="${r#*|}"
  src=$(echo "${rest%%|*}" | xargs)
  amc=$(echo "${rest#*|}" | xargs)
  clip="$CLIPS/$src.wav"
  [ -s "$clip" ] || { echo "SKIP $slug (no clip $clip)" | tee -a "$LOG"; continue; }

  before=$(ls -t "$OUT"/*.mp3 2>/dev/null | head -1)
  t0=$(date +%s)
  if ! timeout 900 $PY main.py "$clip" "$OUT/" amc $amc >"$OUT/.$slug.render.log" 2>&1; then
    echo "RENDER-FAIL $slug (see $OUT/.$slug.render.log)" | tee -a "$LOG"; fail=$((fail+1)); continue
  fi
  t1=$(date +%s)
  newest=$(ls -t "$OUT"/*.mp3 2>/dev/null | head -1)
  if [ -z "$newest" ] || [ "$newest" = "$before" ]; then
    echo "NO-OUTPUT $slug — render exited 0 but wrote nothing" | tee -a "$LOG"; fail=$((fail+1)); continue
  fi
  final="$OUT/$slug.mp3"
  mv -f "$newest" "$final"

  verdict=$(mesh-song-verify "$clip" "$final" 2>&1 | tail -1); vrc=$?
  case $vrc in
    0) pass=$((pass+1)); tag=SONG ;;
    2) unver=$((unver+1)); tag="N/A " ;;
    *) fail=$((fail+1)); tag=DROP ;;
  esac
  printf '%-4s %-22s %4ss %7s  amc %s\n    %s\n' \
    "$tag" "$slug" "$((t1-t0))" "$(du -h "$final" | cut -f1)" "$amc" "$verdict" | tee -a "$LOG"
done

printf '=== %d song / %d dropped / %d unverifiable ===\n' "$pass" "$fail" "$unver" | tee -a "$LOG"
