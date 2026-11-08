"""SAT — Satellite imagery (commodity intel), keyless.

Serves NASA GIBS (Global Imagery Browse Services) daily MODIS tiles for a
curated area of interest, plus Open-Meteo conditions for the AOI centroid.
Both sources are public and need no API key. Matches the handler in
engine/functions/misc/sat.py.

When a source is unreachable the handler says so explicitly
(data_mode='not_configured', status='provider_unavailable') and returns no
rows. It never draws a synthetic tile or a placeholder cloud value.
"""
from __future__ import annotations

from ..enums import (
    AssetClass,
    Category,
    ControlKind,
    DataMode,
)
from ..registry import manifest
from ..spec import (
    CachingPolicy,
    CardSchema,
    CardSlot,
    ColumnSpec,
    FieldDef,
    FunctionManifest,
    InputSpec,
    OutputContract,
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
    TableSchema,
)


@manifest()
def sat() -> FunctionManifest:
    return FunctionManifest(
        code="SAT",
        name="Satellite Imagery",
        category=Category.MISC,
        intent=(
            "Keyless NASA GIBS satellite tile for a curated commodity area of interest "
            "(oil storage, port congestion, crop belts) on a chosen capture day, with "
            "Open-Meteo cloud cover and conditions for the AOI centroid."
        ),
        asset_classes=[AssetClass.COMMODITY],
        inputs=[
            InputSpec(
                name="aoi",
                label="Area of Interest",
                control=ControlKind.SELECT,
                required=True,
                description="Curated AOI preset (Cushing tank farm, Singapore Strait, etc.).",
                options=[
                    "cushing_ok",
                    "singapore_strait",
                    "shanghai_port",
                    "rotterdam_port",
                    "saudi_ras_tanura",
                    "iowa_corn_belt",
                ],
            ),
            InputSpec(
                name="layer",
                label="Layer",
                control=ControlKind.SELECT,
                required=True,
                description=(
                    "NASA GIBS visualisation layer: true_color (MODIS Terra corrected reflectance), "
                    "ndvi (MODIS 8-day NDVI composite), moisture (MODIS Terra bands 7-2-1 composite), "
                    "thermal (MODIS land surface temperature, day), swir (VIIRS SNPP SWIR-NIR-red composite)."
                ),
                options=["true_color", "ndvi", "moisture", "thermal", "swir"],
            ),
            InputSpec(
                name="capture_date",
                label="Capture date",
                control=ControlKind.DATE_RANGE,
                required=False,
                description=(
                    "GIBS daily mosaic day (YYYY-MM-DD). Accepts a single day or 'from,to'; "
                    "the end of the window is used as the capture day. Defaults to today (UTC)."
                ),
            ),
        ],
        defaults={
            "aoi": "cushing_ok",
            "layer": "true_color",
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=[],
            acceptable_modes=[
                DataMode.DELAYED_REFERENCE,
                DataMode.NOT_CONFIGURED,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=3600, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["data_mode", "as_of"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="capture_utc", label="Captured", kind="datetime", format="yyyy-MM-dd"),
                ColumnSpec(key="aoi", label="AOI", kind="tag"),
                ColumnSpec(key="layer", label="Layer", kind="tag"),
                ColumnSpec(key="cloud_pct", label="Cloud (proxy)", kind="percent", format="%.1f"),
                ColumnSpec(key="tile_url", label="Tile", kind="action"),
                ColumnSpec(key="source", label="Source", kind="tag"),
            ],
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="aoi", label="AOI", kind="badge"),
                CardSlot(key="latest_capture", label="Capture day (UTC)", kind="timestamp"),
                CardSlot(key="cloud_pct", label="Modelled cloud cover (Open-Meteo)", kind="kpi", unit="%"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "SAT shows real imagery or an explicit unavailable state, and never pretends. "
            "The tile_url is a live NASA GIBS WMS GetMap PNG for the AOI, layer and capture "
            "day (MODIS daily mosaics, no API key). It is probed for reachability. cloud_pct "
            "is the Open-Meteo daily mean cloud cover at the AOI centroid on the capture day, "
            "used as a proxy: it is not read from the image itself. When both sources are "
            "unreachable, SAT returns data_mode='not_configured' with rows=[] and a reason. "
            "No synthetic tiles, placeholder thumbnails or fabricated cloud values are produced. "
            "The window is one capture day; SAT does not search for the lowest-cloud capture."
        ),
        field_dict={
            "data_mode": FieldDef(description="delayed_reference when live; not_configured when both sources are unreachable.", source="envelope"),
            "rows[].capture_utc": FieldDef(unit="UTC", description="GIBS daily mosaic day requested (UTC).", source="provider"),
            "rows[].cloud_pct": FieldDef(unit="%", description="Open-Meteo daily mean cloud cover at the AOI centroid (proxy, not the image's own cloud mask).", source="provider"),
            "rows[].tile_url": FieldDef(description="Live NASA GIBS WMS GetMap PNG URL for the AOI, layer and capture day.", source="provider"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="sat_explicit_unavailable_when_sources_down",
                description="If NASA GIBS and Open-Meteo are both unreachable, SAT returns data_mode='not_configured', rows=[], a reason, and no tile_url. It never returns a synthetic tile.",
                inputs={"_env": "gibs_and_open_meteo_unreachable"},
                assertions=[
                    "data_mode_equals_not_configured",
                    "rows_is_empty_array",
                    "reason_is_present",
                    "no_synthetic_tiles",
                ],
            ),
            SemanticTest(
                name="sat_real_gibs_tile_or_explicit_unavailable",
                description="Every returned row carries a real https://gibs.earthdata.nasa.gov GetMap tile_url, and cloud_pct is numeric or null.",
                inputs={"aoi": "cushing_ok", "layer": "true_color"},
                assertions=[
                    "tile_url_is_gibs_getmap_url",
                    "cloud_pct_is_numeric_or_null",
                    "no_placeholder_thumbnail",
                ],
            ),
            SemanticTest(
                name="sat_capture_day_is_the_requested_day",
                description="The row capture_utc equals the requested capture day (end of the window). SAT does not move the capture to another day.",
                inputs={"aoi": "cushing_ok", "capture_date": "2026-01-01"},
                assertions=["capture_utc_equals_requested_day"],
            ),
        ],
    )


__all__ = ["sat"]
