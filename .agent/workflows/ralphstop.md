---
description: Stop the never-stop Ralph engine on THIS repo. /ralphstop drains the background daemon (ralph stop) — the loop halts within ~20s and stays down until you run /ralphloop again.
---
# /ralphstop — stop the never-stop engine

The user wants to STOP the never-stop Ralph daemon on THIS repo. Do EXACTLY this:
1. ralph stop "$PWD"            # sets the STOP sentinel + SIGTERMs the supervisor → drains within ~20s
2. ralph status "$PWD"           # confirm it is now stopped/dead (status: stopped)

Then tell the user: "🛑 Ralph engine stopped — the loop has drained and will not resume until you run
/ralphloop again." If they want it to STAY down even across a reboot, run: ralph stop "$PWD" --permanent.
You are DONE after that. Do not iterate or summarize repeatedly.
Hard limits: no financial actions; no broad `rm -rf`; no force-push to main; no DB drop; no push to a
remote the user doesn't own.
