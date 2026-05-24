"""SEC-11: certifi cacert.pem must be bundled and pinned for curl_cffi.

PyInstaller bundles relocate libssl/libcrypto; ssl.get_default_verify_paths
returns the BUILD host's path which doesn't exist on the user's machine.
curl_cffi captures DEFAULT_CACERT at module import, so server.py exports
SSL_CERT_FILE / CURL_CA_BUNDLE / REQUESTS_CA_BUNDLE *before* any HTTP
backend imports.
"""
from __future__ import annotations

import os

import certifi
import pytest


def test_bundled_cacert_exists_and_is_nonempty():
    """certifi.where() must point at a real PEM with at least one CERTIFICATE."""
    path = certifi.where()
    assert os.path.isfile(path), f"missing cacert.pem at {path}"
    head = open(path, "rb").read(64 * 1024)
    assert b"-----BEGIN CERTIFICATE-----" in head, (
        "cacert.pem looks empty/truncated"
    )


def test_pin_bundled_cacert_sets_env_vars(monkeypatch):
    """_pin_bundled_cacert exports the env vars curl_cffi reads first."""
    from showme import server

    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)

    server._pin_bundled_cacert()

    expected = certifi.where()
    assert os.environ.get("SSL_CERT_FILE") == expected
    assert os.environ.get("CURL_CA_BUNDLE") == expected
    assert os.environ.get("REQUESTS_CA_BUNDLE") == expected


def test_pin_bundled_cacert_respects_existing_env(monkeypatch):
    """User-supplied SSL_CERT_FILE overrides must NOT be clobbered."""
    from showme import server

    user_path = "/tmp/user-supplied-cacert.pem"
    monkeypatch.setenv("SSL_CERT_FILE", user_path)
    monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)

    server._pin_bundled_cacert()

    # User override preserved; bundled defaults populated for the others.
    assert os.environ.get("SSL_CERT_FILE") == user_path
    assert os.environ.get("CURL_CA_BUNDLE") == certifi.where()
    assert os.environ.get("REQUESTS_CA_BUNDLE") == certifi.where()


def test_pin_bundled_cacert_no_certifi_is_noop(monkeypatch):
    """If certifi can't be imported, _pin_bundled_cacert must not raise."""
    import builtins

    from showme import server

    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    real_import = builtins.__import__

    def _fail_certifi(name, *args, **kwargs):
        if name == "certifi":
            raise ImportError("simulated missing certifi")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fail_certifi)

    # Must not raise.
    server._pin_bundled_cacert()
    assert "SSL_CERT_FILE" not in os.environ


@pytest.mark.skipif(
    "curl_cffi" not in __import__("sys").modules
    and not __import__("importlib.util", fromlist=["find_spec"]).find_spec("curl_cffi"),
    reason="curl_cffi not installed in this env",
)
def test_curl_cffi_uses_bundled_cacert():
    """curl_cffi DEFAULT_CACERT resolves to a real file inside the bundle."""
    # Force re-import so the env vars set by conftest/_pin take effect for
    # the module-load capture. In practice this only matters in the frozen
    # bundle; in dev it should already be resolving correctly.
    import importlib

    import curl_cffi.curl as cc

    importlib.reload(cc)
    assert cc.DEFAULT_CACERT, "DEFAULT_CACERT is empty"
    assert os.path.isfile(cc.DEFAULT_CACERT), (
        f"DEFAULT_CACERT points at non-existent {cc.DEFAULT_CACERT!r} — "
        "ssl.get_default_verify_paths() returned a stale build-host path"
    )
