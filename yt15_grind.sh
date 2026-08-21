#!/bin/bash
# 15 varied mixes from the operator's YouTube track (ZEQCwxWWQy8 — DJ Rashad "Pass That Shit").
# Short feeds (≤~54s) dodge the O(n^2) automixer blowup that killed the whole-track run at 3min.
set -u
cd ~/grainneukeln
SRC=downloads/yt_ZEQCwx_djrashad.mp3
OUT=output/yt15
PY=.venv/bin/python
DUR=266000
mkdir -p "$OUT"
made=0
for i in $(seq 1 15); do
  start=$(( (i-1) * 15000 + 2000 ))
  len=$(( 38000 + (i % 5) * 4000 ))
  end=$(( start + len ))
  if [ $end -gt $DUR ]; then end=$DUR; start=$(( end - len )); fi
  feed="downloads/yt15_feed_$i.mp3"
  $PY -c "from pydub import AudioSegment as A; a=A.from_mp3('$SRC'); a[$start:$end].export('$feed',format='mp3')" || { echo "[yt15] feed $i cut FAILED"; continue; }
  L=$(( 300 + i*60 ))
  SS=$(awk "BEGIN{print 0.85 + 0.03*$i}")
  S=$(awk "BEGIN{print 0.90 + 0.02*($i%6)}")
  printf '[yt15] mix %2d/15 start=%dms len=%dms L=%s ss=%s s=%s\n' "$i" "$start" "$len" "$L" "$SS" "$S"
  timeout 150 $PY main.py "$feed" "$OUT" amc l "$L" ss "$SS" s "$S" >/dev/null 2>&1 || { echo "  mix $i FAILED rc=$?"; rm -f "$feed"; continue; }
  newmix=$(ls -t "$OUT"/*vtgsmlpr*.mp3 2>/dev/null | head -1)
  dest="$OUT/ztune_$(printf %02d $i).mp3"
  mv "$newmix" "$dest"
  rm -f "$feed"
  made=$((made+1))
  echo "  -> $dest ($(du -h "$dest" | cut -f1))"
done
echo "[yt15] DONE: $made/15 mixes in $OUT"
ls -la "$OUT"/ztune_*.mp3 2>/dev/null
