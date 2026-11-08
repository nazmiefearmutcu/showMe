"""VCAP#1: a requested geography with zero saved periods must be warned, not silent."""
from __future__ import annotations

import asyncio

import pytest

from showme.engine.services.vcap.models import Query, validate_dataset
from showme.engine.services.vcap.service import VCAPService


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("SHOWME_VCAP_DIR", str(tmp_path))
    monkeypatch.delenv("SHOWME_DEFILLAMA_API_KEY", raising=False)
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path / "app"))


def _dataset():
    return {
        "schema_version": 1, "source_id": "custom_test", "source_name": "Test publication",
        "source_url": "https://example.org/research", "published_at": "2025-06-01",
        "methodology": "Company investment reported by the publisher.",
        "methodology_version": "v1", "geography_basis": "company_hq",
        "date_basis": "announced", "sector": "all", "observations": [{
            "scope": "countries", "geography": "USA", "period": "2024",
            "metric": "investment", "stage": "total", "unit": "USD",
            "value": 100, "status": "reported",
        }],
    }


def test_zero_period_requested_geography_is_warned_not_silent():
    service = VCAPService()
    service.store.save(validate_dataset(_dataset()))  # custom_test: USA only
    data, _ = asyncio.run(service.query(Query.parse({
        "source_ids": ["custom_test"], "geographies": ["USA", "TUR"],
    })))
    assert data["status"] == "ok"
    assert {r["geography"] for r in data["rows"]} == {"USA"}
    tur = next(s for s in data["coverage"]["series"] if s["geography"] == "TUR")
    assert tur["periods"] == [] and tur["first_period"] is None
    assert any("TUR" in w and "custom_test" in w for w in data["warnings"]), data["warnings"]
    assert not any("USA" in w for w in data["warnings"])
