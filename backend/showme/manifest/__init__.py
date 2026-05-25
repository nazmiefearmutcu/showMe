"""FunctionManifest contract — single source of truth.

Public surface:
    * ``FunctionManifest`` and every supporting spec model
    * ``REGISTRY`` — process-wide singleton
    * ``manifest`` — decorator helper for seed modules
    * Enum types (``Category``, ``AssetClass``, ``DataMode``,
      ``ControlKind``, ``ChartKind``)
    * ``load_seeds()`` — convenience importer for every bundled seed
"""
from __future__ import annotations

from .enums import (
    AssetClass,
    Category,
    ChartKind,
    ControlKind,
    DataMode,
)
from .registry import REGISTRY, ManifestRegistry, manifest
from .seeds import load_seeds
from .spec import (
    AlertingSpec,
    AxisSpec,
    CachingPolicy,
    CardSchema,
    CardSlot,
    ChartGrammar,
    ColumnSpec,
    FieldDef,
    Formula,
    FunctionManifest,
    InputSpec,
    OutputContract,
    PaneGrammar,
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
    TableSchema,
)

__all__ = [
    # enums
    "AssetClass",
    "Category",
    "ChartKind",
    "ControlKind",
    "DataMode",
    # registry
    "ManifestRegistry",
    "REGISTRY",
    "manifest",
    "load_seeds",
    # spec models
    "AlertingSpec",
    "AxisSpec",
    "CachingPolicy",
    "CardSchema",
    "CardSlot",
    "ChartGrammar",
    "ColumnSpec",
    "FieldDef",
    "Formula",
    "FunctionManifest",
    "InputSpec",
    "OutputContract",
    "PaneGrammar",
    "ProvenanceSpec",
    "ProviderChain",
    "SemanticTest",
    "TableSchema",
]
