"""Round 28 — release manifest builder."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# scripts/ isn't a package; add it to sys.path on demand.
SCRIPT_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import build_release_manifest as brm  # type: ignore  # noqa: E402


@pytest.fixture()
def release_tree(tmp_path: Path) -> Path:
    root = tmp_path / "release"
    for plat in ("darwin-aarch64", "darwin-x86_64"):
        d = root / plat
        d.mkdir(parents=True)
        (d / "showme.dmg").write_bytes(b"fake")
        (d / "showme.dmg.sig").write_text(f"sig-{plat}\n")
    return root


def test_collect_platforms_finds_dmg_and_sig(release_tree: Path) -> None:
    plats = brm.collect_platforms(release_tree)
    assert set(plats) == {"darwin-aarch64", "darwin-x86_64"}
    assert plats["darwin-aarch64"].artifact.name == "showme.dmg"


def test_collect_platforms_skips_when_signature_missing(tmp_path: Path) -> None:
    root = tmp_path / "release"
    (root / "darwin-aarch64").mkdir(parents=True)
    (root / "darwin-aarch64/showme.dmg").write_bytes(b"x")
    plats = brm.collect_platforms(root)
    assert plats == {}


def test_build_manifest_emits_tauri_compatible_shape(release_tree: Path) -> None:
    manifest = brm.build_manifest(
        release_dir=release_tree,
        version="0.0.2",
        notes="round 28 release",
        upload_base="https://example.com/r/v0.0.2",
    )
    assert manifest["version"] == "0.0.2"
    assert manifest["notes"] == "round 28 release"
    plat = manifest["platforms"]["darwin-aarch64"]
    assert plat["signature"] == "sig-darwin-aarch64"
    assert plat["url"].endswith("showme.dmg")
    assert plat["url"].startswith("https://example.com/r/v0.0.2/")


def test_build_manifest_raises_when_no_platforms(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        brm.build_manifest(
            release_dir=tmp_path,
            version="0.0.2",
            notes="x",
            upload_base="https://example.com",
        )


def test_main_writes_manifest_to_disk(tmp_path: Path, release_tree: Path) -> None:
    notes_file = tmp_path / "notes.md"
    notes_file.write_text("Round 28 — auto-update")
    out = tmp_path / "latest.json"
    rc = brm.main([
        "--release-dir", str(release_tree),
        "--version", "0.0.2",
        "--notes-file", str(notes_file),
        "--upload-base", "https://example.com/r/v0.0.2",
        "--out", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text())
    assert payload["version"] == "0.0.2"
    assert payload["notes"] == "Round 28 — auto-update"
    assert "darwin-aarch64" in payload["platforms"]
