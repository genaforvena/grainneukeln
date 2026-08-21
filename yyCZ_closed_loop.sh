#!/usr/bin/env bash
# yyCZ_closed_loop.sh — DJ Screw "My Mind Went Blank" (yt yyCZtDbVeAA, 397.5s screwed),
# CLOSED-LOOP ONLY, big variety (2026-07-25, operator: "all closed loops only but big variety on
# 'my mind goes blank' dj screw").
#
# ALL CLOSED LOOP means every render here comes from `--uxn-ctrl --uxn-feedback`: the ROM
# (uxn_ctrl/paramgen.rom) picks l/w/s/c/ss/m, and the audio answers back — a per-tick regional
# rhythm_density XOR-perturbs the c-band index. There are NO hand-written treatments in this
# script, which is the whole difference from yt_yyCZ_grind.sh (20 open-loop recipes typed by hand).
# rw is off the mode table upstream; q/poly/lib each get a third.
#
# WHERE THE VARIETY COMES FROM — two independent axes multiplied, because one source cannot supply
# both:
#
#  1. THE ROM WALK. stride 461 (co-prime with 256) carries into the high bits every tick, so all
#     four axes packed two-bits-each into tick_lo advance together instead of only `l` moving.
#     Each segment's --uxn-start continues the previous segment's walk, so the batch is ONE
#     non-repeating 24-tick sequence, not 8 copies of the same 3 recipes. Verified by preview
#     before writing this: the 24 ticks cover all 4 values of l, w, s, c and ss, and all 3 modes.
#     (Preview is OPEN-loop; the feedback byte moves `c` further at render time, so the applied
#     line is read back out of the render log, never assumed.)
#
#  2. THE MATERIAL. A screwed 6.5-minute track is not one texture — the a-cappella head, the
#     drop, the Point Blank verses and the outro are different material at the same tempo. Eight
#     segments of DIFFERENT LENGTHS (60-130s) spread across the whole 397s give the ROM eight
#     different things to be varied ABOUT. Full-source ticks would have been 24 grinds of the
#     same averaged texture.
#
# LENGTH IS A VARIABLE, NOT A CONSTANT, so a fixed "render >= 0.8x source" gate would fire on every
# legitimate fast render. Same measured relation as gong_closed_loop.sh:
#     q, poly : output ~= segment / s          (ss does not change the length)
#     lib     : output ~= segment / (s * ss)
# and the gate asserts >= half of THAT prediction — a grind that consumed only an excerpt comes
# back many times short, not slightly short.
#
#   usage: ./yyCZ_closed_loop.sh [outdir] [ticks-per-segment]
set -uo pipefail
cd "$(dirname "$0")"

SRC=downloads/yt_yyCZ_src.mp3
OUT="${1:-output/yyCZ-cl}"
TICKS="${2:-3}"
STRIDE=461
PY=.venv/bin/python
LOG="$OUT/closed-loop.log"
MIN_FRACTION_OF_PREDICTED=0.5
mkdir -p "$OUT"

# start_s:len_s — eight regions of the 397.5s track, deliberately unequal in length and
# overlapping, so no two segments are the same slice of the same texture.
SEGMENTS=(4:60 50:95 120:75 160:130 215:65 250:110 300:85 330:64)

[ -s "$SRC" ] || { echo "no source: $SRC" >&2; exit 1; }

printf '=== yyCZ closed-loop grind %s (segments=%d ticks=%s stride=%s) ===\n' \
  "$(date -Is)" "${#SEGMENTS[@]}" "$TICKS" "$STRIDE" | tee -a "$LOG"

pass=0; fail=0; short=0; unver=0; i=0
for seg in "${SEGMENTS[@]}"; do
  ss_start="${seg%%:*}"; seg_len="${seg##*:}"
  name="seg$(printf %02d $((i+1)))-${ss_start}s"
  start=$(( i * TICKS * STRIDE ))     # the walk continues across segments
  i=$((i+1))

  wav="${TMPDIR:-/tmp}/yycz-cl-$$-$name.wav"
  if ! ffmpeg -v error -y -ss "$ss_start" -t "$seg_len" -i "$SRC" -ac 2 -ar 44100 "$wav"; then
    echo "CUT-FAIL $name" | tee -a "$LOG"; fail=$((fail+1)); continue
  fi
  sdur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$wav")

  # STAGE OUTSIDE $OUTDIR — mesh-grind-deliver scans ~/grainneukeln/output RECURSIVELY every 3
  # minutes, so a stage dir under output/ races the rename and ships the render under its raw
  # auto-generated name, leaving the sent-ledger holding a name that is not on disk.
  stage="${TMPDIR:-/tmp}/yycz-cl-stage-$$-$name"; rm -rf "$stage"; mkdir -p "$stage"
  printf -- '--- %s (%.0fs of %s) start=%d\n' "$name" "$sdur" "$SRC" "$start" | tee -a "$LOG"

  if ! timeout 3600 $PY main.py "$wav" "$stage" --uxn-ctrl --uxn-feedback \
        --uxn-ticks "$TICKS" --uxn-stride "$STRIDE" --uxn-start "$start" \
        >"$OUT/.$name.render.log" 2>&1; then
    echo "RENDER-FAIL $name (see $OUT/.$name.render.log)" | tee -a "$LOG"
    fail=$((fail+1)); rm -f "$wav"; rm -rf "$stage"; continue
  fi

  # The ROM's APPLIED lines, in order — the real recipe. Not the open-loop preview: the feedback
  # byte moves the c-band, so what ran is not what a dry preview would have printed.
  mapfile -t lines < <(grep -oP '^\[uxn tick \d+\] \K.*' "$OUT/.$name.render.log")

  n=0
  for f in $(ls -tr "$stage"/*.mp3 2>/dev/null); do
    line="${lines[$n]:-}"; n=$((n+1))
    odur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f")
    s_val=$(awk '{for(j=1;j<NF;j++) if($j=="s") print $(j+1)}' <<<"$line")
    ss_val=$(awk '{for(j=1;j<NF;j++) if($j=="ss") print $(j+1)}' <<<"$line")
    mode=$(awk '{print $NF}' <<<"$line")
    pred=$(awk -v d="$sdur" -v s="${s_val:-1}" -v ss="${ss_val:-1}" -v m="$mode" \
      'BEGIN{ e = (m=="lib") ? s*ss : s; if(e+0<=0) e=1; printf "%.1f", d/e }')

    final="$OUT/yyCZ-${name}-t$((n-1))-${mode}.mp3"
    mv -f "$f" "$final"

    if awk -v o="$odur" -v p="$pred" -v k="$MIN_FRACTION_OF_PREDICTED" \
         'BEGIN{exit !(p+0>0 && o/p < k+0)}'; then
      printf 'SHORT %-34s %.0fs vs predicted %.0fs — consumed an excerpt, not the segment\n' \
        "$(basename "$final")" "$odur" "$pred" | tee -a "$LOG"
      short=$((short+1)); continue
    fi

    verdict=$(mesh-song-verify "$wav" "$final" 2>&1 | tail -1); vrc=$?
    case $vrc in
      0) pass=$((pass+1)); tag=SONG ;;
      2) unver=$((unver+1)); tag="N/A " ;;
      *) fail=$((fail+1)); tag=DROP ;;
    esac
    printf '%-4s %-36s SEG %3.0fs  ACT %4.0fs  PRED %4.0fs   %s\n      %s\n' \
      "$tag" "$(basename "$final")" "$sdur" "$odur" "$pred" "$line" "$verdict" | tee -a "$LOG"
  done
  rm -rf "$stage"; rm -f "$wav"
done

printf '=== %d song / %d dropped / %d short / %d unverifiable ===\n' \
  "$pass" "$fail" "$short" "$unver" | tee -a "$LOG"
