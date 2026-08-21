#!/usr/bin/env bash
# END-TO-END: A HUMAN PRESSES THE RECORD BUTTON.
#
# Why this exists. On 2026-08-21 the suite was 443 green on the tip commit and the operator's first
# words about the shipped RECORD button were "как-то она кривовато работает". Both are true, and
# they are about different things: tui/test_record.py drives `panel.toggle_record()` and the panel's
# Button in-process, which proves the WIRING. Nothing in the tree ever ran the app in a terminal and
# pressed a key. So the one path the operator actually takes — keystroke -> app -> panel -> device ->
# something visible — was asserted by nothing, and a green suite said so in a voice that sounded like
# it covered the button.
#
# WHAT IS ASSERTED, and why it is not "a file appears". A take needs a free microphone, and whether
# one exists is a fact about the NODE, not about the code: on mesh-home the room ear holds the only
# working capture device with an exclusive raw-ALSA grab (arecord -D plughw:CARD=Camera,DEV=0 on
# /dev/snd/pcmC0D0c), and the second capture input measures rms 1 / peak 4 — nothing is plugged in.
# A gate demanding audio would therefore be RED for a reason that is not a defect, and would be
# quietly disabled within a week. The contract that holds everywhere is weaker and sharper:
#
#     A PRESS MUST PRODUCE A VISIBLE STATE CHANGE. Recording started, or a NAMED refusal.
#     Silence is the failure.
#
# That is exactly the complaint. A button that swallows the press is indistinguishable, to the person
# pressing it, from one that is working — which is why "кривовато" is the honest word for it and why
# no in-process test could ever have caught it.
set -uo pipefail
cd "$(dirname "$0")/.."
SESSION="gnk-rec-e2e-$$"
OUT="$(mktemp -d)"
PY="${GNK_PY:-.venv/bin/python}"
[ -x "$PY" ] || PY=python3
KEY="${GNK_REC_KEY:-C-g}"
fail(){ tmux kill-session -t "$SESSION" 2>/dev/null; rm -rf "$OUT"; echo "e2e: FAIL ($1)" >&2; exit 1; }

command -v tmux >/dev/null 2>&1 || { echo "e2e: SKIP (no tmux — nothing to drive the keystroke with)" >&2; exit 2; }

# A REAL terminal, at a real size. Textual lays out against the pane, and a pane too small to hold
# the source panel would hide the very label this test reads — a false RED that reads like a defect.
tmux new-session -d -s "$SESSION" -x 200 -y 50 \
  "$PY main.py --tui '$OUT' 2>&1 | tee '$OUT/tui.log'" || fail "tmux could not start the TUI"

# Wait for the app to PAINT, never a fixed sleep: a machine under load starts slower than the sleep
# you chose on an idle one, and the resulting flake gets 'fixed' by making the sleep longer until the
# test proves nothing but that time passes.
for _ in $(seq 1 60); do
  tmux capture-pane -t "$SESSION" -p 2>/dev/null | grep -q 'REC' && break
  sleep 0.5
done
before="$(tmux capture-pane -t "$SESSION" -p 2>/dev/null)"
printf '%s' "$before" | grep -q 'REC' || fail "the app never painted a RECORD control in 30s (pane: $(printf '%s' "$before" | tail -3 | tr '\n' '|'))"

tmux send-keys -t "$SESSION" "$KEY"

# THE ASSERTION IS ON NEW TEXT, NOT ON A DIFFERENCE. The first version of this file compared whole
# pane snapshots and grepped the result for take-related words — and PASSED when driven with an
# UNBOUND key (GNK_REC_KEY=C-y), because a live pane repaints on its own and the words it was
# grepped for were already sitting in the static chrome. A press that changed nothing scored exactly
# like a press that worked. Same shape as every vacuous gate in the mesh doctrine: the check ran, the
# check was green, and its subject was never touched. So: diff the snapshots, and require the
# EVIDENCE to appear in the lines that are NEW.
b="$(mktemp)"; a="$(mktemp)"
printf '%s\n' "$before" | sed 's/[0-9]\+\.[0-9]\+s//g' | sort -u > "$b"
newtext=""
for _ in $(seq 1 24); do
  after="$(tmux capture-pane -t "$SESSION" -p 2>/dev/null)"
  printf '%s\n' "$after" | sed 's/[0-9]\+\.[0-9]\+s//g' | sort -u > "$a"
  newtext="$(comm -13 "$b" "$a")"
  # The four outcomes start_record()/stop_record() can actually produce, spelled as the panel spells
  # them. A NAMED refusal counts: on a node whose only capture device is held (mesh-home, where the
  # room ear has an exclusive raw-ALSA grab) that IS the correct behaviour, and a gate demanding a
  # take would be red for a fact about the node rather than a defect in the button.
  printf '%s' "$newtext" | grep -qE '■ STOP|Recording via|Record failed|kept at|Still loading a source' && break
  sleep 0.5
done
if ! printf '%s' "$newtext" | grep -qE '■ STOP|Recording via|Record failed|kept at|Still loading a source'; then
  rm -f "$b" "$a"
  fail "the press produced no NEW take-related text in 12s — it was swallowed; a silent no-op is what the operator called 'кривовато' (new lines were: $(printf '%s' "$newtext" | tr '\n' '|' | cut -c1-200))"
fi

# Second press: the control must come BACK to REC — and it only means anything if it LEFT. Where the
# take was refused outright the button never changed, so there is nothing to assert and the check is
# skipped OUT LOUD; an unstated skip reads exactly like a passing assertion.
if printf '%s' "$newtext" | grep -q '■ STOP'; then
  tmux send-keys -t "$SESSION" "$KEY"
  back=0
  for _ in $(seq 1 24); do
    now="$(tmux capture-pane -t "$SESSION" -p 2>/dev/null)"
    printf '%s' "$now" | grep -q '● REC' && { back=1; break; }
    sleep 0.5
  done
  [ "$back" = 1 ] || { rm -f "$b" "$a"; fail "the button went to ■ STOP and never came back to ● REC — it starts and cannot stop"; }
  stopnote="stop edge asserted"
else
  echo "  (stop edge) skipped out loud: the take was refused before it started, so the button never left ● REC — nothing to stop" >&2
  stopnote="stop edge n/a (take refused up front)"
fi

verdict="$(printf '%s' "$newtext" | grep -oE '■ STOP|Recording via [^ ]+|Record failed[^"]*|kept at [^ ]+' | head -1)"
rm -f "$b" "$a"
tmux kill-session -t "$SESSION" 2>/dev/null
rm -rf "$OUT"
echo "e2e: ok (ctrl+g produced NEW take-related text: ${verdict:-?}; $stopnote)"
