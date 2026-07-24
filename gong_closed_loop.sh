#!/usr/bin/env bash
# gong_closed_loop.sh — grind the gong-chime corpus from the Uxn ROM, CLOSED-LOOP, at full source
# length (2026-07-24, operator: "use closed loop, more interesting and diverse params, use q or lib
# or poly, not rw, different lengths speeds etc").
#
# Where gong_grind.sh hand-writes each recipe, here the recipes come from uxn_ctrl/paramgen.rom and
# every tick's `c`-band choice is perturbed by a feedback byte measured from the rhythm density of
# the REGION of audio that tick is working over (--uxn-feedback). The ROM decides; the audio
# answers back.
#
# THREE THINGS HAD TO CHANGE IN THE ROM/DRIVER FOR THIS TO BE WORTH RUNNING:
#
#  1. `rw` is out of the mode table. The mode index was `mode_tick & 3` over a 4-slot table, so
#     simply deleting one mode would have re-weighted the survivors 2:1:1 — it is MOD 3 now, and
#     q/poly/lib each get exactly a third.
#  2. The tables were widened. s and ss had been narrowed to 0.8-1.2, which is four ways of saying
#     "about normal"; grain length now spans 120-2000ms (the [120,2000] contract mesh-sound-reflex's
#     derive() clamps to) and s/ss straddle 1.0 in both directions.
#  3. A STRIDE. This is the one that actually mattered: the ROM packs l/w/s/c into two bits each of
#     a single byte, so CONSECUTIVE ticks only ever move `l`. A 12-tick run at stride 1 is one
#     speed and one band-split from end to end — it looks varied in the log because `l` is moving.
#     Stride 461 (co-prime with 256) carries into the high bits every tick; 12 ticks then cover all
#     4 values of all 4 axes, all 4 ss values and all 3 modes. Each source also gets a `--uxn-start`
#     that continues the previous source's walk, so the batch is one non-repeating sequence rather
#     than N copies of the same recipes.
#
# LENGTH IS NOW A VARIABLE, NOT A CONSTANT — which is the point ("different lengths speeds"), and
# it means gong_grind.sh's "render >= 0.80x source" gate would fire on every legitimate fast render.
# Measured relation (n=3, then re-checked across this batch — see PRED/ACT in the log):
#     q, poly : output ~= source / s          (ss does not change the length)
#     lib     : output ~= source / (s * ss)
# so the gate asserts the render is at least HALF its predicted length. That still catches the
# failure it exists to catch — a grind that consumed only an excerpt comes back many times short,
# not slightly short — without calling a deliberate 2.1x speed-up a truncation.
#
#   usage: ./gong_closed_loop.sh [outdir] [ticks-per-source]
set -uo pipefail
cd "$(dirname "$0")"

FULL=downloads/ethnic/gong/full
OUT="${1:-output/gong-cl}"
TICKS="${2:-3}"
STRIDE=461
PY=.venv/bin/python
LOG="$OUT/closed-loop.log"
mkdir -p "$OUT"

# One source per tradition — the duplicates (gonggede-pura, kulintang-ph, natpwe) sit this out so
# the batch spends its ticks on distinct material.
SOURCES=(gonggede-besakih kulintang-chime hsaingwaing vietnam-gong bidayuh-gongs javanese-bronze)

MIN_FRACTION_OF_PREDICTED=0.5

printf '=== gong closed-loop grind %s (ticks=%s stride=%s) ===\n' "$(date -Is)" "$TICKS" "$STRIDE" \
  | tee -a "$LOG"

pass=0; fail=0; short=0; unver=0; i=0
for src in "${SOURCES[@]}"; do
  wav="$FULL/$src.wav"
  [ -s "$wav" ] || { echo "SKIP $src (no source)" | tee -a "$LOG"; continue; }
  sdur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$wav")
  start=$(( i * TICKS * STRIDE ))
  i=$((i+1))

  stage="$OUT/.stage-$src"; rm -rf "$stage"; mkdir -p "$stage"
  printf -- '--- %s (%.0fs) start=%d\n' "$src" "$sdur" "$start" | tee -a "$LOG"

  if ! timeout 3600 $PY main.py "$wav" "$stage" --uxn-ctrl --uxn-feedback \
        --uxn-ticks "$TICKS" --uxn-stride "$STRIDE" --uxn-start "$start" \
        >"$OUT/.$src.render.log" 2>&1; then
    echo "RENDER-FAIL $src (see $OUT/.$src.render.log)" | tee -a "$LOG"; fail=$((fail+1)); continue
  fi

  # The ROM's applied lines, in order — the render's real recipe, not the open-loop preview (the
  # feedback byte moves the c-band, so what ran is NOT what a dry preview would have printed).
  mapfile -t lines < <(grep -oP '^\[uxn tick \d+\] \K.*' "$OUT/.$src.render.log")

  n=0
  for f in $(ls -tr "$stage"/*.mp3 2>/dev/null); do
    line="${lines[$n]:-}"; n=$((n+1))
    odur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f")
    s_val=$(awk '{for(j=1;j<NF;j++) if($j=="s") print $(j+1)}' <<<"$line")
    ss_val=$(awk '{for(j=1;j<NF;j++) if($j=="ss") print $(j+1)}' <<<"$line")
    mode=$(awk '{print $NF}' <<<"$line")
    # predicted length: lib stretches by ss as well as s; q/poly do not
    pred=$(awk -v d="$sdur" -v s="${s_val:-1}" -v ss="${ss_val:-1}" -v m="$mode" \
      'BEGIN{ e = (m=="lib") ? s*ss : s; if(e+0<=0) e=1; printf "%.1f", d/e }')

    final="$OUT/${src}-t$((n-1))-${mode}.mp3"
    mv -f "$f" "$final"

    if awk -v o="$odur" -v p="$pred" -v k="$MIN_FRACTION_OF_PREDICTED" \
         'BEGIN{exit !(p+0>0 && o/p < k+0)}'; then
      printf 'SHORT %-28s %.0fs vs predicted %.0fs — consumed an excerpt, not the source\n' \
        "$(basename "$final")" "$odur" "$pred" | tee -a "$LOG"
      short=$((short+1)); continue
    fi

    verdict=$(mesh-song-verify "$wav" "$final" 2>&1 | tail -1); vrc=$?
    case $vrc in
      0) pass=$((pass+1)); tag=SONG ;;
      2) unver=$((unver+1)); tag="N/A " ;;
      *) fail=$((fail+1)); tag=DROP ;;
    esac
    printf '%-4s %-30s SRC %3.0fs  ACT %4.0fs  PRED %4.0fs   %s\n      %s\n' \
      "$tag" "$(basename "$final")" "$sdur" "$odur" "$pred" "$line" "$verdict" | tee -a "$LOG"
  done
  rmdir "$stage" 2>/dev/null
done

printf '=== %d song / %d dropped / %d short / %d unverifiable ===\n' \
  "$pass" "$fail" "$short" "$unver" | tee -a "$LOG"
