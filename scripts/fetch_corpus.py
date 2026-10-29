"""Fetch a reproducible sample of arXiv abstracts (cs.CL + cs.LG) into data/corpus.jsonl.

Reproducibility: fixed submission-date windows and sort order give a stable candidate
pool per (category, window); a seeded RNG then samples the final corpus from the pooled
candidates, so every window is represented.
"""
import argparse
import json
import random
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

API = "https://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom"}
# (start, end) as YYYYMMDDHHMM; one window every two months of 2024. Keep in sync with README.
WINDOWS = [
    ("202401010000", "202402292359"),
    ("202403010000", "202404302359"),
    ("202405010000", "202406302359"),
    ("202407010000", "202408312359"),
    ("202409010000", "202410312359"),
    ("202411010000", "202412312359"),
]
CATEGORIES = ["cs.CL", "cs.LG"]


def fetch_pool(category: str, window: tuple[str, str], n: int) -> list[dict]:
    params = {
        "search_query": f"cat:{category} AND submittedDate:[{window[0]} TO {window[1]}]",
        "start": 0,
        "max_results": n,
        "sortBy": "submittedDate",
        "sortOrder": "ascending",
    }
    r = httpx.get(API, params=params, timeout=60, follow_redirects=True)
    r.raise_for_status()
    papers = []
    for e in ET.fromstring(r.text).findall("a:entry", NS):
        url = e.findtext("a:id", namespaces=NS)
        arxiv_id = url.rsplit("/abs/", 1)[-1].split("v")[0]
        papers.append(
            {
                "id": arxiv_id,
                "title": " ".join(e.findtext("a:title", namespaces=NS).split()),
                "abstract": " ".join(e.findtext("a:summary", namespaces=NS).split()),
                "authors": [a.findtext("a:name", namespaces=NS) for a in e.findall("a:author", NS)],
                "published": e.findtext("a:published", namespaces=NS)[:10],
                "categories": [c.get("term") for c in e.findall("a:category", NS)],
                "url": url,
            }
        )
    return papers


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--pool", type=int, default=50, help="candidates fetched per category per window")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="data/corpus.jsonl")
    args = ap.parse_args()

    pool: dict[str, dict] = {}
    for window in WINDOWS:
        for cat in CATEGORIES:
            for p in fetch_pool(cat, window, args.pool):
                pool[p["id"]] = p
            time.sleep(3)  # arXiv API etiquette

    ids = sorted(pool)  # sort before sampling so the seed fully determines the result
    chosen = random.Random(args.seed).sample(ids, min(args.n, len(ids)))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for i in sorted(chosen):
            f.write(json.dumps(pool[i]) + "\n")
    print(f"wrote {len(chosen)} papers to {out}")


if __name__ == "__main__":
    main()
