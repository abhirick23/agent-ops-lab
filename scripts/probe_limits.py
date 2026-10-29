"""Measure free-tier request limits per Gemini model from the 429 QuotaFailure details.

Google's docs do not publish per-model free-tier limits (AI Studio only), so we send tiny
requests back to back until a 429 names the violated quota. Only the first violated quota
is reported, normally requests/minute; per-day limits are not probed (they would take
hundreds of calls) and show up only if you happen to exhaust them.

    python -m scripts.probe_limits gemini-3.6-flash gemini-3.5-flash > results/free_tier_limits.json
"""
import json
import sys
import time

from google import genai
from google.genai import errors, types

from app.config import get_settings

MAX_CALLS = 20


def probe(client: genai.Client, model: str) -> dict:
    started = time.monotonic()
    for n in range(1, MAX_CALLS + 1):
        try:
            client.models.generate_content(model=model, contents="ok", config=types.GenerateContentConfig(max_output_tokens=8))
        except errors.APIError as e:
            out = {"model": model, "calls_before_error": n - 1, "http_status": e.code, "status": e.status}
            if e.code == 429:
                body = e.details if isinstance(e.details, dict) else {}
                for d in body.get("error", {}).get("details", []):
                    for v in d.get("violations", []):
                        out.update(quota_id=v.get("quotaId"), quota_value=v.get("quotaValue"))
                    if d.get("retryDelay"):
                        out["retry_delay"] = d["retryDelay"]
            else:
                out["message"] = str(e)[:200]
            out["seconds"] = round(time.monotonic() - started, 1)
            return out
    return {"model": model, "calls_before_error": MAX_CALLS, "note": f"no 429 in {MAX_CALLS} calls"}


def main() -> None:
    models = sys.argv[1:]
    client = genai.Client(api_key=get_settings().gemini_api_key, http_options=types.HttpOptions(timeout=20000))
    results = []
    for i, m in enumerate(models):
        results.append(probe(client, m))
        print(json.dumps(results[-1]), file=sys.stderr)
        if i < len(models) - 1:
            time.sleep(65)  # let the per-minute window clear so models do not interfere
    print(json.dumps({"measured_at": time.strftime("%Y-%m-%d"), "results": results}, indent=1))


if __name__ == "__main__":
    main()
