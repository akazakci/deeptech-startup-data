#!/usr/bin/env python3
"""
Extract per-entity patent/publication rows from the EPO Deep Tech Finder.

Why this exists
---------------
The main `applicants` endpoint provides only *aggregate* patent totals
(`totalPatents`, `totalGrantedPatents`). The UI also exposes a per-entity table
("European patent applications") with fields like Title / Technical field /
Filing year / Patent status. The frontend uses an additional endpoint:

  POST /datav/public/datavisualisation/api/dataset/1/publications

with payload:
  { nextPageToken: "", filters: [{ filter_id: "org_id", filter_values: [{id: ORG_ID}]}] }

This script downloads those per-entity publication rows for all companies (or a limit).

Inputs:
  - research/data/raw/epo_deeptech_complete_*.json (latest)

Outputs:
  - research/data/raw/epo_publications_{YYYY-MM-DD}.jsonl
    Each line: {"org_id": "...", "name": "...", "role": "...", "publications": [...], "total": N}

Requirements:
  pip3 install playwright
  python3 -m playwright install chromium

Usage:
  python3 data_collection/extract_epo_publications_playwright.py --limit 50
  python3 data_collection/extract_epo_publications_playwright.py
"""

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


EPO_EXPLORE_URL = "https://dtf.epo.org/datav/public/dashboard-frontend/host_epoorg.html#/explore?dataSet=1"
PUBLICATIONS_URL = "https://dtf.epo.org/datav/public/datavisualisation/api/dataset/1/publications"


def load_latest_entities() -> List[Dict[str, Any]]:
    raw_dir = Path("research/data/raw")
    files = list(raw_dir.glob("epo_deeptech_complete_*.json"))
    if not files:
        raise SystemExit("No EPO extract found. Run: python3 data_collection/extract_epo_playwright.py")
    latest = max(files, key=lambda p: p.stat().st_mtime)
    with open(latest, "r", encoding="utf-8") as f:
        d = json.load(f)
    return d.get("entities") or []


def fetch_publications(page, org_id: str, token: str) -> Dict[str, Any]:
    payload = {
        "nextPageToken": token,
        "filters": [{"filter_id": "org_id", "filter_values": [{"id": org_id}]}],
    }
    payload_json = json.dumps(payload)
    return page.evaluate(
        f"""async () => {{
          const resp = await fetch('{PUBLICATIONS_URL}', {{
            method: 'POST',
            credentials: 'include',
            headers: {{
              'Content-Type': 'application/json',
              'Accept': 'application/json, text/plain, */*',
              'Origin': 'https://dtf.epo.org',
              'Referer': 'https://dtf.epo.org/datav/public/dashboard-frontend/host_epoorg.html'
            }},
            body: JSON.stringify({payload_json})
          }});
          const data = await resp.json();
          return {{ ok: resp.ok, status: resp.status, data }}; 
        }}"""
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="Limit number of entities (debug)")
    ap.add_argument("--roles", default="company", help="Comma-separated roles to include (company,school,pro)")
    ap.add_argument("--sleep", type=float, default=0.25, help="Delay between entity requests (seconds)")
    ap.add_argument("--resume", action="store_true", help="Resume: skip org_ids already present in output file")
    ap.add_argument("--output", default="", help="Override output path (default: research/data/raw/epo_publications_YYYY-MM-DD.jsonl)")
    args = ap.parse_args()

    roles = {r.strip() for r in args.roles.split(",") if r.strip()}
    entities = [e for e in load_latest_entities() if e.get("role") in roles]
    if args.limit and args.limit > 0:
        entities = entities[: args.limit]

    out_dir = Path("research/data/raw")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.output) if args.output else (out_dir / f"epo_publications_{datetime.now().strftime('%Y-%m-%d')}.jsonl")

    done_ids = set()
    if args.resume and out_path.exists():
        # Read existing jsonl and collect org_ids we already wrote (including error records)
        with open(out_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                oid = obj.get("org_id")
                if oid:
                    done_ids.add(str(oid))

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )
        context = browser.new_context(viewport={"width": 1600, "height": 900})
        page = context.new_page()

        # Establish session (Cloudflare-cleared browser context)
        print("Loading EPO page and waiting for Cloudflare...")
        print("(This may take 1-2 minutes. The browser window should open.)")
        page.goto(EPO_EXPLORE_URL, wait_until="domcontentloaded", timeout=120000)
        print("Page loaded. Waiting for Cloudflare challenge to clear...")
        try:
            page.wait_for_timeout(10000)
        except PlaywrightTimeout:
            pass
        print("Cloudflare wait complete. Starting extraction...")

        if done_ids:
            entities = [e for e in entities if str(e.get("unique_ID")) not in done_ids]
        n = len(entities)
        print(f"Extracting publications for {n} entities -> {out_path}")
        if args.resume:
            print(f"Resume mode: skipping {len(done_ids)} already-written org_ids")

        mode = "a" if args.resume and out_path.exists() else "w"
        with open(out_path, mode, encoding="utf-8") as f:
            for i, e in enumerate(entities, start=1):
                org_id = str(e.get("unique_ID"))
                name = e.get("name")
                role = e.get("role")

                pubs: List[Dict[str, Any]] = []
                token = ""
                page_no = 0
                while True:
                    page_no += 1
                    res = fetch_publications(page, org_id, token)
                    if not res or not res.get("ok"):
                        # log minimal info and stop this org
                        err = {
                            "org_id": org_id,
                            "name": name,
                            "role": role,
                            "error": True,
                            "http_status": res.get("status") if isinstance(res, dict) else None,
                            "data_keys": list((res.get("data") or {}).keys()) if isinstance(res, dict) else None,
                        }
                        f.write(json.dumps(err, ensure_ascii=False) + "\n")
                        break

                    data = res.get("data") or {}
                    batch = data.get("publications") or []
                    if batch:
                        pubs.extend(batch)

                    token = data.get("nextPageToken") or ""
                    if not token:
                        break

                    # polite pacing
                    time.sleep(max(0.0, args.sleep))

                rec = {
                    "org_id": org_id,
                    "name": name,
                    "role": role,
                    "total": len(pubs),
                    "publications": pubs,
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

                if i % 10 == 0 or i == n:
                    print(f"  {i}/{n} done")
                time.sleep(max(0.0, args.sleep))

        browser.close()

    print("✅ Done")


if __name__ == "__main__":
    main()


