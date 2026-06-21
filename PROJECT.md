# Project: showMe Bot System Audit Remediation

## Architecture
The showMe bot system consists of:
- **Backend (Python)**:
  - API Routes: `backend/showme/server_routes/` for bots, strategies, exchange credentials.
  - Bot Runtime/Engine: `backend/showme/bots/` (runner, record, performance, store).
  - Compute & Evaluation: `backend/showme/strategies/` (compute, evaluate, spec).
  - Brokers Integration: `backend/showme/brokers/` (factory, ccxt_broker, base, credential_store).
- **UI (React/TypeScript)**:
  - Function Panes: `ui/src/functions/` (BOT.tsx, BOTS.tsx, STRA.tsx, CONN.tsx).

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | Backend Strategy & Sizing | Fix sizing validations, BB template params name alignment, and PnL performance calculations (C-API-1, C-API-2, H-SUP-3). Add unit tests. | None | DONE |
| 2 | Backend Bot Runtime & Locks | Fix tick frequency alignment, state-aware evaluation, broker connection pool & cleanup, and disable lock sequence (C-RUNTIME-1, C-RUNTIME-2, C-RUNTIME-3, H-RT-2). Add unit/integration tests. | M1 | DONE |
| 3 | Integration & Cascade Delete | Secure bots route from payload injection and implement cascade deletion for credentials and strategies halting bots (C-INT-1, C-INT-2, C-API-3). Add unit/integration tests. | M2 | DONE |
| 4 | UI Cascade & Dropdowns | Prevent UI dropdown selection breakage on referenced record deletion and fix timeframe selection mismatch in UI dropdowns (C-UI-1, H-UI-3). | M3 | DONE |

## Interface Contracts
### strategies/spec.py & strategies/compute.py & catalog/templates.yml
- Bollinger Bands parameter name must be aligned: standard deviation must be represented consistently (e.g. template uses `std_dev` or `num_std`, must match what compute expects).
- Strategy creation/update validation rules on `sizing_value` (> 0) and `risk_pct` (<= 100%).

### Exchange Credentials / Strategy Cascade Deletions ↔ Bot Runner
- Deleting a credential or strategy must trigger a cascade delete hook that stops and disables active dependent running bots, cancels their tasks/listeners, and updates their status to stopped/error.

## Code Layout
- `backend/showme/server_routes/`: FastAPI routes.
- `backend/showme/bots/`: Bot life cycle and executor runtime.
- `backend/showme/strategies/`: Strategy spec, evaluation, and compute logic.
- `backend/showme/brokers/`: CCXT and paper broker interfaces.
- `ui/src/functions/`: React panels and views.
