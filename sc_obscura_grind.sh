#!/bin/bash
# 20 diverse grinds from SoundCloud salamaaashop/obscura-dub (operator ask 2026-08-14 22:26,
# re-asked 22:43). Source fetched through grainneukeln's OWN downloader (yt_dlp handles the
# soundcloud extractor) — see youtube/downloader.py.
#
# FULL-TRACK, not windowed (operator correction 2026-08-14 23:00: "grinds you are sending me are
# abridged version from original audio, make grinds out of full track"). The first pass cut a
# 34-55s feed window per mix because `mesh-room-music --remix` fails silently above ~65s. That
# ceiling belongs to the room-music path, NOT to a direct `main.py` grind: measured here, the full
# 332s source grinds in 30s (q) / 15s (rw) and renders 221-282s of audio. So every treatment below
# takes the WHOLE track as its source.
#
# Axis spread (combo-repel — no two treatments repeat a vector):
#   mode      q (euclid/named pattern) · poly · lib sim|con · rw
#   pattern   ek/en euclid AND the named tala/clave/bell cells (pat/cyc/rot/acc)
#   tempo     s (grid speed) x ss (sample speed) — incl. the operator's slow-sample-fast-grid pairing
#   grain     l (length) · env (taper) · rv (reverse prob)
#   placement snap · sw (swing) · fg/nofill (rest fill) · c (band split)
#
# CONSTRAINTS carried from prior batches (do not "simplify" these away):
#   - rw render length is quadratic-ish in beat count, not source length -> every rw treatment
#     carries `tl src` to bound the render at the source length
#     (memory: rw-length-is-quadratic-in-source-duration)
#   - `l` only accepts int / *N / /N forms; `l 0.5` is silently IGNORED
#   - `c` bands are `low,high;low,high` (COMMAS); `pr` streams are `ratio:low-high` (DASHES)
set -u
cd ~/grainneukeln
SRC=downloads/sc_obscura_src.mp3
# Renders stage and land OUTSIDE ~/grainneukeln/output — `mesh-grind-deliver` sweeps that whole tree
# recursively every 3 minutes (`# reflex-cadence: */3 * * * *`, OUTDIR=$HOME/grainneukeln/output)
# and ships any *.mp3 whose BASENAME is not already in ~/.mesh/room-music-sent.log. Rendering there
# means each mix goes out TWICE (the sweep + this script's explicit --deliver), and worse, the sweep
# can catch the raw render in the window between the mixer writing it and this script's loudnorm —
# shipping the operator a ~-35 dBFS file. Same trap the gong lane hit (4a07477).
OUT=${OBSCURA_STAGE:-$HOME/.mesh/grinds/obscura/_stage}
FINAL=${OBSCURA_FINAL:-$HOME/.mesh/grinds/obscura}
PY=.venv/bin/python
DELIVER=${DELIVER:-1}
START=${START:-1}          # resume a partial batch: START=4 skips mixes already shipped
mkdir -p "$OUT" "$FINAL"
[ -f "$SRC" ] || { echo "[obscura] SRC missing: $SRC"; exit 1; }
DUR=$($PY -c "from pydub import AudioSegment as A;print(len(A.from_mp3('$SRC')))" 2>/dev/null || echo 0)
[ "$DUR" -gt 60000 ] || { echo "[obscura] SRC too short/unreadable (DUR=$DUR)"; exit 1; }
echo "[obscura] FULL-TRACK source DUR=${DUR}ms ($(awk "BEGIN{printf \"%.0f\", $DUR/1000}")s)"

# "mode_args | caption"
TREATMENTS=(
  "m q ek 3 en 8 s 1.5 ss 0.7|slow-sample fast-grid · E(3,8) tresillo · s1.5 ss0.7"
  "m q pat clave32 s 1.35 ss 0.72 snap|son clave 3-2 + snap · s1.35 ss0.72"
  "m rw ss 0.55 env 22 tl src|rw · half-speed sample, long taper — dub smear"
  "m poly pr 3;2 s 1.6 ss 0.6|poly 3-vs-2 · slow-sample fast-grid s1.6 ss0.6"
  "m lib con lk 6 s 1.4 ss 0.75 l 2|lib contrast k6 · s1.4 ss0.75 l2"
  "m q pat bembe s 1.2 fg -4|bembe 7-stroke bell 12/8 · loud fill -4dB"
  "m rw sw 66 s 1.4 ss 0.65 rv 0.35 tl src|rw · 2:1 shuffle · 35% grains reversed"
  "m q pat teental l 3 ss 0.8|tintal 16-matra theka · long grains l3, slow sample"
  "m poly pr 5;4 s 1.8 ss 0.6 l 2|poly 5-vs-4 extreme · s1.8 ss0.6 short grains"
  "m q ek 7 en 16 snap nofill|E(7,16) dense · PURE GRID, silent rests (nofill)"
  "m lib sim lk 7 env 30|lib similarity k7 · 30% taper — hypnotic in-cluster"
  "m q pat aksak9 s 1.15|9/8 aksak (2+2+2+3) limping meter · s1.15"
  "m rw s 0.8 ss 1.35 tl src|OPPOSITE pairing · fast-sample slow-grid s0.8 ss1.35"
  "m q pat gnawa cyc 4 s 1.3 ss 0.7|qraqeb 12/8 accent stream · s1.3 ss0.7"
  "m poly pr 3:1-1200;2:5000-16000|poly 3-vs-2 SPLIT · low band vs high band"
  "m q pat maqsum snap sw 60 fg -12|maqsum DUM/tak · snap+swing60 · quiet fill -12dB"
  "m lib con lk 4 rv 0.5 l 2|lib contrast k4 · HALF the grains reversed · l2"
  "m q pat jhaptal rot 3 ss 0.6|jhaptal 10-matra ROTATED by 3 · slow sample ss0.6"
  "m rw c 1,900;2500,12000 env 15 tl src|rw two-band split (sub-bass vs air) · taper 15"
  "m q pat colotomic s 1.45 ss 0.68 snap|Javanese colotomic gong punctuation · s1.45 ss0.68"
)

N=${#TREATMENTS[@]}
made=0
for i in $(seq "$START" $N); do
  spec="${TREATMENTS[$((i-1))]}"
  margs="${spec%%|*}"; cap="${spec#*|}"
  printf '[obscura] mix %2d/%d  FULL TRACK  mode=[%s]\n' "$i" "$N" "$margs"
  timeout 900 $PY main.py "$SRC" "$OUT" amc $margs >"$OUT/grind_$i.log" 2>&1
  rc=$?
  if [ $rc -ne 0 ]; then
    echo "  mix $i grind FAILED rc=$rc — $(tail -2 "$OUT/grind_$i.log" | tr '\n' ' ' | tail -c 200)"
    continue
  fi
  # The mixer names its render from the PARAMS (l465_w2_ss0.7_…mp3) — the older batch scripts
  # globbed `*vtgsmlpr*`, which matches NOTHING the current mixer writes, so every mix would have
  # read as "produced NO output" while a real render sat on disk. The staging dir holds only the
  # mixer's own renders (finals land in $FINAL), so the newest mp3 here IS this mix.
  newmix=$(ls -t "$OUT"/*.mp3 2>/dev/null | head -1)
  [ -n "$newmix" ] || { echo "  mix $i produced NO output"; continue; }
  dest="$FINAL/obscura_$(printf %02d $i).mp3"
  mv "$newmix" "$dest"
  # bloom guard: a render longer than ~1.5x the source means a mode overshot its bound
  rawms=$($PY -c "from pydub import AudioSegment as A;print(len(A.from_mp3('$dest')))" 2>/dev/null || echo 0)
  cap_ms=$(( DUR * 3 / 2 ))
  if [ "$rawms" -gt "$cap_ms" ]; then
    ffmpeg -v quiet -y -i "$dest" -t "$(awk "BEGIN{print $DUR/1000}")" -c copy "${dest}.tr.mp3" \
      && mv "${dest}.tr.mp3" "$dest"
    echo "  BLOOM: trimmed ${rawms}ms -> ${DUR}ms (mode overshot the source length)"
  fi
  # raw grinds come out QUIET (-32..-36dB) — the export loudnorm is not deployed on this node
  ffmpeg -nostdin -v quiet -y -i "$dest" -af loudnorm=I=-16:TP=-1.5:LRA=11 -b:a 192k "${dest}.ln.mp3" \
    && mv "${dest}.ln.mp3" "$dest"
  outms=$($PY -c "from pydub import AudioSegment as A;print(len(A.from_mp3('$dest')))" 2>/dev/null || echo 0)
  made=$((made+1))
  echo "  -> $dest ($(du -h "$dest" | cut -f1), len=$(awk "BEGIN{printf \"%.0f\", $outms/1000}")s of ${DUR}ms source)"
  if [ "$DELIVER" = 1 ]; then
    mesh-room-music --deliver "$dest" "🎛 obscura-dub $i/$N (full track) — $cap" "obscura $i/$N" 2>&1 | sed 's/^/    /'
  fi
done
echo "[obscura] DONE: $made mixes ground this run (of $N treatments, started at $START) → $FINAL"
