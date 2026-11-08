"""SAT#3: every SAT layer names its own NASA GIBS product.

Was: ``moisture`` and ``swir`` both mapped to MODIS_Terra_CorrectedReflectance_Bands721,
so one of the two labels was wrong. ``swir`` now maps to the VIIRS SNPP SWIR
composite (BandsM11-I2-I1), which GIBS lists in its WMS capabilities.
"""
from __future__ import annotations

from showme.engine.functions.misc import sat as sat_mod
from showme.manifest.seeds.sat_seed import sat


def test_each_sat_layer_maps_to_a_distinct_gibs_product() -> None:
    product_ids = [product for product, _matrix in sat_mod._GIBS_LAYERS.values()]
    assert len(product_ids) == len(set(product_ids)), product_ids


def test_swir_layer_requests_the_swir_product_not_the_moisture_composite() -> None:
    product, _matrix = sat_mod._GIBS_LAYERS["swir"]
    assert product == "VIIRS_SNPP_CorrectedReflectance_BandsM11-I2-I1"
    url = sat_mod._gibs_wms_url((-1.0, -1.0, 1.0, 1.0), product, "2026-11-01")
    assert "LAYERS=VIIRS_SNPP_CorrectedReflectance_BandsM11-I2-I1&" in url
    assert "MODIS_Terra_CorrectedReflectance_Bands721" not in url


def test_moisture_layer_keeps_the_seven_two_one_composite() -> None:
    product, _matrix = sat_mod._GIBS_LAYERS["moisture"]
    assert product == "MODIS_Terra_CorrectedReflectance_Bands721"


def test_seed_layer_description_no_longer_claims_both_are_the_same_composite() -> None:
    layer = next(spec for spec in sat.inputs if spec.name == "layer")
    assert "both MODIS Terra" not in (layer.description or "")
    assert "VIIRS" in (layer.description or "")
