---
description: Start the NEVER-STOPPING Ralph engine on THIS repo. /ralphloop launches the background daemon (ralph start --daemon) that improves the repo FOREVER, auto-recovers from any agy stall/timeout, and opens a LIVE monitor window (status + per-iteration journal). Stop it any time with /ralphstop. It does NOT stop until you do.
---
# /ralphloop — start the never-stop engine (opens a live monitor; stop with /ralphstop)

When the user types /ralphloop they want THIS repo to start improving itself FOREVER and to NOT stop
until they stop it. A single agy chat session CANNOT do that (it stalls/ends), so DO NOT loop here —
LAUNCH THE EXTERNAL DAEMON: it runs in the BACKGROUND (that is what makes it never-stop + stall-proof)
and a LIVE monitor window shows the user what it does each iteration.

Do EXACTLY this, in order. Each command runs in the FOREGROUND and returns immediately (never background-poll):
1. ralph init "$PWD" 2>/dev/null || true        # scaffold if needed (no-op otherwise)
2. ralph start "$PWD" --daemon                  # start the never-stopping background daemon (idempotent)
3. ralph status "$PWD"                           # confirm ALIVE + show pid/iteration
4. ralph console "$PWD"                            # OPEN a live monitor WINDOW (status + per-iteration journal); returns immediately

Then tell the user EXACTLY this:
  "✅ Never-stop Ralph engine is running in the background (pid + iteration above), and a LIVE monitor
   window just opened — it shows the status AND what it did each iteration (Task/Changes/Verification/
   Decision from .ralph/PROGRESS.md), refreshing live. It keeps improving this repo FOREVER and
   auto-recovers from any agy stall/timeout.
     • If the window didn't open, run in a terminal:  ralph console \"$PWD\"
     • Raw engine log stream:                          ralph tail \"$PWD\"
     • STOP it any time:  type /ralphstop   (or run:  ralph stop \"$PWD\")"

You are DONE after that — do NOT iterate/poll/summarize here; the daemon owns the loop and survives
this chat closing. If `ralph status` shows NOT alive (sandbox blocked the launch), tell the user to run
`ralph start "$PWD" --daemon` once in a plain terminal. (`ralph` = the antigravity-ralph repo's bin/ralph.)
