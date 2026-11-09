# D phase — parallel P0 repair plan

Prepared 2026-11-08 on `fix/foundation-audit` (base for every worker: `5ab5c65`).
Source of truth for each finding (evidence, file:line, proposed fix, verifier
notes): `docs/audit/function-ledger.json`, by finding id.

Scope: the 31 confirmed P0 findings that remain after excluding the functions
owned by the Awareness session (TOP, NI, CN, NALRT, NSE, SOSC, EVTS, ECO, MEET,
DVD, CACT, TRDH — TOP#1 and NSE#1 were handed to that session) and PSC#1
(fixed in `9a4a27f`).

## Worker groups (no two groups edit the same file)

| Group | Findings | Files the group owns |
|---|---|---|
| G1 bond-api | CRPR#1, CRPR#2, TAUC#1, ISIN#1 | `engine/functions/bond/_stubs.py`, `manifest/seeds/crpr_seed.py`, `ui/src/functions/CRPR.tsx`, `engine/data_sources/bond/treasury_auctions_adapter.py`, `ui/src/functions/TAUC.tsx`, `engine/data_sources/reference/openfigi_adapter.py` + the ISIN handler |
| G2 commodity | CPF#1, WETR#1 | `engine/functions/commodity/_funcs.py`, `manifest/seeds/cpf_seed.py`, WETR seed, `ui/src/functions/WETR.tsx` |
| G3 equity-finra-fa | DARK#1, DPF#1, FA#3 | `engine/functions/equity/dark.py`, `equity/dpf.py`, `engine/data_sources/equity/finra_adapter.py`, DARK/DPF panes, `equity/fa.py`, `engine/data_sources/equity/sec_edgar_adapter.py` |
| G4 equity-sec-dcf | FTS#1, FTS#2, LITM#1, DCF#1 | `engine/data_sources/equity/sec_efts_adapter.py`, `equity/fts.py`, `ui/src/functions/FTS.tsx`, `engine/functions/misc/_bonus.py` (LITM only — `cact.py` is Awareness-owned), `ui/src/functions/DCF.tsx`, `equity/dcf.py` |
| G5 macro | COUN#1, ECFC#1, ECST#1 | `engine/functions/macro/coun.py`, `macro/ecfc.py`, `macro/ecst.py`, `ui/src/functions/ECFC.tsx`, `ui/src/functions/ECST.tsx` |
| G6 fx-screen | OVDV#1, MOST#2 | `engine/functions/fx/_funcs.py`, `ui/src/functions/OVDV.tsx`, `engine/functions/screen/_funcs.py` |
| G7 news-router | TLDR#1, TLDR#3, SAT#1, SAT#2 | `engine/functions/news/tldr.py`, `engine/functions/misc/sat.py`, `server_routes/_agent_runtime.py` (sole owner) |
| G8 portfolio-A | PORT_WHATIF#1, TRA#1, LOTS#1 | `engine/functions/portfolio/_more.py`, `ui/src/functions/PortfolioAnalytics.tsx`, `engine/data_sources/equity/yfinance_adapter.py` (sole owner), `portfolio/lots.py` |
| G9 portfolio-B | ACCT#1, BMTX#3, CORR#1 | `engine/functions/portfolio/acct.py`, `portfolio/bmtx.py`, `portfolio/corr.py`, `ui/src/functions/CORR.tsx` |
| G10 trade | FXGO#3, TCA#1, TSOX#1 | `engine/functions/trade/_funcs.py`, `trade/tca.py`, `backend/showme/server.py` (sole owner), `manifest/seeds/tsox_seed.py`, `ui/src/functions/TSOX.tsx` |

Paths without a prefix are under `backend/showme/`. Nobody edits
`contracts/pane_params.json` or `tests/_truth_baseline.json` (regenerated once
after the merge), `server_routes/function_index.py`, `ui/src/functions/registry.tsx`,
`ui/src/lib/sentiment-store.ts`, or any Awareness-owned module (`eco.py`,
`top.py`, `cact.py`, ...). LOTS#1 is fixed inside `lots.py` (G10 owns
`server.py`); TLDR#3 reads ECO/TOP results without editing them.

## Per-group procedure

1. Implementer (Haiku, own git worktree): for each finding, write a failing
   test that reproduces it (no network: patch the adapter), record the red
   output, fix, see it pass; run the related existing tests and the offline
   truth gate (no count may rise); commit per finding as `fix(CODE): ...`.
2. Reviewer (Haiku, read-only, adversarial): diff vs `5ab5c65`, check each
   finding is really fixed, no invented or placeholder data, honest
   provenance and explicit empty/error states, meaningful tests, no edits
   outside the group's files.
3. Fixer (Haiku) for review problems, one round; escalation to the session
   model if problems remain.
4. Orchestrator: cherry-pick every group onto `fix/foundation-audit`,
   regenerate `contracts/pane_params.json`, lower the truth baseline
   (`SHOWME_UPDATE_TRUTH_BASELINE=1`), run backend/UI/typecheck/lint/e2e,
   strict live re-audit of the fixed codes (`--only`), rebuild the ledger.

Worktrees: the orchestrator creates them itself, one per group, with
`git worktree add -b d/<group> .claude/worktrees/d-<group> 5ab5c65`.
The agent tool's own `isolation: worktree` bases new worktrees on `main`
(`3cbbb71`, probed 2026-11-08), which lacks the whole audit branch, so it must
not be used. Inside `.claude/worktrees/` Node resolves `typescript` and
`vitest` from the main checkout's `node_modules` (all UI deps are hoisted to
the root), so UI tests run from `<worktree>/ui` with
`node <main>/node_modules/vitest/vitest.mjs run <test file>`.

Test commands inside a worktree (never `uv run`/`uv sync`, never port 8765):

```
cd <worktree>/backend && PYTHONPATH=<worktree>/backend <main>/backend/.venv/Scripts/python.exe -m pytest tests/<file> -q -p no:cacheprovider
```

Check first that `python -c "import showme; print(showme.__file__)"` prints a
path inside the worktree (the venv's editable install points at the main
checkout).
