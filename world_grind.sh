#!/usr/bin/env bash
# world_grind.sh — grind the world-tradition corpus, each source on a timeline from ITS OWN metric
# universe, and carry the source's LICENCE all the way into the render.
#
# Sibling of ethnic_grind.sh, and the difference is the provenance chain. ethnic_grind grinds 13
# clips pulled off YouTube that cannot name where they came from; this one reads
# downloads/world/MANIFEST.jsonl, where scripts/world_harvest.py recorded the archive.org
# identifier, the verbatim licence URL and the basis on which the item was matched to its tradition
# — and it writes a sidecar `<slug>.txt` beside every mp3 repeating all of it. A render whose source
# cannot be named is not publishable, and the sidecar is what makes the difference checkable rather
# than asserted.
#
# The grid column is the point of the pairing, same as in ethnic_grind: a bulería is ground on the
# 12-beat compás, a tango on the habanera cell, a samba on the surdo's inverted downbeat. Thirteen
# of those timelines did not exist in the library before 2026-08-30 — the engine covered Africa,
# the diaspora and Asia and nothing west of the Bosphorus, so every European clip would otherwise
# have landed on E(k,n).
#
# Two traditions carry the grid `euclid` ON PURPOSE and it is not a gap in the table: a Sámi joik is
# famously not metric, and the hula ipu patterns are not something this file can state honestly. An
# invented timeline would be worse than the euclidean default, because it would look like knowledge.
#
# Every render is verified against its source with mesh-song-verify before it counts.
#
#   usage: ./world_grind.sh [outdir] [--only <tradition>]
set -uo pipefail
cd "$(dirname "$0")"

MANIFEST=downloads/world/MANIFEST.jsonl
OUT="${1:-output/world}"
[ "${1:-}" = "--only" ] && OUT=output/world
PY=.venv/bin/python
ONLY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --only) ONLY="$2"; shift 2 ;;
    *) shift ;;
  esac
done
LOG="$OUT/grind.log"
mkdir -p "$OUT"

[ -s "$MANIFEST" ] || { echo "no corpus — run scripts/world_harvest.py first" >&2; exit 2; }

# A SUBJECT TAG SAYS WHAT AN ITEM IS ABOUT, NOT WHAT IT IS — so the harvester's subject gate admitted
# a 1916 lecture series as `balkan` and this loop would have ground it on an aksak7 grid it does not
# have. `--recheck --quarantine` MOVES such clips, but moving is not enough: the manifest row still
# names them and `[ -s "$clip" ]` finds them at their new path, so the grinder must refuse them by
# their DECLARATION. Polarity is deliberate — exclude what declares itself contaminated rather than
# admitting only what declares itself music, so a manifest predating those fields still grinds
# instead of silently going empty.
excluded=$(jq -r 'select(.quarantined or (.speech_verdict == "speech")) | .slug' "$MANIFEST" | wc -l)
total=$(wc -l < "$MANIFEST")
if [ "$excluded" -gt 0 ]; then
  echo "EXCLUDED $excluded of $total manifest row(s): quarantined or measured speech" | tee -a "$LOG"
  jq -r 'select(.quarantined or (.speech_verdict == "speech")) | "  - \(.slug)  \(.quarantined // .speech_verdict)  :: \(.title)"' "$MANIFEST" | tee -a "$LOG"
fi

PATTAB=$(python3 scripts/world_harvest.py --patterns 2>/dev/null)
[ -n "$PATTAB" ] || echo "WARN: current pairing table unreadable — falling back to the manifest's harvest-time grids" | tee -a "$LOG"

printf '=== world grind %s ===\n' "$(date -Is)" | tee -a "$LOG"
pass=0; fail=0; unver=0; skipped=0

while IFS=$'\t' read -r slug clip pattern tradition region licence kind ident basis title; do
  [ -n "${ONLY:-}" ] && [ "$tradition" != "$ONLY" ] && continue
  if [ ! -s "$clip" ]; then
    echo "SKIP $slug (clip missing: $clip)" | tee -a "$LOG"; skipped=$((skipped+1)); continue
  fi

  # The manifest records the grid AS IT WAS AT HARVEST TIME, and the pairing is code that moves:
  # 11 traditions were repointed on 2026-08-30 (fado -> habanera, samba -> surdo, hula -> euclid...)
  # while a harvest was mid-flight, so rows written before the edit name timelines the library does
  # not have. Re-read the CURRENT table and let the manifest value be the fallback, never the truth.
  cur=$(printf '%s\n' "$PATTAB" | awk -F'\t' -v t="$tradition" '$1==t{print $2; exit}')
  [ -n "$cur" ] && pattern="$cur"

  # `euclid` is the honest no-timeline case: pass no `pat` at all and let the generator default,
  # rather than naming a cycle this repo cannot defend.
  if [ "$pattern" = "euclid" ]; then
    amc="m q snap s 0.95 env 12"
  else
    amc="m q pat $pattern snap s 0.95 env 12"
  fi
  seed=$(printf '%s' "$slug" | cksum | cut -d' ' -f1)
  amc="$amc seed $((seed % 9000 + 1000))"

  # MEMORY, not length, is what bounds a grind here, and the arithmetic is measured, not guessed:
  # peak RSS is linear in feed length at ~4.12 MB per second of audio plus a ~230 MB base, and it
  # does NOT depend on the recipe (2026-08-21: the most pathological and the calmest recipe landed
  # 108 KB apart across five gigabytes). A 75-minute source therefore wants ~18.8 GB, which this
  # 31 GB node cannot give while the minds are resident. Refusing such a track LOUDLY, with the
  # number, is not the input cap this repo already deleted — that cap silently truncated every
  # source; this declines a whole one and says exactly why, and raising MESH_GRIND_MEM_MB or
  # freeing memory makes it run untouched.
  dur=$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$clip" 2>/dev/null)
  dur=${dur%.*}; dur=${dur:-0}
  need=$(( dur * 412 / 100 + 230 ))
  avail=${MESH_GRIND_MEM_MB:-$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)}
  if [ "$need" -gt "$avail" ]; then
    printf 'SKIP-MEM %-16s %-13s %ss of audio wants ~%s MB, only %s MB available\n' \
      "$slug" "$pattern" "$dur" "$need" "$avail" | tee -a "$LOG"
    skipped=$((skipped+1)); continue
  fi

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

  # The sidecar is written for EVERY render, including one the verifier later rejects — a dropped
  # mix that cannot say what it was made from is still an unattributable file on disk.
  cat > "$OUT/$slug.txt" <<SIDE
render:     $slug.mp3
tradition:  $tradition ($region)
grid:       $pattern
amc:        $amc
source:     $title
archive.org $ident — https://archive.org/details/$ident
licence:    $licence
licence is: $kind
matched by: $basis
SIDE

  verdict=$(mesh-song-verify "$clip" "$final" 2>&1 | tail -1); vrc=$?
  case $vrc in
    0) pass=$((pass+1)); tag=SONG ;;
    2) unver=$((unver+1)); tag="N/A " ;;
    *) fail=$((fail+1)); tag=DROP ;;
  esac
  printf '%-4s %-16s %-13s %4ss %7s  %s\n    %s\n' \
    "$tag" "$slug" "$pattern" "$((t1-t0))" "$(du -h "$final" | cut -f1)" "$licence" "$verdict" \
    | tee -a "$LOG"
done < <(jq -r 'select((.quarantined|not) and (.speech_verdict != "speech")) | [.slug,.clip,.pattern,.tradition,.region,(.licenceurl//"georgeblood: collection-level PD claim, no per-item licence"),.licence_kind,.identifier,.match_basis,(.title|tostring)]|@tsv' "$MANIFEST")

printf '=== %d song / %d dropped / %d unverifiable / %d skipped ===\n' \
  "$pass" "$fail" "$unver" "$skipped" | tee -a "$LOG"
