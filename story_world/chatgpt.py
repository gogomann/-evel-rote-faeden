"""Anmeldung mit ChatGPT (Sign in with ChatGPT, Nutzung des ChatGPT-Abos statt API-Schlüssel).

Ablauf nach https://developers.openai.com/siwc/token-sharing-open-source (offene, lokal laufende Apps):
OAuth 2.0 Authorization Code mit PKCE, öffentlicher Client ohne Geheimnis, Rückruf auf
http://127.0.0.1:<port>/auth/callback (die laufende Oberfläche). Beim ersten Mal registriert sich die App über
client_id=dynamic_agent_client und bekommt eine eigene Client-ID (oaiapp_…), die je Anbieter gespeichert wird.
Zugangsdaten liegen beim Anbieter in story_world.config.json (0600, nicht in Git). Nur Python-Standardbibliothek.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from . import providers

ISSUER = "https://auth.openai.com"
AUTHORIZE_URL = ISSUER + "/api/accounts/authorize"
TOKEN_URL = ISSUER + "/api/accounts/oauth/token"
REVOKE_URL = ISSUER + "/api/accounts/oauth/revoke"
JWKS_URL = ISSUER + "/.well-known/jwks.json"
RESOURCE = "https://api.openai.com/v1"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
PLAN_SCOPE = "chatgpt.tokens.use.direct"
DYNAMIC_CLIENT = "dynamic_agent_client"
APP_NAME = "Evel • Rote Fäden"
CALLBACK_PATH = "/auth/callback"
USAGE_URL = "https://chatgpt.com/settings/usage"

_PENDING: dict = {}          # state -> laufender Anmeldeversuch
_PENDING_TTL = 15 * 60
_REFRESH_LOCK = threading.Lock()
_JWKS_CACHE: dict = {"keys": None, "geladen": 0.0}


class ChatGPTError(providers.ProviderError):
    pass


# ---------------------------------------------------------------- Hilfen

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _post_form(url: str, fields: dict, timeout: int = 30) -> tuple:
    """Gibt (HTTP-Status, JSON-Antwort oder {}) zurück, wirft nur bei Netzwerkfehlern."""
    data = urllib.parse.urlencode(fields).encode("ascii")
    request = urllib.request.Request(url, data=data, method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json", "User-Agent": "StoryWorld/1"})
    try:
        kwargs = {"context": providers._ssl_context()} if url.startswith("https://") else {}
        with urllib.request.urlopen(request, timeout=timeout, **kwargs) as response:
            raw = response.read().decode("utf-8", "replace")
            status = response.status
    except urllib.error.HTTPError as exc:
        raw, status = exc.read().decode("utf-8", "replace"), exc.code
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ChatGPTError(f"OpenAI-Anmeldung nicht erreichbar: {getattr(exc, 'reason', exc)}")
    try:
        return status, (json.loads(raw) if raw.strip() else {})
    except ValueError:
        return status, {"detail": raw[:300]}


def _get_json(url: str, timeout: int = 30) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "StoryWorld/1"})
    try:
        kwargs = {"context": providers._ssl_context()} if url.startswith("https://") else {}
        with urllib.request.urlopen(request, timeout=timeout, **kwargs) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise ChatGPTError(f"Schlüssel der OpenAI-Anmeldung nicht abrufbar: {getattr(exc, 'reason', exc)}")


def _error_code(payload: dict) -> str:
    if not isinstance(payload, dict):
        return ""
    err = payload.get("error")
    if isinstance(err, dict):
        return str(err.get("code") or err.get("type") or "")
    return str(err or payload.get("code") or "")


# ---------------------------------------------------------------- Host-ID

def host_id() -> str:
    """Stabile, undurchsichtige Kennung dieses Rechners (vor der ersten Anmeldung festgelegt und gespeichert)."""
    with providers._LOCK:
        cfg = providers.load()
        value = cfg.get("chatgpt_host_id")
        if not value:
            value = "urn:uuid:" + str(uuid.uuid4())
            cfg["chatgpt_host_id"] = value
            providers.save(cfg)
        return value


# ---------------------------------------------------------------- ID-Token prüfen (RS256, reine Standardbibliothek)

_SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")


def _jwks(force: bool = False) -> list:
    if force or not _JWKS_CACHE["keys"] or time.time() - _JWKS_CACHE["geladen"] > 3600:
        _JWKS_CACHE["keys"] = _get_json(JWKS_URL).get("keys") or []
        _JWKS_CACHE["geladen"] = time.time()
    return _JWKS_CACHE["keys"]


def _rsa_verify(n: int, e: int, message: bytes, signature: bytes) -> bool:
    k = (n.bit_length() + 7) // 8
    if len(signature) != k:
        return False
    em = pow(int.from_bytes(signature, "big"), e, n).to_bytes(k, "big")
    digest = _SHA256_DIGEST_INFO + hashlib.sha256(message).digest()
    expected = b"\x00\x01" + b"\xff" * (k - len(digest) - 3) + b"\x00" + digest
    return secrets.compare_digest(em, expected)


def validate_id_token(id_token: str, client_id: str, nonce: str | None, leeway: int = 120) -> dict:
    try:
        head_b64, body_b64, sig_b64 = id_token.split(".")
        header = json.loads(_b64url_decode(head_b64))
        claims = json.loads(_b64url_decode(body_b64))
        signature = _b64url_decode(sig_b64)
    except (ValueError, AttributeError):
        raise ChatGPTError("ID-Token der Anmeldung ist unlesbar.")
    if header.get("alg") != "RS256":
        raise ChatGPTError(f"Unerwartetes Signaturverfahren im ID-Token: {header.get('alg')}")
    signed = f"{head_b64}.{body_b64}".encode("ascii")
    for attempt in (False, True):  # unbekannte kid: Schlüssel einmal neu laden
        keys = [k for k in _jwks(force=attempt) if k.get("kty") == "RSA" and k.get("kid") == header.get("kid")]
        if keys:
            break
    if not keys:
        raise ChatGPTError("Signaturschlüssel des ID-Tokens nicht gefunden.")
    key = keys[0]
    n = int.from_bytes(_b64url_decode(key["n"]), "big")
    e = int.from_bytes(_b64url_decode(key["e"]), "big")
    if not _rsa_verify(n, e, signed, signature):
        raise ChatGPTError("Signatur des ID-Tokens ist ungültig.")
    now = time.time()
    if claims.get("iss") != ISSUER:
        raise ChatGPTError("ID-Token stammt nicht von OpenAI.")
    aud = claims.get("aud")
    if client_id not in (aud if isinstance(aud, list) else [aud]):
        raise ChatGPTError("ID-Token gehört zu einer anderen App.")
    if float(claims.get("exp", 0)) + leeway < now:
        raise ChatGPTError("ID-Token ist abgelaufen.")
    if nonce is not None and claims.get("nonce") != nonce:
        raise ChatGPTError("ID-Token passt nicht zu diesem Anmeldeversuch.")
    if not claims.get("sub"):
        raise ChatGPTError("ID-Token ohne Konto-Kennung.")
    return claims


# ---------------------------------------------------------------- Anmeldung

def _oauth(p: dict) -> dict:
    return p.get("oauth") or {}


def start(pid: str, port: int) -> str:
    """Baut die Anmelde-Adresse für den Anbieter und merkt sich den Versuch. Rückruf auf die laufende Oberfläche."""
    p = providers.get_provider(pid)
    if p.get("type") != "chatgpt":
        raise ValueError("Dieser Anbieter nutzt keine ChatGPT-Anmeldung.")
    for state in [s for s, v in _PENDING.items() if time.time() - v["erstellt"] > _PENDING_TTL]:
        _PENDING.pop(state, None)
    auth = _oauth(p)
    client_id = auth.get("client_id") or DYNAMIC_CLIENT
    verifier = _b64url(secrets.token_bytes(48))
    state, nonce = _b64url(secrets.token_bytes(24)), _b64url(secrets.token_bytes(24))
    redirect_uri = f"http://127.0.0.1:{int(port)}{CALLBACK_PATH}"
    params = {"client_id": client_id, "ext_agent_host_id": host_id(), "response_type": "code",
              "redirect_uri": redirect_uri, "scope": SCOPES, "resource": RESOURCE, "state": state, "nonce": nonce,
              "code_challenge_method": "S256",
              "code_challenge": _b64url(hashlib.sha256(verifier.encode("ascii")).digest())}
    if client_id == DYNAMIC_CLIENT:
        params["agent_name_hint"] = APP_NAME
    else:
        if auth.get("id_token"):
            params["id_token_hint"] = auth["id_token"]
        if auth.get("email"):
            params["login_hint"] = auth["email"]
        if auth.get("plan_erneut_fragen"):
            params["prompt"] = "consent"
    _PENDING[state] = {"pid": pid, "verifier": verifier, "nonce": nonce, "redirect_uri": redirect_uri,
                       "client_id": client_id, "erstellt": time.time()}
    if auth.get("plan_erneut_fragen"):
        providers._set_state(pid, oauth=dict(auth, plan_erneut_fragen=False))
    return AUTHORIZE_URL + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)


def callback(query: dict) -> dict:
    """Verarbeitet den Rückruf aus dem Browser. Gibt {ok, meldung, pid} zurück (für die Rückrufseite)."""
    state = query.get("state") or ""
    pending = _PENDING.pop(state, None)
    if not pending or time.time() - pending["erstellt"] > _PENDING_TTL:
        raise ChatGPTError("Dieser Anmeldeversuch ist unbekannt oder abgelaufen. Bitte in der App neu starten.")
    pid = pending["pid"]
    try:
        if query.get("error"):
            reason = query.get("error_description") or query["error"]
            if query["error"] == "access_denied":
                raise ChatGPTError("Anmeldung abgebrochen – es wurde nichts freigegeben.")
            raise ChatGPTError(f"OpenAI meldet: {reason}")
        code = query.get("code")
        if not code:
            raise ChatGPTError("Rückruf ohne Anmeldecode.")
        client_id = pending["client_id"]
        returned = query.get("client_id")
        if client_id == DYNAMIC_CLIENT:
            if not returned or returned == DYNAMIC_CLIENT:
                raise ChatGPTError("Registrierung unvollständig: OpenAI hat keine Client-ID geliefert.")
            client_id = returned
        elif returned and returned != client_id:
            raise ChatGPTError("Rückruf gehört zu einer anderen Registrierung – nichts übernommen.")
        status, tokens = _post_form(TOKEN_URL, {"grant_type": "authorization_code", "client_id": client_id,
                                                "code": code, "code_verifier": pending["verifier"],
                                                "redirect_uri": pending["redirect_uri"], "resource": RESOURCE})
        if status != 200 or not tokens.get("access_token"):
            code_txt = _error_code(tokens) or f"HTTP {status}"
            raise ChatGPTError(f"Anmeldecode nicht eingelöst ({code_txt}). Bitte erneut anmelden.")
        claims = validate_id_token(tokens.get("id_token", ""), client_id, pending["nonce"])
        p = providers.get_provider(pid)
        old = _oauth(p)
        if old.get("subject") and old.get("client_id") == client_id and old["subject"] != claims["sub"]:
            raise ChatGPTError("Angemeldet wurde ein anderes ChatGPT-Konto als bei diesem Anbieter gespeichert.")
        scopes = sorted(set((tokens.get("scope") or "").split()))
        record = {"email": claims.get("email", ""), "name": claims.get("name", ""), "issuer": claims["iss"],
                  "subject": claims["sub"], "client_id": client_id, "ext_agent_host_id": host_id(),
                  "id_token": tokens.get("id_token", ""), "access_token": tokens["access_token"],
                  "refresh_token": tokens.get("refresh_token", ""), "token_type": tokens.get("token_type", "Bearer"),
                  "expires_in": int(tokens.get("expires_in") or 3600),
                  "expires_at": time.time() + int(tokens.get("expires_in") or 3600), "scopes": scopes,
                  "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  "erste_anmeldung": not old.get("subject"), "hinweis_gesehen": bool(old.get("hinweis_gesehen"))}
        plan = PLAN_SCOPE in scopes
        providers._set_state(pid, oauth=record, status="ungeprueft" if plan else "fehler",
                             last_error="" if plan else "ChatGPT-Abo nicht freigegeben – „Continue with ChatGPT“ "
                                                        "erneut wählen und die Nutzung des Abos erlauben.")
        if not plan:
            return {"ok": False, "pid": pid, "meldung": "Angemeldet, aber die Nutzung deines ChatGPT-Abos wurde nicht "
                                                        "freigegeben. Ohne diese Freigabe schreibt die KI nicht."}
        return {"ok": True, "pid": pid, "meldung": f"Angemeldet als {record['email'] or 'ChatGPT-Konto'}."}
    except ChatGPTError as exc:
        p = providers.get_provider(pid)
        providers._set_state(pid, last_error=str(exc))
        return {"ok": False, "pid": pid, "meldung": str(exc)}


def _pending_for(pid) -> bool:
    return any(v["pid"] == pid and time.time() - v["erstellt"] < _PENDING_TTL for v in list(_PENDING.values()))


def signed_in(p: dict) -> bool:
    auth = _oauth(p)
    return bool(auth.get("refresh_token") or auth.get("access_token"))


def plan_enabled(p: dict) -> bool:
    return signed_in(p) and PLAN_SCOPE in (_oauth(p).get("scopes") or [])


def access_token(p: dict) -> str:
    """Gültiges Zugangstoken; erneuert es kurz vor Ablauf (serialisiert, damit sich zwei Aufrufe nicht überholen)."""
    auth = _oauth(p)
    if not signed_in(p):
        raise ChatGPTError("Nicht mit ChatGPT angemeldet. Einstellungen → KI-Anbieter → „Continue with ChatGPT“.")
    if PLAN_SCOPE not in (auth.get("scopes") or []):
        raise ChatGPTError("Die Nutzung deines ChatGPT-Abos ist nicht freigegeben – bitte erneut anmelden.")
    if auth.get("access_token") and float(auth.get("expires_at", 0)) - 120 > time.time():
        return auth["access_token"]
    with _REFRESH_LOCK:
        fresh = _oauth(providers.get_provider(p["id"]))  # evtl. hat ein anderer Aufruf schon erneuert
        if fresh.get("access_token") and float(fresh.get("expires_at", 0)) - 120 > time.time():
            p["oauth"] = fresh
            return fresh["access_token"]
        if not fresh.get("refresh_token"):
            raise ChatGPTError("ChatGPT-Anmeldung abgelaufen – bitte erneut anmelden.")
        status, tokens = _post_form(TOKEN_URL, {"grant_type": "refresh_token", "client_id": fresh["client_id"],
                                                "refresh_token": fresh["refresh_token"], "resource": RESOURCE})
        if status == 200 and tokens.get("access_token"):
            fresh.update(access_token=tokens["access_token"],
                         refresh_token=tokens.get("refresh_token") or fresh["refresh_token"],
                         expires_in=int(tokens.get("expires_in") or 3600),
                         expires_at=time.time() + int(tokens.get("expires_in") or 3600),
                         scopes=sorted(set((tokens.get("scope") or " ".join(fresh.get("scopes") or [])).split())),
                         saved_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
            if tokens.get("id_token"):
                fresh["id_token"] = tokens["id_token"]
            providers._set_state(p["id"], oauth=fresh)
            p["oauth"] = fresh
            return fresh["access_token"]
        code = _error_code(tokens)
        if code in ("invalid_grant", "invalid_refresh_token", "token_expired", "refresh_token_expired",
                    "refresh_token_invalidated", "refresh_token_reused"):
            cleared = {k: v for k, v in fresh.items() if k not in ("access_token", "refresh_token", "expires_at")}
            providers._set_state(p["id"], oauth=cleared, status="fehler",
                                 last_error="ChatGPT-Anmeldung nicht mehr gültig – bitte erneut anmelden.")
            p["oauth"] = cleared
            raise ChatGPTError("ChatGPT-Anmeldung nicht mehr gültig (z. B. in ChatGPT getrennt) – bitte erneut anmelden.")
        if code == "invalid_client":
            raise ChatGPTError("OpenAI kennt die Registrierung dieser App nicht mehr (invalid_client).")
        raise ChatGPTError(f"Erneuern der ChatGPT-Anmeldung fehlgeschlagen ({code or f'HTTP {status}'}) – "
                           "später erneut versuchen.")


def sign_out(pid: str) -> dict:
    """Beendet die Sitzung bei OpenAI (Widerruf) und entfernt die Tokens. Client-ID und Host-ID bleiben."""
    p = providers.get_provider(pid)
    auth = _oauth(p)
    confirmed = True
    if auth.get("refresh_token"):
        confirmed = False
        for attempt in range(3):
            try:
                status, _ = _post_form(REVOKE_URL, {"token": auth["refresh_token"], "token_type_hint": "refresh_token",
                                                    "client_id": auth.get("client_id", "")}, timeout=15)
            except ChatGPTError:
                status = 0
            if status == 200:
                confirmed = True
                break
            if status and status < 500:
                break
            time.sleep(0.5 * (attempt + 1))
    keep = {k: auth[k] for k in ("client_id", "email", "subject", "ext_agent_host_id", "hinweis_gesehen") if k in auth}
    providers._set_state(pid, oauth=keep, status="ungeprueft", last_error="")
    return {"ok": True, "widerrufen": confirmed,
            "meldung": "Abgemeldet." if confirmed else
            "Lokal abgemeldet; der Widerruf bei OpenAI wurde nicht bestätigt. Du kannst die App in ChatGPT → "
            "Einstellungen trennen."}


def request_plan_again(pid: str) -> None:
    """Nächste Anmeldung fragt die Freigabe des Abos erneut ab (nach einer Ablehnung)."""
    p = providers.get_provider(pid)
    providers._set_state(pid, oauth=dict(_oauth(p), plan_erneut_fragen=True))


def mark_notice_seen(pid: str) -> None:
    p = providers.get_provider(pid)
    providers._set_state(pid, oauth=dict(_oauth(p), hinweis_gesehen=True))


def public_state(p: dict) -> dict:
    auth = _oauth(p)
    return {"angemeldet": signed_in(p), "plan": plan_enabled(p), "email": auth.get("email", ""),
            "registriert": bool(auth.get("client_id")), "anmeldung_laeuft": _pending_for(p.get("id")),
            "hinweis_zeigen": plan_enabled(p) and not auth.get("hinweis_gesehen"), "nutzung_url": USAGE_URL}


# ---------------------------------------------------------------- Fehler der Responses-API verständlich machen

_PLAN_ERRORS = {
    "subscription_sharing_usage_limit_exceeded":
        f"Nutzungslimit deines ChatGPT-Abos (oder das Limit für diese App) erreicht. Nutzung verwalten: {USAGE_URL}",
    "subscription_sharing_usage_unavailable": "ChatGPT kann die Nutzung gerade nicht prüfen – später erneut versuchen.",
    "subscription_sharing_user_not_eligible":
        "Dein ChatGPT-Konto bzw. Arbeitsbereich darf das Abo nicht in anderen Apps nutzen (nur Plus und Pro).",
    "subscription_sharing_unsupported_capability": "ChatGPT-Abo unterstützt einen Teil der Anfrage nicht",
    "subscription_sharing_route_not_supported": "Dieser Aufruf ist mit dem ChatGPT-Abo nicht erlaubt.",
    "subscription_sharing_invalid_user": "ChatGPT konnte das Konto nicht bestätigen – bitte erneut anmelden.",
    "subscription_sharing_user_unavailable": "ChatGPT-Kontodaten gerade nicht verfügbar – später erneut versuchen.",
}


def explain(code: str, param: str = "", status: int | None = None, detail: str = "") -> str:
    if code in _PLAN_ERRORS:
        text = _PLAN_ERRORS[code]
        if code == "subscription_sharing_unsupported_capability" and param:
            text += f" ({param})."
        return text + (f" [{code}]" if code else "")
    hints = {401: "ChatGPT-Anmeldung wurde nicht akzeptiert – Konto und Freigabe prüfen, ggf. erneut anmelden.",
             403: "ChatGPT hat die Anfrage abgelehnt (Berechtigung oder Region).",
             503: "ChatGPT-Abo-Nutzung gerade nicht verfügbar – später erneut versuchen."}
    base = hints.get(status, "ChatGPT meldet einen Fehler.")
    extra = " ".join(x for x in (f"HTTP {status}" if status else "", code, detail[:200]) if x)
    return f"{base} ({extra})" if extra else base
