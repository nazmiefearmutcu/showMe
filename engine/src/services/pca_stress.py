"""PCA-based factor stress test.

Decompose returns into orthogonal principal components and apply k-σ shocks
along chosen factors (e.g. PC1 = market β, PC2 = sector tilt, ...). Each
asset's response is its loading × shock magnitude; correlations are
preserved without ad-hoc correlation matrices.

Key outputs:
- explained_variance_ratio per PC
- top loadings per PC (top symbols + sign)
- per-asset shocked return for given (k, factor) shock
"""

from __future__ import annotations

import numpy as np


def pca_decompose(rets: np.ndarray) -> dict:
    """SVD-based PCA. ``rets`` is (T × N), zero-mean recommended."""
    if rets.ndim != 2 or rets.shape[0] < 2:
        raise ValueError("returns matrix must be 2D with ≥ 2 rows")
    R = rets - rets.mean(axis=0)
    # Singular value decomposition
    U, S, Vt = np.linalg.svd(R, full_matrices=False)
    # Eigenvalues = S² / (T−1)
    n_obs = R.shape[0]
    var = (S ** 2) / max(n_obs - 1, 1)
    total = var.sum() if var.sum() else 1.0
    return {
        "loadings": Vt,            # (k × N) — rows are PCs, cols are assets
        "explained_variance": var,
        "explained_variance_ratio": (var / total).tolist(),
        "singular_values": S.tolist(),
        "components_t": U @ np.diag(S),    # (T × k) factor scores
    }


def factor_shock(
    rets: np.ndarray, *,
    pc_index: int = 0, k_sigma: float = 3.0,
) -> dict:
    """Apply a +k_sigma shock along PC[pc_index]. Returns per-asset return."""
    pca = pca_decompose(rets)
    loadings = pca["loadings"]
    if pc_index >= loadings.shape[0]:
        raise ValueError(f"pc_index {pc_index} out of range")
    sigma = float(np.sqrt(pca["explained_variance"][pc_index]))
    shock_magnitude = k_sigma * sigma
    # Return per asset = loading × shock
    asset_returns = loadings[pc_index] * shock_magnitude
    return {
        "pc_index": pc_index,
        "k_sigma": k_sigma,
        "shock_magnitude": shock_magnitude,
        "factor_explained_variance_ratio": pca["explained_variance_ratio"][pc_index],
        "asset_returns": asset_returns.tolist(),
    }


def apply_to_portfolio(
    weights: np.ndarray, rets: np.ndarray, *,
    pc_index: int = 0, k_sigma: float = 3.0,
) -> dict:
    """Portfolio-level stress under PC shock."""
    sh = factor_shock(rets, pc_index=pc_index, k_sigma=k_sigma)
    asset_rets = np.asarray(sh["asset_returns"])
    portfolio_return = float(weights @ asset_rets)
    return {
        **sh,
        "portfolio_return": portfolio_return,
        "weights": weights.tolist() if hasattr(weights, "tolist") else list(weights),
    }


def top_loadings(loadings: np.ndarray, symbols: list[str], pc_index: int = 0,
                 top_n: int = 10) -> list[dict]:
    if pc_index >= loadings.shape[0]:
        return []
    row = loadings[pc_index]
    pairs = sorted(zip(symbols, row), key=lambda p: -abs(p[1]))[:top_n]
    return [{"symbol": s, "loading": float(v)} for s, v in pairs]
