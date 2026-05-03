"""Round 28 — Tauri update manifest builder.

Tauri's updater plugin reads a single JSON file with this shape:

    {
      "version": "0.0.2",
      "notes": "release notes…",
      "pub_date": "2026-05-15T14:00:00Z",
      "platforms": {
        "darwin-aarch64": {
          "signature": "<base64>",
          "url": "https://github.com/.../showme-aarch64.dmg"
        },
        "darwin-x86_64": {
          "signature": "<base64>",
          "url": "https://github.com/.../showme-x86_64.dmg"
        }
      }
    }

This script walks a release directory laid out as

    release/
      darwin-aarch64/showme.dmg
      darwin-aarch64/showme.dmg.sig
      darwin-x86_64/showme.dmg
      darwin-x86_64/showme.dmg.sig
      windows-x86_64/showme-setup.exe
      windows-x86_64/showme-setup.exe.sig
      ...

and emits the manifest. Pass ``--upload-base`` so the URLs use the
GitHub release download URL.

Usage::

    python scripts/build_release_manifest.py \
        --release-dir release \
        --version 0.0.2 \
        --notes-file release/NOTES.md \
        --upload-base https://github.com/showme-app/showme/releases/download/v0.0.2 \
        --out release/latest.json
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

PLATFORM_KEYS = {
    "darwin-aarch64": (".dmg", ".dmg.tar.gz"),
    "darwin-x86_64": (".dmg", ".dmg.tar.gz"),
    "linux-x86_64": (".AppImage",),
    "windows-x86_64": (".exe",),
}


@dataclass
class PlatformAsset:
    artifact: Path
    signature: Path

    def url(self, base: str) -> str:
        return f"{base.rstrip('/')}/{self.artifact.name}"


def collect_platforms(release_dir: Path) -> dict[str, PlatformAsset]:
    out: dict[str, PlatformAsset] = {}
    for plat, exts in PLATFORM_KEYS.items():
        plat_dir = release_dir / plat
        if not plat_dir.exists():
            continue
        artifact: Path | None = None
        for ext in exts:
            hits = sorted(plat_dir.glob(f"*{ext}"))
            if hits:
                artifact = hits[0]
                break
        if artifact is None:
            continue
        sig = artifact.with_suffix(artifact.suffix + ".sig")
        if not sig.exists():
            print(f"[warn] {plat}: signature missing for {artifact.name}", file=sys.stderr)
            continue
        out[plat] = PlatformAsset(artifact=artifact, signature=sig)
    return out


def build_manifest(
    release_dir: Path,
    version: str,
    notes: str,
    upload_base: str,
    pub_date: datetime | None = None,
) -> dict:
    platforms = collect_platforms(release_dir)
    if not platforms:
        raise SystemExit(f"no platforms found under {release_dir}")
    pd = (pub_date or datetime.now(tz=timezone.utc)).isoformat()
    return {
        "version": version,
        "notes": notes,
        "pub_date": pd,
        "platforms": {
            plat: {
                "signature": asset.signature.read_text().strip(),
                "url": asset.url(upload_base),
            }
            for plat, asset in platforms.items()
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build_release_manifest")
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--notes-file", type=Path)
    parser.add_argument("--notes", default="")
    parser.add_argument("--upload-base", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    notes = args.notes
    if args.notes_file and args.notes_file.exists():
        notes = args.notes_file.read_text().strip()
    manifest = build_manifest(
        release_dir=args.release_dir,
        version=args.version,
        notes=notes,
        upload_base=args.upload_base,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
