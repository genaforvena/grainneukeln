#!/usr/bin/env bash
# yyCZ_full_closed_loop.sh — 25 mixes of the FULL DJ Screw "My Mind Went Blank" tape
# (yt yyCZtDbVeAA, 397.5s), closed-loop, driven by the purpose-built uxn_ctrl/paramgen-screw.rom.
# 2026-07-25, operator: "use full track of dj screw and make 25 different interesting mixes
# (please be creative with knobs)" — under the standing "all closed loops only".
#
# FULL TRACK, NOT SEGMENTS. The earlier batch cut eight regions because one source cannot supply
# both material variety and knob variety. With a custom ROM the knobs supply all of it, so the
# segmenting is unnecessary — and it was costing the thing a screwed tape is actually for, which is
# LENGTH: a 6.6-minute source at s 0.5 is a 13-minute render, and that only exists if the whole
# tape goes in.
#
# WHERE THE 25 RECIPES COME FROM. paramgen-screw.rom (see uxn_ctrl/paramgen-screw.tal for the
# tables and why each one is what it is). Two things make it different from the shared ROM:
# the mode strings carry their own sub-knobs (euclid ek/en, snap, swing, gap-fill gain, polyrhythm
# ratios incl. band-split streams, library cluster count + sim/contrast) — reachable because
# run_uxn_sequence hands the emitted line to config_automix as "amc <line>", so `m` was always the
# tail of an amc fragment — and the mode table is MOD 7 rather than MOD 3.
#
# VERIFIED BEFORE RUNNING, not assumed: at stride 461 the 25 ticks emit 25 DISTINCT lines and cover
# all 4 values of l, w, s, c and ss and all 7 mode recipes. Twelve strides were ticked to pick that
# one (701 and 1361 reach only 6 modes; 1013 only 3 ss values). The preview is open-loop; the
# feedback byte moves `c` further at render time, so the applied line is read back out of the
# render log and never assumed.
#
# ONE PROCESS PER TICK, and that is not a performance choice — it is the only way each render is
# actually the recipe its log line says it is. `amc` is a PARTIAL update: config_automix reads
# every param as `current value if the token is absent` (cutter/sample_cut_tool.py:408 onward), so
# within a process each tick INHERITS whatever the previous tick set and did not mention. That was
# harmless while the ROM emitted all six axes every tick — l/w/s/c/ss/m always present is a full
# overwrite. It stops being harmless the moment the mode strings carry sub-knobs, because no tick
# mentions another recipe's knobs: `ek 3 en 8 fg -3` stays set through the poly and lib ticks that
# follow it, `snap`/`sw 66` leak from one q recipe into the other, `pr` streams leak into lib.
# MEASURED, not reasoned: the first 5-tick chunk left every staged filename carrying `k3_n8` from
# tick 0's euclid, and its *lib* render carrying `st[{'ratio': 5}, ...]` — poly's stream config,
# one tick later, in a library-mode render. Each tick now starts from AutoMixerConfig defaults.
# The cost is the per-process source load + beat detection (~1 min of the ~3 min per render);
# --uxn-start keeps the walk continuous, so it is still one 25-tick sequence.
#
# LENGTH IS THE POINT HERE, so the "did it consume the whole source" gate uses the same measured
# relation as gong_closed_loop.sh and asserts >= half of it:
#     q, poly : output ~= source / s          (ss does not change the length)
#     lib     : output ~= source / (s * ss)
#
#   usage: ./yyCZ_full_closed_loop.sh [outdir] [total-ticks] [ticks-per-chunk] [first-tick]
set -uo pipefail
cd "$(dirname "$0")"

SRC=downloads/yt_yyCZ_src.mp3
OUT="${1:-output/yyCZ-full-cl}"
TOTAL="${2:-25}"
CHUNK="${3:-1}"
FIRST="${4:-0}"
STRIDE=461
ROM=uxn_ctrl/paramgen-screw.rom
PY=.venv/bin/python
LOG="$OUT/closed-loop.log"
MIN_FRACTION_OF_PREDICTED=0.5
MAX_MB=45                       # TG ceiling is 50MB; re-encode before we get there
mkdir -p "$OUT"

[ -s "$SRC" ] || { echo "no source: $SRC" >&2; exit 1; }
[ -s "$ROM" ] || { echo "no ROM: $ROM (run uxn_ctrl/bin/uxnasm paramgen-screw.tal $ROM)" >&2; exit 1; }

sdur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$SRC")
printf '=== yyCZ FULL-TRACK closed-loop grind %s (%.0fs source, %s ticks, stride %s, rom %s) ===\n' \
  "$(date -Is)" "$sdur" "$TOTAL" "$STRIDE" "$(basename $ROM)" | tee -a "$LOG"

pass=0; fail=0; short=0; unver=0; idx="$FIRST"
chunk=0
while [ "$idx" -lt "$TOTAL" ]; do
  n_this=$(( TOTAL - idx )); [ "$n_this" -gt "$CHUNK" ] && n_this=$CHUNK
  start=$(( idx * STRIDE ))
  chunk=$((chunk+1))

  # STAGE OUTSIDE $OUT — mesh-grind-deliver scans ~/grainneukeln/output RECURSIVELY every 3
  # minutes, so a stage dir under output/ races the rename: the reflex ships the render under its
  # raw auto-generated name and the sent-ledger then holds a name that is not on disk.
  stage="${TMPDIR:-/tmp}/yycz-full-stage-$$-c$chunk"; rm -rf "$stage"; mkdir -p "$stage"
  rlog="$OUT/.tick$(printf %02d "$idx").render.log"
  printf -- '--- chunk %d: ticks %d..%d (uxn-start=%d)\n' \
    "$chunk" "$idx" "$((idx + n_this - 1))" "$start" | tee -a "$LOG"

  timeout 7200 $PY main.py "$SRC" "$stage" --uxn-ctrl "$ROM" --uxn-feedback \
        --uxn-ticks "$n_this" --uxn-stride "$STRIDE" --uxn-start "$start" >"$rlog" 2>&1
  rc=$?
  if [ $rc -ne 0 ]; then
    # rc=137 is the OOM killer, not a degenerate grind — say which, the log has cost that
    # confusion before.
    case $rc in
      137) echo "CHUNK-OOM   chunk $chunk killed (rc=137, out of memory) — see $rlog" ;;
      124) echo "CHUNK-TIMEOUT chunk $chunk exceeded 7200s — see $rlog" ;;
      *)   echo "CHUNK-FAIL  chunk $chunk rc=$rc — see $rlog" ;;
    esac | tee -a "$LOG"
    # renders that DID land before the failure are still on disk; fall through and keep them
  fi

  mapfile -t lines < <(grep -oP '^\[uxn tick \d+\] \K.*' "$rlog")

  # NUL-delimited, oldest first. NEVER `for f in $(ls ...)`: the engine bakes the applied recipe
  # into the render filename, and a poly `pr` stream config goes in as a Python repr —
  # `..._m-poly_k3_n8_st[{'ratio': 5}, {'ratio': 4}, {'ratio': 3}]_2026_07_25_0044.mp3`. Spaces,
  # quotes and brackets in a filename word-split under `$(ls)`, the mv fails on a fragment, and
  # the failure cascades: a `stat` on the file that was never moved fed `$(( / 1048576 ))` an
  # empty operand, and that arithmetic syntax error took the whole render loop out after ONE
  # render of twenty-five. Filenames from an engine are data, not a word list.
  mapfile -d '' -t staged < <(
    find "$stage" -maxdepth 1 -type f -name '*.mp3' -printf '%T@\t%p\0' 2>/dev/null \
      | sort -z -t $'\t' -k1,1n | cut -z -f2-)

  n=0
  for f in "${staged[@]}"; do
    [ -n "$f" ] || continue
    line="${lines[$n]:-}"; tick_i=$(( idx + n )); n=$((n+1))
    odur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f")
    s_val=$(awk '{for(j=1;j<NF;j++) if($j=="s") print $(j+1)}' <<<"$line")
    ss_val=$(awk '{for(j=1;j<NF;j++) if($j=="ss") print $(j+1)}' <<<"$line")
    l_val=$(awk '{for(j=1;j<NF;j++) if($j=="l") print $(j+1)}' <<<"$line")
    mode=$(awk '{for(j=1;j<NF;j++) if($j=="m") print $(j+1)}' <<<"$line")
    pred=$(awk -v d="$sdur" -v s="${s_val:-1}" -v ss="${ss_val:-1}" -v m="$mode" \
      'BEGIN{ e = (m=="lib") ? s*ss : s; if(e+0<=0) e=1; printf "%.1f", d/e }')

    # name carries the recipe, so a file in a TG roll is identifiable without the log
    final="$OUT/yyCZ-$(printf %02d $tick_i)-${mode:-x}-l${l_val:-x}-s${s_val:-x}.mp3"
    if ! mv -f "$f" "$final"; then
      echo "MV-FAIL $(basename "$f") — render exists but could not be named" | tee -a "$LOG"
      fail=$((fail+1)); continue
    fi

    # every size read is guarded: a missing file must render 0, never an empty arithmetic operand
    sz=$(stat -c%s "$final" 2>/dev/null || echo 0); szmb=$(( ${sz:-0} / 1048576 ))
    if [ "$szmb" -gt "$MAX_MB" ]; then
      ffmpeg -v error -y -i "$final" -b:a 128k "${final}.re.mp3" && mv "${final}.re.mp3" "$final"
      sz2=$(stat -c%s "$final" 2>/dev/null || echo 0)
      echo "      re-encoded ${szmb}MB -> $(( ${sz2:-0} / 1048576 ))MB (TG ceiling)" | tee -a "$LOG"
    fi

    if awk -v o="$odur" -v p="$pred" -v k="$MIN_FRACTION_OF_PREDICTED" \
         'BEGIN{exit !(p+0>0 && o/p < k+0)}'; then
      printf 'SHORT %-40s %.0fs vs predicted %.0fs — consumed an excerpt, not the tape\n' \
        "$(basename "$final")" "$odur" "$pred" | tee -a "$LOG"
      short=$((short+1)); continue
    fi

    verdict=$(mesh-song-verify "$SRC" "$final" 2>&1 | tail -1); vrc=$?
    case $vrc in
      0) pass=$((pass+1)); tag=SONG ;;
      2) unver=$((unver+1)); tag="N/A " ;;
      *) fail=$((fail+1)); tag=DROP ;;
    esac
    printf '%-4s %-40s SRC %3.0fs  ACT %4.0fs  PRED %4.0fs\n      %s\n      %s\n' \
      "$tag" "$(basename "$final")" "$sdur" "$odur" "$pred" "$line" "$verdict" | tee -a "$LOG"
  done
  rm -rf "$stage"
  idx=$(( idx + n_this ))
done

printf '=== %d song / %d dropped / %d short / %d unverifiable (of %d ticks) ===\n' \
  "$pass" "$fail" "$short" "$unver" "$TOTAL" | tee -a "$LOG"
