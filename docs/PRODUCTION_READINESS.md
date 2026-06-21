# showMe Production Readiness & Release Governance

## 1. Release Security & Signing Pipeline
For a secure macOS desktop deployment (Tauri + Python PyInstaller bundle):
- **Apple Notarization & Codesigning**: Every release artifact (DMG, App bundle) is signed with a Developer ID Certificate and submitted to the Apple Notarization Service (`xcrun notarytool`).
- **Tauri Updater Signature**: Updater manifests are cryptographically signed using Tauri's private key (`TAURI_SIGNING_PRIVATE_KEY`). The desktop client verifies the signature before applying updates.
- **Rollback and Key Rotation**: A fail-safe rollback endpoint is hosted on GitHub Releases. API keys and signing keys are rotated quarterly using GitHub Actions secrets environment.

## 2. Secrets Management & Keychain Integration
To secure broker tokens and credentials:
- **macOS Keychain**: In production mode, credentials (Alpaca keys, Binance secrets) are written directly to the macOS Keychain service rather than plain text files.
- **Redacted Logging**: All logs redact standard key prefixes (e.g. `sk_`, `AKIA`) and credential values automatically in `logging_setup.py`.
- **Frontend Isolation**: Frontend code never accesses credentials directly; all API calls requiring auth are routed through the Python localhost sidecar.

## 3. Trading Sizing & RiskPolicy Engine
A dedicated Risk Policy layer wraps the execution engine (`sizing.py` and `exec.py`):
- **Exposure Limits**: Maximum daily loss, maximum total exposure, and symbol-level exposure limits are validated before submitting any order.
- **Duplicate Order Guard**: A deduplication lock blocks orders with the same symbol, quantity, and side submitted within 5 seconds.
- **Broker Reconciliation**: Orders are reconciled against the broker's portfolio state post-fill to verify lot allocation accuracy.

## 4. AI/ML Sentiment Lifecycle (FinBERT & showme_x_v1)
- **Model Storage**: Models are lazy-loaded from HuggingFace (`ProsusAI/finbert`) or bundled locally under `data/x_model/showme_x_v1` (RoBERTa-base with three classification heads).
- **RAM & Hardware Acceleration**: Runs on CPU or uses Apple Silicon MPS (Metal Performance Shaders) when available for batch sentiment inference under 1.5 seconds.
