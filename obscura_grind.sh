#!/usr/bin/env bash
# obscura_grind.sh — 20 granular grinds of "obscura dub" (soundcloud.com/salamaaashop/obscura-dub),
# operator ask 2026-08-14 22:26 + re-ask 22:43 (board task grind-obscura-dub).
#
# Source is a 5:32 DUB track, so the recipe set is aimed at what dub actually IS rather than a
# generic axis sweep: one-drop and steppers grids, offbeat skank, bass/skank BAND SPLITS (the c
# channel config), tape-echo reverse grains (rv), and long-envelope chamber smear (env) — plus the
# neutral/opposite regimes so the batch spans the space instead of 20 shades of one idea.
#
# Sibling of yt_ZEQC_grind.sh (window-per-mix, combo-repel) rather than gong_grind.sh (full-length):
# 20 full-length 5.5-min grinds is 110 minutes of audio for the operator to sit through. Each mix
# takes its own WINDOW of the source, walked across the track so the batch also traverses the
# arrangement, not just the parameter space.
#
# GATES (each render must EARN its delivery):
#   - fresh output: the newest mp3 must be strictly newer than the pre-render snapshot, else a
#     failed grind silently ships the PREVIOUS mix (the mesh-room-music stale-output trap).
#   - length floor: render >= 0.5x its feed. A silently truncated grind is inaudible as a fault.
#   - loudness: the automixer export does NOT normalize (verified in cutter/sample_cut_tool.py:705
#     — a bare mix.export, no gain stage), so raw grinds land at -32..-46 dBFS and the operator has
#     flagged "очень тихо" before. Every render goes through loudnorm I=-16 before it is sent.
#
# DELIVERY / DOUBLE-SEND: mesh-grind-deliver (*/3 reflex) scans ~/grainneukeln/output RECURSIVELY
# and TG's anything new, keyed on basename in ~/.mesh/room-music-sent.log. mesh-room-music --deliver
# does NOT write that ledger. So renders are staged OUTSIDE output/, delivered here with their real
# recipe as the caption, the ledger line is appended AFTER a confirmed send, and only then are they
# moved into output/obscura/ — where grind-deliver now skips them as already-sent.
#
#   usage: ./obscura_grind.sh [first_index] [last_index]
set -uo pipefail
cd "$(dirname "$0")"

SRC=downloads/obscura/obscura-dub.wav
STAGE=staging_obscura
OUT=output/obscura
PY=.venv/bin/python
LOG=downloads/obscura/grind.log
SENT_LOG="$HOME/.mesh/room-music-sent.log"
mkdir -p "$STAGE" "$OUT"

[ -s "$SRC" ] || { echo "[obscura] SRC missing: $SRC"; exit 1; }
DUR=$($PY -c "from pydub import AudioSegment as A;print(len(A.from_file('$SRC')))" 2>/dev/null || echo 0)
[ "$DUR" -gt 60000 ] || { echo "[obscura] SRC too short/unreadable (DUR=$DUR)"; exit 1; }
echo "[obscura] source ${SRC} DUR=${DUR}ms" | tee -a "$LOG"

# "amc args | feed_ms | caption". Combo-repel: no two rows share a full parameter vector.
# Feed length is held under the superslow budget — a sample_speed ss<1 stretches every grain by
# 1/ss, so the RAM a grind needs scales with feed/ss, not feed (mesh-room-music's eff_cap rule).
# Rows with ss<=0.6 therefore get short feeds; ss>=1 rows can take the long ones.
TREATMENTS=(
  # -- dub's own grids ----------------------------------------------------------------------
  "m q pat ..x. cyc 4 acc 0,-12,-3,-12 s 0.85 ss 0.9 env 14 seed 801|48000|ONE DROP · accent on 3, 1 and 4 ducked · s0.85 ss0.9"
  "m q pat x.x.x.x. cyc 4 snap s 1.0 ss 0.85 seed 802|46000|STEPPERS · four-on-floor, snapped · ss0.85"
  "m q pat .x.x cyc 2 sw 62 fg -9 seed 803|46000|SKANK · offbeat only, swung 62, quiet fill"
  "m q pat ..x. cyc 4 rot 2 acc 0,-14,-2,-14 snap s 0.8 seed 804|44000|ONE DROP rotated · half-time grid s0.8"
  "m q pat x..x..x. cyc 4 acc 0,-12,-12,-4,-12,-12,-6,-12 seed 805|46000|3-3-2 dub bassline cycle"
  # -- band splits: bass in one hand, skank in the other -------------------------------------
  "m q ek 3 en 8 c 1,180;180,14000 s 0.9 ss 0.8 env 16 seed 806|44000|BAND SPLIT · sub <180Hz vs top · E(3,8) s0.9 ss0.8"
  "m q pat ..x. cyc 4 c 1,120;120,700;700,16000 snap seed 807|42000|THREE BANDS · sub / body / air on a one-drop"
  "m poly pr 4:1-200;3:200-16000 seed 808|40000|POLY BAND · 4-stream sub against 3-stream top"
  "m q ek 5 en 8 c 2000,16000 fg -14 s 1.1 seed 809|44000|TOP ONLY · >2kHz skank+hats, bass gone"
  "m q ek 2 en 8 c 1,300 s 0.75 ss 0.9 env 20 seed 810|40000|SUB ONLY · <300Hz, sparse E(2,8), slow"
  # -- tape echo / chamber: reverse grains + long envelopes ----------------------------------
  "m q pat ..x. cyc 4 rv 0.45 env 22 s 0.8 ss 0.7 seed 811|36000|TAPE ECHO · 45% reversed grains, long taper"
  "m rw rv 0.7 env 26 ss 0.75 tl 40 seed 812|36000|SPRING CHAMBER · 70% reverse drift, bounded 40s"
  "m q ek 4 en 16 rv 0.3 env 18 nofill snap seed 813|46000|DUB SPACE · pure grid, silent rests, 30% reverse"
  "m lib con lk 6 rv 0.5 env 24 ss 0.8 seed 814|38000|REVERSE LIBRARY · contrast clusters, half reversed"
  # -- the opposite regimes, so the batch is not 20 shades of one idea -----------------------
  "m poly pr 3;2 s 1.5 ss 0.6 seed 815|30000|SLOW SAMPLE FAST GRID · poly 3-vs-2 · s1.5 ss0.6"
  "m q ek 7 en 16 snap s 1.3 ss 0.65 seed 816|32000|DENSE E(7,16) rushed grid, dragged sample"
  "m rw s 0.9 ss 1.4 tl 45 seed 817|45000|OPPOSITE · fast sample slow grid · ss1.4, bounded"
  "m lib sim lk 7 l 3 seed 818|40000|HYPNOTIC · similarity clusters k7, long grains l3"
  "m q ek 9 en 16 sw 66 fg -3 seed 819|44000|SHUFFLE 2:1 · dense, loud fill (-3dB)"
  "m poly pr 5;4 l 2 s 1.2 seed 820|36000|PHASE · 5-against-4, short grains, s1.2"
)

N=${#TREATMENTS[@]}
FIRST="${1:-1}"; LAST="${2:-$N}"
made=0; failed=0

# Walk the window start across the arrangement so mix i hears a different part of the track.
LONGEST=48000
USABLE=$(( DUR - LONGEST - 2000 )); [ $USABLE -lt 1 ] && USABLE=1

for i in $(seq "$FIRST" "$LAST"); do
  spec="${TREATMENTS[$((i-1))]}"
  margs="${spec%%|*}"; rest="${spec#*|}"; flen="${rest%%|*}"; cap="${rest##*|}"

  start=$(( (i-1) * USABLE / (N-1) ))
  end=$(( start + flen ))
  if [ $end -gt $DUR ]; then end=$DUR; start=$(( end - flen )); fi
  [ $start -lt 0 ] && start=0

  feed="$STAGE/feed_$i.wav"
  $PY -c "from pydub import AudioSegment as A; a=A.from_file('$SRC'); a[$start:$end].export('$feed',format='wav')" \
    || { echo "[obscura] mix $i feed cut FAILED" | tee -a "$LOG"; failed=$((failed+1)); continue; }

  printf '[obscura] mix %2d/%d  win=%d-%dms  amc=[%s]\n' "$i" "$N" "$start" "$end" "$margs" | tee -a "$LOG"
  pre="$(ls -t "$STAGE"/*.mp3 2>/dev/null | head -1)"
  t0=$(date +%s)
  timeout 400 $PY main.py "$feed" "$STAGE" amc $margs >>"$LOG" 2>&1
  rc=$?
  wall=$(( $(date +%s) - t0 ))
  rm -f "$feed"
  if [ $rc -ne 0 ]; then
    echo "  mix $i grind FAILED rc=$rc (${wall}s)" | tee -a "$LOG"; failed=$((failed+1)); continue
  fi

  # FRESH-OUTPUT gate: a grind that produced nothing must not ship the previous mix.
  new="$(ls -t "$STAGE"/*.mp3 2>/dev/null | head -1)"
  if [ -z "$new" ] || [ "$new" = "$pre" ]; then
    echo "  mix $i produced NO fresh output (${wall}s)" | tee -a "$LOG"; failed=$((failed+1)); continue
  fi

  outms=$($PY -c "from pydub import AudioSegment as A;print(len(A.from_mp3('$new')))" 2>/dev/null || echo 0)
  # LENGTH gate: a silently truncated render is inaudible as a fault.
  if [ "$outms" -lt $(( flen / 2 )) ]; then
    echo "  mix $i TRUNCATED: ${outms}ms < 0.5x feed ${flen}ms — not shipped" | tee -a "$LOG"
    mv "$new" "$STAGE/REJECT_$(printf %02d $i)_short.mp3"; failed=$((failed+1)); continue
  fi

  dest="$STAGE/obscura-dub_$(printf %02d $i).mp3"
  raw_db=$(ffmpeg -nostdin -v error -i "$new" -af volumedetect -f null - 2>&1 | awk -F': ' '/mean_volume/{print $2}')
  # LOUDNESS: the automixer export has no gain stage; raw grinds land ~-35dBFS.
  ffmpeg -nostdin -v error -y -i "$new" -af loudnorm=I=-16:TP=-1.5:LRA=11 -b:a 192k "$dest" \
    && rm -f "$new" || { mv "$new" "$dest"; echo "  (loudnorm failed, shipping raw)" | tee -a "$LOG"; }
  szmb=$(( $(stat -c%s "$dest") / 1048576 ))
  if [ "$szmb" -gt 45 ]; then
    ffmpeg -nostdin -v error -y -i "$dest" -b:a 128k "${dest}.re.mp3" && mv "${dest}.re.mp3" "$dest"
  fi
  new_db=$(ffmpeg -nostdin -v error -i "$dest" -af volumedetect -f null - 2>&1 | awk -F': ' '/mean_volume/{print $2}')
  echo "  -> $dest  len=${outms}ms wall=${wall}s  gain ${raw_db:-?} -> ${new_db:-?}" | tee -a "$LOG"

  bn="$(basename "$dest")"
  if mesh-room-music --deliver "$dest" "🎛 $i/$N · obscura dub · $cap" "obscura dub $i/$N" 2>&1 | sed 's/^/    /'; then
    printf '%s sent %s(obscura-grind) src=soundcloud/obscura-dub\n' \
      "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$bn" >> "$SENT_LOG"
    mv "$dest" "$OUT/$bn"
    printf '%s obscura %s | win %d-%dms | amc %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$bn" \
      "$start" "$end" "$margs" >> "$HOME/.mesh/room-music-params.log"
    made=$((made+1))
  else
    echo "  mix $i DELIVERY FAILED — left staged at $dest (not ledgered)" | tee -a "$LOG"
    failed=$((failed+1))
  fi
done

echo "[obscura] DONE: $made delivered, $failed failed, of $((LAST-FIRST+1)) attempted" | tee -a "$LOG"
