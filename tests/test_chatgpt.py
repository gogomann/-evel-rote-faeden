"""Anmeldung mit ChatGPT: OAuth mit PKCE, ID-Token-Prüfung, Erneuern, Abmelden, Responses-Stream – alles gegen
simulierte OpenAI-Server, ohne Netz."""

import base64
import hashlib
import json
import os
import random
import tempfile
import threading
import time
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _is_prime(n: int) -> bool:
    if n < 4:
        return n in (2, 3)
    d, r = n - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1
    rng = random.Random(n)
    for _ in range(20):
        x = pow(rng.randrange(2, n - 2), d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _prime(bits: int, rng: random.Random) -> int:
    while True:
        c = rng.getrandbits(bits) | (1 << bits - 1) | 1
        if _is_prime(c):
            return c


class _Key:
    def __init__(self):
        rng = random.Random(4711)
        self.e = 65537
        while True:
            p, q = _prime(512, rng), _prime(512, rng)
            phi = (p - 1) * (q - 1)
            if p != q and phi % self.e:
                break
        self.n, self.d = p * q, pow(self.e, -1, phi)
        self.k = (self.n.bit_length() + 7) // 8

    def jwk(self, kid="k1"):
        enc = lambda i: _b64(i.to_bytes((i.bit_length() + 7) // 8, "big"))
        return {"kty": "RSA", "alg": "RS256", "kid": kid, "n": enc(self.n), "e": enc(self.e)}

    def sign(self, claims: dict, kid="k1") -> str:
        head = _b64(json.dumps({"alg": "RS256", "kid": kid, "typ": "JWT"}).encode())
        body = _b64(json.dumps(claims).encode())
        digest = bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256(f"{head}.{body}".encode()).digest()
        em = b"\x00\x01" + b"\xff" * (self.k - len(digest) - 3) + b"\x00" + digest
        sig = pow(int.from_bytes(em, "big"), self.d, self.n).to_bytes(self.k, "big")
        return f"{head}.{body}.{_b64(sig)}"


KEY = _Key()


class FakeOpenAI(BaseHTTPRequestHandler):
    """auth.openai.com (Token, JWKS, Widerruf) und api.openai.com/v1 (Modelle, Responses) in einem."""
    calls = []
    nonce = None
    client_id = "oaiapp_test123"
    refresh_fails = False
    mode = "ok"

    def log_message(self, *a):
        pass

    def _json(self, code, payload):
        out = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_GET(self):
        FakeOpenAI.calls.append(("GET", self.path, dict(self.headers), None))
        if self.path == "/jwks.json":
            return self._json(200, {"keys": [KEY.jwk()]})
        if self.path == "/v1/models":
            return self._json(200, {"models": [{"slug": "gpt-sol", "display_name": "GPT Sol", "visibility": "list"},
                                               {"slug": "intern", "visibility": "hide"},
                                               {"slug": "gpt-mini", "display_name": "Mini", "visibility": "list"}]})
        self._json(404, {"error": "nicht da"})

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
        if self.headers.get("Content-Type", "").startswith("application/x-www-form-urlencoded"):
            body = dict(urllib.parse.parse_qsl(raw))
        else:
            body = json.loads(raw)
        FakeOpenAI.calls.append(("POST", self.path, dict(self.headers), body))
        if self.path == "/token":
            if body["grant_type"] == "refresh_token" and FakeOpenAI.refresh_fails:
                return self._json(400, {"error": "invalid_grant"})
            now = int(time.time())
            id_token = KEY.sign({"iss": "https://auth.openai.com", "aud": FakeOpenAI.client_id, "sub": "user-1",
                                 "email": "ralf@example.com", "exp": now + 3600, "iat": now, "nonce": FakeOpenAI.nonce})
            scope = "openid profile email offline_access resource.invoke"
            if FakeOpenAI.mode != "ohne_plan":
                scope += " chatgpt.tokens.use.direct"
            suffix = "2" if body["grant_type"] == "refresh_token" else "1"
            return self._json(200, {"access_token": "at-" + suffix, "refresh_token": "rt-" + suffix,
                                    "id_token": id_token, "token_type": "Bearer", "expires_in": 3600, "scope": scope})
        if self.path == "/revoke":
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/v1/responses":
            if FakeOpenAI.mode == "limit":
                return self._json(429, {"error": {"code": "subscription_sharing_usage_limit_exceeded", "message": "Limit"}})
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            events = [{"type": "response.created"}, {"type": "response.output_text.delta", "delta": '{"ok": '},
                      {"type": "response.output_text.delta", "delta": "true}"}]
            if FakeOpenAI.mode == "failed":
                events.append({"type": "response.failed", "response": {
                    "error": {"code": "subscription_sharing_usage_limit_exceeded"}}})
            elif FakeOpenAI.mode != "abgebrochen":
                events.append({"type": "response.completed", "response": {}})
            for ev in events:
                self.wfile.write(f"event: {ev['type']}\ndata: {json.dumps(ev)}\n\n".encode())
            return
        self._json(404, {"error": "nicht da"})


class ChatGPTTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_cfg = os.environ.get("STORY_CONFIG")
        os.environ["STORY_CONFIG"] = os.path.join(self.tmp.name, "cfg.json")
        self.server = HTTPServer(("127.0.0.1", 0), FakeOpenAI)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{self.server.server_address[1]}"
        from story_world import chatgpt, providers
        self.cg, self.pv = chatgpt, providers
        self.saved = (chatgpt.TOKEN_URL, chatgpt.JWKS_URL, chatgpt.REVOKE_URL, providers.PRESET_BY_ID["chatgpt"]["base_url"])
        chatgpt.TOKEN_URL, chatgpt.JWKS_URL, chatgpt.REVOKE_URL = base + "/token", base + "/jwks.json", base + "/revoke"
        chatgpt._JWKS_CACHE.update(keys=None, geladen=0)
        providers.PRESET_BY_ID["chatgpt"]["base_url"] = base + "/v1"
        FakeOpenAI.calls, FakeOpenAI.mode, FakeOpenAI.refresh_fails = [], "ok", False

    def tearDown(self):
        self.cg.TOKEN_URL, self.cg.JWKS_URL, self.cg.REVOKE_URL, self.pv.PRESET_BY_ID["chatgpt"]["base_url"] = self.saved
        self.server.shutdown()
        self.server.server_close()
        if self.old_cfg is None:
            os.environ.pop("STORY_CONFIG", None)
        else:
            os.environ["STORY_CONFIG"] = self.old_cfg
        self.tmp.cleanup()

    def _login(self, pid, mode="ok"):
        url = self.cg.start(pid, 8765)
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        FakeOpenAI.nonce, FakeOpenAI.mode = q["nonce"], mode
        cb = {"code": "c-1", "state": q["state"], "scope": q["scope"]}
        if q["client_id"] == "dynamic_agent_client":
            cb["client_id"] = FakeOpenAI.client_id
        return q, self.cg.callback(cb)

    def test_full_flow(self):
        pid = self.pv.add_provider({"preset": "chatgpt", "base_url": "https://boese.example/v1"})
        p = self.pv.get_provider(pid)
        self.assertEqual(p["type"], "chatgpt")
        self.assertTrue(p["base_url"].endswith("/v1") and "boese" not in p["base_url"])  # Adresse fest
        self.assertFalse(self.pv.public_provider(p)["chatgpt"]["angemeldet"])
        with self.assertRaises(self.pv.ProviderError):
            self.pv.verify(pid)

        q, result = self._login(pid)
        # Erst-Registrierung: dynamischer Client, App-Name, Host-ID, PKCE, Loopback auf 127.0.0.1
        self.assertEqual(q["client_id"], "dynamic_agent_client")
        self.assertEqual(q["agent_name_hint"], "Evel • Rote Fäden")
        self.assertTrue(q["ext_agent_host_id"].startswith("urn:uuid:"))
        self.assertEqual((q["code_challenge_method"], q["redirect_uri"], q["resource"]),
                         ("S256", "http://127.0.0.1:8765/auth/callback", "https://api.openai.com/v1"))
        self.assertIn("chatgpt.tokens.use.direct", q["scope"])
        self.assertTrue(result["ok"], result)
        exchange = [c for c in FakeOpenAI.calls if c[1] == "/token"][0][3]
        self.assertEqual((exchange["client_id"], exchange["redirect_uri"]), (FakeOpenAI.client_id, q["redirect_uri"]))
        self.assertEqual(_b64(hashlib.sha256(exchange["code_verifier"].encode()).digest()), q["code_challenge"])
        self.assertNotIn("client_secret", exchange)

        p = self.pv.get_provider(pid)
        state = self.pv.public_provider(p)
        self.assertNotIn("oauth", state)  # Tokens gehen nie an die Oberfläche
        self.assertEqual((state["chatgpt"]["email"], state["chatgpt"]["plan"], state["chatgpt"]["hinweis_zeigen"]),
                         ("ralf@example.com", True, True))
        self.assertEqual(p["oauth"]["client_id"], FakeOpenAI.client_id)
        self.assertEqual(oct(os.stat(os.environ["STORY_CONFIG"]).st_mode & 0o777), "0o600")

        # Modelle: nur sichtbare, Reihenfolge des Servers
        self.pv.load_models(pid)
        self.assertEqual(self.pv.get_provider(pid)["models"][:2], ["gpt-sol", "gpt-mini"])

        # Inferenz: Responses-API, store=false, stream=true, Systemtext als instructions, keine Sampling-Felder
        chunks = []
        msgs = [{"role": "system", "content": "Nur JSON."}, {"role": "user", "content": "Antworte."}]
        text, used = self.pv.complete(msgs, chain=[(self.pv.get_provider(pid), "gpt-sol")], temperature=0.7,
                                      max_tokens=500, on_chunk=chunks.append)
        self.assertEqual(text, '{"ok": true}')
        self.assertEqual("".join(chunks), text)
        call = [c for c in FakeOpenAI.calls if c[1] == "/v1/responses"][-1]
        body = call[3]
        self.assertEqual(call[2]["Authorization"], "Bearer at-1")
        self.assertEqual((body["store"], body["stream"], body["instructions"]), (False, True, "Nur JSON."))
        # JSON-Modus: OpenAI verlangt „json“ in input (instructions zählen nicht) → Hinweis wird angehängt
        self.assertEqual(body["input"], [{"role": "user", "content": "Antworte.\n\nAntworte ausschließlich mit gültigem JSON."}])
        self.assertEqual(body["text"], {"format": {"type": "json_object"}})
        for field in ("temperature", "max_output_tokens", "max_tokens", "messages"):
            self.assertNotIn(field, body)

        # Ablauf: Token wird mit der ausgestellten Client-ID erneuert, Refresh-Token rotiert
        p = self.pv.get_provider(pid)
        self.pv._set_state(pid, oauth=dict(p["oauth"], expires_at=time.time() - 5))
        self.pv.complete(msgs, chain=[(self.pv.get_provider(pid), "gpt-sol")])
        refresh = [c[3] for c in FakeOpenAI.calls if c[1] == "/token" and c[3]["grant_type"] == "refresh_token"][-1]
        self.assertEqual((refresh["client_id"], refresh["refresh_token"], refresh["resource"]),
                         (FakeOpenAI.client_id, "rt-1", "https://api.openai.com/v1"))
        self.assertEqual(self.pv.get_provider(pid)["oauth"]["refresh_token"], "rt-2")
        self.assertEqual([c for c in FakeOpenAI.calls if c[1] == "/v1/responses"][-1][2]["Authorization"], "Bearer at-2")

        # Limit erreicht: verständlicher Hinweis mit Link zur Nutzung
        FakeOpenAI.mode = "limit"
        with self.assertRaises(self.pv.ProviderError) as ctx:
            self.pv.complete(msgs, chain=[(self.pv.get_provider(pid), "gpt-sol")])
        self.assertIn("chatgpt.com/settings/usage", str(ctx.exception))
        FakeOpenAI.mode = "failed"
        with self.assertRaises(self.pv.ProviderError) as ctx:
            self.pv.complete(msgs, chain=[(self.pv.get_provider(pid), "gpt-sol")])
        self.assertIn("Nutzungslimit", str(ctx.exception))
        FakeOpenAI.mode = "abgebrochen"
        with self.assertRaises(self.pv.ProviderError) as ctx:
            self.pv.complete(msgs, chain=[(self.pv.get_provider(pid), "gpt-sol")])
        self.assertIn("ohne Abschluss", str(ctx.exception))

        # Abmelden: Widerruf mit Refresh-Token, Tokens weg, Client-ID bleibt
        out = self.cg.sign_out(pid)
        self.assertTrue(out["widerrufen"])
        revoke = [c[3] for c in FakeOpenAI.calls if c[1] == "/revoke"][-1]
        self.assertEqual((revoke["token"], revoke["token_type_hint"], revoke["client_id"]),
                         ("rt-2", "refresh_token", FakeOpenAI.client_id))
        p = self.pv.get_provider(pid)
        self.assertNotIn("refresh_token", p["oauth"])
        self.assertEqual(p["oauth"]["client_id"], FakeOpenAI.client_id)

        # Erneute Anmeldung: ausgestellte Client-ID, gleiche Host-ID, kein App-Name
        host = q["ext_agent_host_id"]
        q2, result2 = self._login(pid)
        self.assertEqual((q2["client_id"], q2["ext_agent_host_id"]), (FakeOpenAI.client_id, host))
        self.assertNotIn("agent_name_hint", q2)
        self.assertTrue(result2["ok"])

    def test_refusals(self):
        pid = self.pv.add_provider({"preset": "chatgpt"})
        # unbekannter Versuch
        with self.assertRaises(self.cg.ChatGPTError):
            self.cg.callback({"state": "falsch", "code": "x"})
        # abgelehnt
        url = self.cg.start(pid, 8765)
        state = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))["state"]
        self.assertTrue(self.pv.public_provider(self.pv.get_provider(pid))["chatgpt"]["anmeldung_laeuft"])
        r = self.cg.callback({"state": state, "error": "access_denied"})
        self.assertFalse(r["ok"])
        self.assertFalse(self.pv.public_provider(self.pv.get_provider(pid))["chatgpt"]["anmeldung_laeuft"])
        self.assertFalse([c for c in FakeOpenAI.calls if c[1] == "/token"])
        # Registrierung ohne ausgestellte Client-ID
        url = self.cg.start(pid, 8765)
        state = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))["state"]
        self.assertFalse(self.cg.callback({"state": state, "code": "c"})["ok"])
        # falsche Nonce im ID-Token
        url = self.cg.start(pid, 8765)
        state = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))["state"]
        FakeOpenAI.nonce = "andere"
        r = self.cg.callback({"state": state, "code": "c", "client_id": FakeOpenAI.client_id})
        self.assertFalse(r["ok"])
        self.assertIn("Anmeldeversuch", r["meldung"])
        self.assertFalse(self.cg.signed_in(self.pv.get_provider(pid)))
        # gefälschte Signatur
        good = KEY.sign({"iss": "https://auth.openai.com", "aud": "a", "sub": "s", "exp": time.time() + 60})
        head, body, sig = good.split(".")
        forged = KEY.sign({"iss": "https://auth.openai.com", "aud": "a", "sub": "boese", "exp": time.time() + 60})
        with self.assertRaises(self.cg.ChatGPTError):
            self.cg.validate_id_token(f"{head}.{forged.split('.')[1]}.{sig}", "a", None)
        self.assertEqual(self.cg.validate_id_token(good, "a", None)["sub"], "s")
        # Abo nicht freigegeben: angemeldet, aber keine Inferenz
        _, r = self._login(pid, mode="ohne_plan")
        self.assertFalse(r["ok"])
        p = self.pv.get_provider(pid)
        self.assertTrue(self.cg.signed_in(p) and not self.cg.plan_enabled(p))
        with self.assertRaises(self.pv.ProviderError):
            self.pv.complete([{"role": "user", "content": "x"}], chain=[(p, "gpt-sol")])
        self.assertFalse([c for c in FakeOpenAI.calls if c[1] == "/v1/responses"])
        # erneut fragen: prompt=consent
        self.cg.request_plan_again(pid)
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.cg.start(pid, 8765)).query))
        self.assertEqual(q.get("prompt"), "consent")

    def test_refresh_invalid_asks_for_new_login(self):
        pid = self.pv.add_provider({"preset": "chatgpt"})
        self._login(pid)
        p = self.pv.get_provider(pid)
        self.pv._set_state(pid, oauth=dict(p["oauth"], expires_at=time.time() - 5))
        FakeOpenAI.refresh_fails = True
        with self.assertRaises(self.pv.ProviderError) as ctx:
            self.cg.access_token(self.pv.get_provider(pid))
        self.assertIn("erneut anmelden", str(ctx.exception))
        p = self.pv.get_provider(pid)
        self.assertFalse(self.cg.signed_in(p))
        self.assertEqual(p["oauth"]["client_id"], FakeOpenAI.client_id)

    def test_callback_page(self):
        from story_world import web
        pid = self.pv.add_provider({"preset": "chatgpt"})
        url = self.cg.start(pid, 8765)
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        FakeOpenAI.nonce = q["nonce"]
        page = web.chatgpt_callback_page({"state": q["state"], "code": "c", "client_id": FakeOpenAI.client_id}).decode()
        self.assertIn("Mit ChatGPT angemeldet", page)
        self.assertIn("Modelle sind geladen", page)
        self.assertNotIn("at-1", page)
        self.assertIn("Anmeldung nicht abgeschlossen", web.chatgpt_callback_page({"state": "x"}).decode())


if __name__ == "__main__":
    unittest.main()


class ResponsesJsonTests(unittest.TestCase):
    """OpenAI verlangt bei text.format json_object das Wort „json“ in input – instructions zählen nicht."""

    def test_json_hinweis_nur_wenn_noetig(self):
        from story_world import providers
        body = providers._responses_body("m", [{"role": "system", "content": "Antworte NUR mit JSON."},
                                               {"role": "user", "content": "Bewerte A und B."}], True)
        self.assertEqual(body["text"], {"format": {"type": "json_object"}})
        self.assertIn("json", body["input"][-1]["content"].lower())
        self.assertTrue(body["input"][-1]["content"].startswith("Bewerte A und B."))
        same = providers._responses_body("m", [{"role": "user", "content": "Gib JSON zurück."}], True)
        self.assertEqual(same["input"][-1]["content"], "Gib JSON zurück.")
        plain = providers._responses_body("m", [{"role": "user", "content": "Erzähl."}], False)
        self.assertEqual(plain["input"][-1]["content"], "Erzähl.")
