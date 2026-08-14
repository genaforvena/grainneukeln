#!/bin/bash
# Retry pass for the obscura batch's FAILED deliveries.
#
# Why this exists: mesh-room-music's sendAudio is `curl --max-time 120`, and this node's uplink runs
# ~20-100 KiB/s, so a 4-8MB full-track grind can exceed the cap. curl then returns an EMPTY body and
# the caller prints `deliver: TG sendAudio FAILED:` with nothing after the colon — an honest failure,
# but one a batch will walk straight past. The set of mixes the operator actually HAS is therefore
# the batch log's `sent → operator TG` lines, never the set of files on disk.
#
# Reads the batch log, re-sends only what failed, with a timeout matched to the real uplink.
set -u
LOG=${1:-$HOME/grainneukeln/obscura_grind.log}
DIR=${OBSCURA_FINAL:-$HOME/.mesh/grinds/obscura}
ENVF="$HOME/.config/remote-access/env"
[ -f "$ENVF" ] && { set -a; . "$ENVF" 2>/dev/null; set +a; }
[ -n "${BOT_TOKEN:-}" ] && [ -n "${CHAT_ID:-}" ] || { echo "no TG creds"; exit 3; }

# A mix is OUTSTANDING when the log records a render for it but no successful send.
outstanding=""
for f in "$DIR"/obscura_*.mp3; do
  [ -f "$f" ] || continue
  bn=$(basename "$f")
  grep -qF "sent → operator TG ($f)" "$LOG" && continue
  outstanding="$outstanding $bn"
done
[ -n "$outstanding" ] || { echo "redeliver: nothing outstanding"; exit 0; }
echo "redeliver: outstanding →$outstanding"

ok=0; bad=0
for bn in $outstanding; do
  f="$DIR/$bn"
  n=$(echo "$bn" | grep -oE '[0-9]+')
  cap="🎛 obscura-dub ${n#0}/20 (full track)"
  sz=$(du -h "$f" | cut -f1)
  echo -n "  $bn ($sz) … "
  resp=$(curl -s --max-time 900 "https://api.telegram.org/bot${BOT_TOKEN}/sendAudio" \
           -F "chat_id=${CHAT_ID}" -F "audio=@${f};type=audio/mpeg" \
           -F "title=obscura ${n#0}/20" -F "caption=${cap}")
  case "$resp" in
    *'"ok":true'*) echo "sent"; ok=$((ok+1)) ;;
    "")            echo "FAILED (empty response — still hit the timeout)"; bad=$((bad+1)) ;;
    *)             echo "FAILED: $(printf '%s' "$resp" | head -c 160)"; bad=$((bad+1)) ;;
  esac
done
echo "redeliver: $ok sent, $bad still failing"
[ "$bad" = 0 ]
