"""One real /ask through the app's real dependencies, dumping raw Gemini HTTP traffic (key redacted)."""

import json
import sys

sys.path.insert(0, r"C:\created\prjcts\hackatthon\agents_Ops")

import app.llm.gemini as gem  # noqa: E402

N = {"i": 0}


def redact(headers):
    return {k: ("<redacted>" if "key" in k.lower() or "auth" in k.lower() else v) for k, v in headers.items()}


def on_request(req):
    N["i"] += 1
    print(f"\n===== GEMINI REQUEST #{N['i']} =====")
    print(req.method, req.url)
    print(json.dumps(redact(dict(req.headers)), indent=1))
    try:
        print(json.dumps(json.loads(req.content), indent=1))
    except Exception:
        print(req.content[:3000])


def on_response(resp):
    resp.read()
    print(f"\n===== GEMINI RESPONSE #{N['i']} (HTTP {resp.status_code}) =====")
    try:
        print(json.dumps(resp.json(), indent=1))
    except Exception:
        print(resp.text[:3000])


orig_init = gem.GeminiClient.__init__


def patched(self, api_key, model, *a):
    orig_init(self, api_key, model, *a)
    hc = self._client._api_client._httpx_client
    hc.event_hooks["request"].append(on_request)
    hc.event_hooks["response"].append(on_response)


gem.GeminiClient.__init__ = patched

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

q = "Which papers in the corpus discuss reasoning in large language models? Name one and summarize it."
print("POST /ask", json.dumps({"question": q}))
r = TestClient(app, raise_server_exceptions=False).post("/ask", json={"question": q})
print(f"\n===== /ask RESPONSE (HTTP {r.status_code}) =====")
print(json.dumps(r.json(), indent=1))
