---
description: Dictate a LIVE directive to the running Ralph loop on THIS repo WITHOUT stopping it. /ralphsay <message> queues it via `ralph say`; the loop picks it up next iteration as an operator directive (e.g. "focus on api.py", "stop adding tests, fix lint", "prioritize security").
---
# /ralphsay — dictate to the running loop (side-channel; never stops it)

The user wants to send a LIVE directive to the background Ralph loop on this repo WITHOUT stopping it.
Take EVERYTHING the user wrote after /ralphsay as the message and run (foreground, returns at once):
    ralph say "$PWD" "<the user's message verbatim>"
Then tell the user it is queued and the loop will act on it on its NEXT iteration (it keeps running the
whole time — this is a side-channel into .ralph/INBOX.md). If the user gave no message, ask what to
dictate (e.g. "focus on api.py next", "stop adding tests, fix the lint errors", "prioritize security").
Do NOT stop or restart the loop. You are done after confirming.
