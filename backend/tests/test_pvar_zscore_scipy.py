"""Audit Q3 #11 — PVAR z-score must come from inverse-normal CDF.

The legacy hardcode `{0.95: 1.645, 0.99: 2.326, else: 1.96}` returned
1.96 for any other confidence, including 0.90 (correct one-sided z =
1.2816). Pin the Acklam-rational approximation against textbook values.
"""
from __future__ import annotations

import math

from showme.engine.functions.portfolio.pvar import _norm_ppf


def test_norm_ppf_one_sided_95_pct():
    z = _norm_ppf(0.95)
    assert abs(z - 1.6449) < 1e-3


def test_norm_ppf_one_sided_99_pct():
    z = _norm_ppf(0.99)
    assert abs(z - 2.3264) < 1e-3


def test_norm_ppf_one_sided_90_pct():
    """The legacy code returned 1.96 here; correct value is 1.2816."""
    z = _norm_ppf(0.90)
    assert abs(z - 1.2816) < 1e-3


def test_norm_ppf_one_sided_975_pct():
    """The two-sided 95% / one-sided 97.5% case is the classical 1.96."""
    z = _norm_ppf(0.975)
    assert abs(z - 1.9600) < 1e-3


def test_norm_ppf_symmetry():
    """Φ⁻¹(p) = −Φ⁻¹(1−p)."""
    for p in (0.05, 0.1, 0.25, 0.4, 0.45):
        assert abs(_norm_ppf(p) + _norm_ppf(1 - p)) < 1e-9


def test_norm_ppf_tail_extremes_return_finite_signs():
    assert _norm_ppf(0.0001) < -3.5
    assert _norm_ppf(0.9999) > 3.5
    assert math.isinf(_norm_ppf(0.0)) and _norm_ppf(0.0) < 0
    assert math.isinf(_norm_ppf(1.0)) and _norm_ppf(1.0) > 0
