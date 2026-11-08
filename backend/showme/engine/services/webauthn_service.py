"""WebAuthn / Passkey service (BIO).

Plan §20.5: macOS Touch ID / Windows Hello / passkey login.
``fido2`` paketi ile registration + authentication akışı. Credentials
``runtime/webauthn_credentials.sqlite``'ta saklanır.
"""

from __future__ import annotations

import base64
import binascii
import json
import sqlite3
import time
from types import SimpleNamespace
from typing import Any

from showme.app_paths import runtime_path


def _db_file():
    return runtime_path("webauthn.sqlite")


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(str(_db_file()))
    con.execute("""
        CREATE TABLE IF NOT EXISTS credentials (
            user_id TEXT NOT NULL,
            credential_id BLOB NOT NULL,
            public_key BLOB NOT NULL,
            sign_count INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            PRIMARY KEY (user_id, credential_id)
        )""")
    con.execute("""
        CREATE TABLE IF NOT EXISTS pending (
            user_id TEXT NOT NULL,
            challenge BLOB NOT NULL,
            kind TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            state_json TEXT
        )""")
    # HNT-01: databases created before state was persisted need the new
    # column; fresh databases already have it (ALTER then raises harmlessly).
    try:
        con.execute("ALTER TABLE pending ADD COLUMN state_json TEXT")
    except sqlite3.OperationalError:
        pass
    con.commit()
    return con


def _encode_state(state: dict[str, Any]) -> str:
    """JSON-encode an authenticate_begin state (bytes fields → base64)."""
    def _enc(v: Any) -> Any:
        if isinstance(v, (bytes, bytearray)):
            return {"__b64__": base64.b64encode(bytes(v)).decode("ascii")}
        if isinstance(v, dict):
            return {k: _enc(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [_enc(x) for x in v]
        return v
    return json.dumps({k: _enc(v) for k, v in state.items()})


def _decode_state(raw: str) -> dict[str, Any]:
    """Reverse :func:`_encode_state` (challenge returns as ``bytes``)."""
    def _dec(v: Any) -> Any:
        if isinstance(v, dict):
            if "__b64__" in v:
                return base64.b64decode(v["__b64__"])
            return {k: _dec(x) for k, x in v.items()}
        if isinstance(v, list):
            return [_dec(x) for x in v]
        return v
    return {k: _dec(v) for k, v in json.loads(raw).items()}


def _b64url_decode(value: Any) -> bytes:
    """Decode the unpadded base64url fields a browser WebAuthn call sends.

    Tolerates raw bytes, padded/standard base64 and hex so exotic client
    encodings still verify rather than failing with a confusing error.
    """
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    raw = str(value or "")
    if not raw:
        return b""
    try:
        return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except (binascii.Error, ValueError):
        pass
    try:
        return bytes.fromhex(raw)
    except ValueError:
        return raw.encode("utf-8")


class _RegisteredCredential:
    """Attribute-compatible stand-in for fido2's RegisteredCredential.

    ``authenticate_complete`` reads ``credential_id``, ``public_key`` and
    ``sign_count`` off each entry (the sign_count feeds fido2's clone
    detector), so a plain namespace works across the fido2 0.x NamedTuple
    and 1.x dataclass shapes.
    """

    def __init__(self, credential_id: bytes, public_key: bytes,
                 sign_count: int = 0) -> None:
        self.credential_id = credential_id
        self.public_key = public_key
        self.sign_count = sign_count


def _build_assertion(response: dict[str, Any]) -> tuple[bytes, Any]:
    """Extract ``(credential_id, assertion)`` from the browser JSON.

    The assertion object is assembled from the standard WebAuthn response
    fields (clientDataJSON / authenticatorData / signature). When the
    fido2 constructors are unavailable a plain namespace carrying the
    same attributes is returned so verification still runs.
    """
    body = response.get("response") if isinstance(response.get("response"), dict) else response
    credential_id = _b64url_decode(
        response.get("rawId") or response.get("id") or body.get("id") or b""
    )
    client_data = _b64url_decode(body.get("clientDataJSON", ""))
    auth_data = _b64url_decode(body.get("authenticatorData", ""))
    signature = _b64url_decode(body.get("signature", ""))
    try:
        from fido2.webauthn import (  # type: ignore
            AuthenticatorAssertionResponse,
            AuthenticatorData,
            CollectedClientData,
        )
        assertion: Any = AuthenticatorAssertionResponse(
            client_data=CollectedClientData(client_data),
            authenticator_data=AuthenticatorData(auth_data),
            signature=signature,
        )
    except Exception:
        assertion = SimpleNamespace(
            client_data=client_data,
            authenticator_data=auth_data,
            signature=signature,
        )
    return credential_id, assertion


def _verify_assertion(
    server: Any,
    state: dict[str, Any],
    creds: list[tuple],
    response: dict[str, Any],
) -> tuple[bytes, int]:
    """Run fido2's ``authenticate_complete`` (cross-version arities).

    Returns ``(credential_id, new sign_count)`` — the counter the
    assertion carried when the authenticator reports one, otherwise the
    stored value + 1.
    """
    credential_id, assertion = _build_assertion(response)
    registered = [
        _RegisteredCredential(bytes(r[0]), bytes(r[1]), int(r[2])) for r in creds
    ]
    stored = {bytes(r[0]): int(r[2]) for r in creds}
    try:
        server.authenticate_complete(state, registered, credential_id, assertion)
    except TypeError:
        # fido2 < 1.0 signature: authenticate_complete(state, credentials, response)
        server.authenticate_complete(state, registered, assertion)
    counter = getattr(getattr(assertion, "authenticator_data", None), "counter", None)
    if isinstance(counter, int):
        return credential_id, counter
    return credential_id, stored.get(credential_id, 0) + 1


def begin_registration(user_id: str, user_name: str) -> dict[str, Any]:
    """Generate the registration challenge."""
    try:
        from fido2.server import Fido2Server  # type: ignore
        from fido2.webauthn import (  # type: ignore
            PublicKeyCredentialRpEntity, PublicKeyCredentialUserEntity,
            UserVerificationRequirement,
        )
    except Exception:
        return {"error": "fido2 not installed; pip install fido2"}
    server = Fido2Server(PublicKeyCredentialRpEntity(name="ShowMe", id="localhost"))
    user = PublicKeyCredentialUserEntity(id=user_id.encode(), name=user_name,
                                          display_name=user_name)
    options, state = server.register_begin(
        user, [], user_verification=UserVerificationRequirement.PREFERRED,
    )
    con = _db()
    con.execute("INSERT INTO pending(user_id, challenge, kind, created_at) VALUES (?,?,?,?)",
                [user_id, state["challenge"], "register", int(time.time())])
    con.commit(); con.close()
    return {"options": dict(options)}


def complete_registration(user_id: str, response: dict[str, Any]) -> dict[str, Any]:
    """Verify the registration response and persist the credential."""
    try:
        from fido2.server import Fido2Server  # type: ignore
        from fido2.webauthn import PublicKeyCredentialRpEntity  # type: ignore
    except Exception:
        return {"error": "fido2 not installed"}
    server = Fido2Server(PublicKeyCredentialRpEntity(name="ShowMe", id="localhost"))
    con = _db()
    try:
        row = con.execute(
            "SELECT challenge FROM pending WHERE user_id = ? AND kind = 'register' "
            "ORDER BY created_at DESC LIMIT 1",
            [user_id]).fetchone()
        if not row:
            return {"error": "no pending registration"}
        state = {"challenge": row[0]}
        # HNT-20: register_complete raises on malformed/attacker-crafted
        # responses — the connection must be closed either way (was: leaked
        # to the GC on every failed attempt) and the failure is returned as
        # the service's standard {"error": ...} shape instead of raising.
        try:
            auth_data = server.register_complete(state, response)
        except Exception as e:
            return {"error": f"registration verification failed: {str(e) or type(e).__name__}"}
        cred_id = bytes(auth_data.credential_data.credential_id)
        public_key = bytes(auth_data.credential_data.public_key)
        con.execute("INSERT INTO credentials(user_id, credential_id, public_key, sign_count, created_at) VALUES (?,?,?,?,?)",
                    [user_id, cred_id, public_key, 0, int(time.time())])
        con.execute("DELETE FROM pending WHERE user_id = ? AND kind = 'register'", [user_id])
        con.commit()
        return {"credential_id_hex": cred_id.hex()}
    finally:
        con.close()


def list_credentials(user_id: str) -> list[dict[str, Any]]:
    con = _db()
    rows = con.execute("SELECT credential_id, sign_count, created_at FROM credentials WHERE user_id = ?",
                       [user_id]).fetchall()
    con.close()
    return [{"credential_id_hex": r[0].hex(), "sign_count": r[1], "created_at": r[2]} for r in rows]


def begin_authentication(user_id: str) -> dict[str, Any]:
    try:
        from fido2.server import Fido2Server  # type: ignore
        from fido2.webauthn import (  # type: ignore
            PublicKeyCredentialRpEntity, PublicKeyCredentialDescriptor,
        )
    except Exception:
        return {"error": "fido2 not installed"}
    server = Fido2Server(PublicKeyCredentialRpEntity(name="ShowMe", id="localhost"))
    con = _db()
    rows = con.execute("SELECT credential_id FROM credentials WHERE user_id = ?",
                       [user_id]).fetchall()
    if not rows:
        con.close()
        return {"error": "no credentials registered"}
    descs = [PublicKeyCredentialDescriptor(id=r[0]) for r in rows]
    options, state = server.authenticate_begin(descs)
    con.execute(
        "INSERT INTO pending(user_id, challenge, kind, created_at, state_json) VALUES (?,?,?,?,?)",
        [user_id, state.get("challenge") or b"", "auth", int(time.time()),
         _encode_state(state)],
    )
    con.commit(); con.close()
    return {"options": dict(options)}


def complete_authentication(user_id: str, response: dict[str, Any]) -> dict[str, Any]:
    """Verify a passkey assertion server-side. Returns {authenticated: True}.

    HNT-01: the browser's ``{"ok": true}`` flag is NEVER trusted on its
    own — a client saying "ok" logged in as any user. The assertion is
    verified against the challenge issued by ``begin_authentication``
    via ``Fido2Server.authenticate_complete`` using the stored state and
    the user's registered public keys; any failure returns an error and
    leaves the pending challenge in place.
    """
    try:
        from fido2.server import Fido2Server  # type: ignore
        from fido2.webauthn import PublicKeyCredentialRpEntity  # type: ignore
    except Exception:
        return {"error": "fido2 not installed"}
    server = Fido2Server(PublicKeyCredentialRpEntity(name="ShowMe", id="localhost"))
    con = _db()
    try:
        row = con.execute(
            "SELECT challenge, state_json FROM pending WHERE user_id = ? AND kind = 'auth' "
            "ORDER BY created_at DESC LIMIT 1",
            [user_id]).fetchone()
        if not row:
            return {"error": "no pending auth"}
        state = _decode_state(row[1]) if row[1] else {"challenge": row[0]}
        creds = con.execute(
            "SELECT credential_id, public_key, sign_count FROM credentials WHERE user_id = ?",
            [user_id]).fetchall()
        if not creds:
            return {"error": "no credentials registered"}
        try:
            credential_id, sign_count = _verify_assertion(server, state, creds, response)
        except Exception as e:
            return {"error": f"verification failed: {str(e) or type(e).__name__}"}
        # FR-03: bump ONLY the credential that authenticated (the old
        # UPDATE raised every credential the user owns) and store the
        # counter the assertion carried so fido2's clone detector has a
        # real baseline on the next authentication.
        con.execute(
            "UPDATE credentials SET sign_count = ? WHERE user_id = ? AND credential_id = ?",
            [sign_count, user_id, credential_id])
        con.execute("DELETE FROM pending WHERE user_id = ? AND kind = 'auth'", [user_id])
        con.commit()
        return {"authenticated": True, "user_id": user_id}
    finally:
        con.close()
