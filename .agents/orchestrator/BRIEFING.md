# BRIEFING — 2026-06-07T12:48:50+03:00

## Mission
Orchestrate translation, registration, integration, and verification of language catalogs in the showMe app.

## 🔒 My Identity
- Archetype: orchestrator
- Roles: orchestrator, user_liaison, human_reporter, successor
- Working directory: /Users/nazmi/showMe_temp/.agents/orchestrator/
- Original parent: main agent
- Original parent conversation ID: 328adba8-c732-4e7d-9bb1-ede8b636dbdf

## 🔒 My Workflow
- **Pattern**: Project
- **Scope document**: /Users/nazmi/showMe_temp/PROJECT.md
1. **Decompose**: Assess codebase structure and break task into translation, backend, test suite, and verification.
2. **Dispatch & Execute**:
   - **Direct (iteration loop)**: Spawn Explorer -> Worker -> Reviewer -> Challenger -> Forensic Auditor per milestone.
3. **On failure** (in this order):
   - Retry: nudge stuck agent or re-send task
   - Replace: spawn fresh agent with partial progress
   - Skip: proceed without (only if non-critical)
   - Redistribute: split stuck agent's remaining work
   - Redesign: re-partition decomposition
   - Escalate: report to parent (sub-orchestrators only, last resort)
4. **Succession**: Self-succeed at 16 spawns.
- **Work items**:
  1. Explore current en.json and ui/src/i18n structure [done]
  2. Implement/translate 11 missing/incomplete catalogs [in-progress]
  3. Register catalogs and modify t() function to remove English fallback [pending]
  4. Verify changes with unit and integration tests [pending]
- **Current phase**: 2
- **Current focus**: Translate and populate all catalog files (R1)

## 🔒 Key Constraints
- Follow requirements R1-R4 exactly.
- Never write, modify, or create source code files directly.
- NEVER run build/test commands yourself — require workers to do so.
- Never reuse a subagent after it has delivered its handoff — always spawn fresh.

## Current Parent
- Conversation ID: 328adba8-c732-4e7d-9bb1-ede8b636dbdf
- Updated: not yet

## Key Decisions Made
- Initial plan: Initializing metadata and preparing Explorer subagent.
- Milestone 1: Exploration completed. Confirmed en.json has 137 keys, tr.json matches exactly. Other 10 locales are missing.

## Team Roster
| Agent | Type | Work Item | Status | Conv ID |
|-------|------|-----------|--------|---------|
| Explorer_1 | explorer | Explore codebase | completed | d340a48b-481f-405c-bbc7-10d75610b30d |
| Explorer_2 | explorer | Explore codebase | completed | 2ec6dfdc-1f84-4328-a09e-66b0f0f1159f |
| Explorer_3 | explorer | Explore codebase | completed | 2a2e5a78-3f97-4d43-9bb6-0c55365ec362 |
| Worker_1 | worker | Translate catalogs | in-progress | c80f9b51-001c-42de-bed3-90c7c38dbdd8 |

## Succession Status
- Succession required: no
- Spawn count: 7 / 16
- Pending subagents: c80f9b51-001c-42de-bed3-90c7c38dbdd8
- Predecessor: none
- Successor: not yet spawned

## Active Timers
- Heartbeat cron: task-79
- Safety timer: task-140
- On succession: kill all timers before spawning successor
- On context truncation: run `manage_task(Action="list")` — re-create if missing

## Artifact Index
- /Users/nazmi/showMe_temp/.agents/orchestrator/plan.md — Project plan
- /Users/nazmi/showMe_temp/.agents/orchestrator/progress.md — Actionable progress log
- /Users/nazmi/showMe_temp/.agents/orchestrator/context.md — Context details
