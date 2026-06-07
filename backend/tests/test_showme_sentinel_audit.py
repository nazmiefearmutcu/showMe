# ruff: noqa: E402
"""Tests for the sentinel audit script."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Add scripts directory to path to import script under test
SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.append(str(SCRIPTS_DIR))

from showme_sentinel_audit import main


def test_sentinel_audit_picks_latest_subdir(capsys):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Create an older directory with a failing sentinel
        old_dir = tmp_path / "2026-06-01T12-00-00"
        old_dir.mkdir()
        (old_dir / "summary.md").write_text("This contains NaN", encoding="utf-8")

        # Create a newer directory with passing content
        new_dir = tmp_path / "2026-06-02T12-00-00"
        new_dir.mkdir()
        (new_dir / "summary.md").write_text("This is clean", encoding="utf-8")

        # Run main pointing to the parent folder.
        # It should resolve to the newer directory and pass.
        orig_argv = sys.argv
        sys.argv = ["showme_sentinel_audit.py", "--path", tmpdir]
        try:
            exit_code = main()
            assert exit_code == 0
        finally:
            sys.argv = orig_argv


def test_sentinel_audit_fails_if_latest_fails(capsys):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Create an older directory with passing content
        old_dir = tmp_path / "2026-06-01T12-00-00"
        old_dir.mkdir()
        (old_dir / "summary.md").write_text("This is clean", encoding="utf-8")

        # Create a newer directory with a failing sentinel
        new_dir = tmp_path / "2026-06-02T12-00-00"
        new_dir.mkdir()
        (new_dir / "summary.md").write_text("This contains NaN", encoding="utf-8")

        orig_argv = sys.argv
        sys.argv = ["showme_sentinel_audit.py", "--path", tmpdir]
        try:
            exit_code = main()
            assert exit_code == 1
        finally:
            sys.argv = orig_argv
