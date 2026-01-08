#!/usr/bin/env python3
"""
Retry EPO publications for previously-failed org_ids and patch the JSONL in-place.

Why this exists
---------------
`research/data/raw/epo_publications_*.jsonl` may include records like:
  {"org_id": "...", "name": "...", "role": "...", "error": true, ...}

Those failures are usually transient (Cloudflare/session/network). This script:
  1) Finds all `error=true` org_ids in the input JSONL
  2) Re-fetches publications for only those org_ids using Playwright, from the browser context
  3) Rewrites the JSONL, replacing the failed lines with refreshed results

Notes
-----
- A Chromium window will open (non-headless). If Cloudflare shows a challenge,
  solve it in the opened window. The script waits `--cloudflare-wait` seconds.

Typical usage
-------------
  # Patch latest publications file (creates a timestamped backup and overwrites input)
  python3 data_collection/retry_epo_publications_errors.py --inplace

  # Patch a specific file, writing a new output file
  python3 data_collection/retry_epo_publications_errors.py \
    --input research/data/raw/epo_publications_2026-01-06.jsonl \
    --output research/data/raw/epo_publications_2026-01-06_patched.jsonl
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

EPO_EXPLORE_URL = "https://dtf.epo.org/datav/public/dashboard-frontend/host_epoorg.html#/explore?dataSet=1"
PUBLICATIONS_URL = "https://dtf.epo.org/datav/public/datavisualisation/api/dataset/1/publications"


def latest_file(pattern: str) -> Path:
    files = sorted(glob.glob(pattern))
    if not files:
        raise SystemExit(f"No files match {pattern}. Run publications extraction first.")
    return Path(max(files, key=lambda p: Path(p).stat().st_mtime))


def chunks(items: List[str], n: int) -> Iterable[List[str]]:
    for i in range(0, len(items), n):
        yield items[i : i + n]


def load_error_records(inp: Path) -> Dict[str, Dict[str, Any]]:
    """Return {org_id: record} for records where error==True."""
    out: Dict[str, Dict[str, Any]] = {}
    with open(inp, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            obj = json.loads(line)
            if not obj.get("error"):
                continue
            org_id = str(obj.get("org_id") or "").strip()
            if not org_id:
                continue
            out[org_id] = obj
    return out


def _js_fetch_publications(payload_json: str) -> str:
    # payload_json is a JSON string for the JS side, embedded as a literal object
    return f"""async () => {{
  try {{
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
    let data = null;
    try {{
      data = await resp.json();
    }} catch (e) {{
      data = null;
    }}
    return {{ ok: resp.ok, status: resp.status, data: data }};
  }} catch (e) {{
    return {{ ok: false, error: e.toString() }};
  }}
}}""".strip()


def fetch_all_publications(page, org_id: str, *, max_attempts: int, sleep_pages: float, sleep_retry: float) -> Dict[str, Any]:
    """
    Fetch all publications for org_id with pagination.
    Returns:
      - on success: {"ok": True, "publications": [...], "total": int|None, "attempt": int}
      - on failure: {"ok": False, "error": "...", "http_status": int|None, "attempt": int}
    """
    last_err: Optional[str] = None
    last_status: Optional[int] = None

    for attempt in range(1, max_attempts + 1):
        token = ""
        pubs: List[Dict[str, Any]] = []
        total_from_api: Optional[int] = None

        try:
            while True:
                payload = {
                    "nextPageToken": token,
                    "filters": [{"filter_id": "org_id", "filter_values": [{"id": org_id}]}],
                }
                payload_json = json.dumps(payload)
                res = page.evaluate(_js_fetch_publications(payload_json))

                if not isinstance(res, dict) or not res.get("ok"):
                    last_status = res.get("status") if isinstance(res, dict) else None
                    last_err = (res.get("error") if isinstance(res, dict) else None) or (
                        f"HTTP {last_status}" if last_status else "Fetch failed"
                    )
                    raise RuntimeError(last_err)

                data = res.get("data") or {}
                if total_from_api is None and isinstance(data.get("total"), int):
                    total_from_api = int(data["total"])

                batch = data.get("publications") or []
                if batch:
                    pubs.extend(batch)

                token = data.get("nextPageToken") or ""
                if not token:
                    break

                time.sleep(max(0.0, sleep_pages))

            return {"ok": True, "publications": pubs, "total": total_from_api, "attempt": attempt}
        except Exception as e:
            last_err = str(e)
            if attempt < max_attempts:
                # refresh session and try again
                try:
                    page.reload(wait_until="domcontentloaded", timeout=60000)
                except Exception:
                    try:
                        page.goto(EPO_EXPLORE_URL, wait_until="domcontentloaded", timeout=60000)
                    except Exception:
                        pass
                time.sleep(max(0.0, sleep_retry))
                continue

            return {"ok": False, "error": last_err or "Fetch failed", "http_status": last_status, "attempt": attempt}

    return {"ok": False, "error": last_err or "Fetch failed", "http_status": last_status, "attempt": max_attempts}


def rewrite_with_replacements(inp: Path, out: Path, replacements: Dict[str, Dict[str, Any]]) -> None:
    """Rewrite JSONL replacing org_id lines found in replacements."""
    with open(inp, "r", encoding="utf-8") as f_in, open(out, "w", encoding="utf-8") as f_out:
        for line in f_in:
            if not line.strip():
                continue
            obj = json.loads(line)
            org_id = str(obj.get("org_id") or "").strip()
            if org_id and org_id in replacements:
                f_out.write(json.dumps(replacements[org_id], ensure_ascii=False) + "\n")
            else:
                f_out.write(line.rstrip("\n") + "\n")


def verify_publications_file(pub_file: Path) -> Dict[str, Any]:
    """Return simple stats for a publications JSONL."""
    lines = 0
    parsed = 0
    org_ids: List[str] = []
    error_count = 0
    missing_pubs_key = 0

    with open(pub_file, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            lines += 1
            obj = json.loads(line)
            parsed += 1
            oid = obj.get("org_id")
            if oid is not None:
                org_ids.append(str(oid))
            if obj.get("error"):
                error_count += 1
            if "publications" not in obj:
                missing_pubs_key += 1

    return {
        "lines": lines,
        "parsed": parsed,
        "unique_org_ids": len(set(org_ids)),
        "error_count": error_count,
        "missing_publications_key": missing_pubs_key,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Retry error records in epo_publications JSONL and patch file.")
    ap.add_argument("--input", default="", help="Input JSONL (default: latest research/data/raw/epo_publications_*.jsonl)")
    ap.add_argument("--output", default="", help="Output JSONL (default: <input>_patched.jsonl)")
    ap.add_argument("--inplace", action="store_true", help="Overwrite input in-place (creates a timestamped backup)")
    ap.add_argument("--batch-size", type=int, default=50, help="How many org_ids to retry per fresh browser session")
    ap.add_argument("--max-attempts", type=int, default=4, help="Max attempts per org_id")
    ap.add_argument("--cloudflare-wait", type=int, default=30, help="Seconds to wait after loading EPO page")
    ap.add_argument("--sleep-entities", type=float, default=0.25, help="Delay between entity requests (seconds)")
    ap.add_argument("--sleep-pages", type=float, default=0.2, help="Delay between paginated requests (seconds)")
    ap.add_argument("--sleep-retry", type=float, default=2.0, help="Delay before retry after a failure (seconds)")
    args = ap.parse_args()

    inp = Path(args.input) if args.input else latest_file("research/data/raw/epo_publications_*.jsonl")
    if not inp.exists():
        raise SystemExit(f"Input file not found: {inp}")

    if args.output:
        out = Path(args.output)
    else:
        out = inp.with_name(f"{inp.stem}_patched{inp.suffix}")

    error_recs = load_error_records(inp)
    error_ids = sorted(error_recs.keys())

    print("=" * 70)
    print("RETRY FAILED EPO PUBLICATIONS")
    print("=" * 70)
    print(f"Input:  {inp}")
    print(f"Errors: {len(error_ids)}")
    print(f"Batch size: {args.batch_size}")
    print(f"Max attempts per org: {args.max_attempts}")
    print()

    if not error_ids:
        print("✅ No error records found. Nothing to retry.")
        return

    replacements: Dict[str, Dict[str, Any]] = {}
    total_done = 0
    total_ok = 0

    for batch_num, batch in enumerate(chunks(error_ids, max(1, args.batch_size)), start=1):
        print("-" * 70)
        print(f"Batch {batch_num}: {len(batch)} org_ids")
        print("-" * 70)

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

            print("Loading EPO page...")
            print(">>> If Cloudflare shows a challenge, solve it in the opened browser window.")
            try:
                page.goto(EPO_EXPLORE_URL, wait_until="domcontentloaded", timeout=120000)
            except PlaywrightTimeout:
                pass
            except Exception:
                pass

            print(f"Waiting {args.cloudflare_wait}s for Cloudflare/session to be ready...")
            time.sleep(max(0, int(args.cloudflare_wait)))

            for i, org_id in enumerate(batch, start=1):
                old = error_recs.get(org_id) or {}
                name = old.get("name")
                role = old.get("role")

                res = fetch_all_publications(
                    page,
                    org_id,
                    max_attempts=max(1, args.max_attempts),
                    sleep_pages=max(0.0, args.sleep_pages),
                    sleep_retry=max(0.0, args.sleep_retry),
                )

                ts = datetime.utcnow().isoformat() + "Z"
                if res.get("ok"):
                    pubs = res.get("publications") or []
                    total = res.get("total")
                    total_ok += 1
                    replacements[org_id] = {
                        "org_id": org_id,
                        "name": name,
                        "role": role,
                        "total": int(total) if isinstance(total, int) else len(pubs),
                        "publications": pubs,
                        "publication_count": len(pubs),
                        "extraction_timestamp": ts,
                        "retried": True,
                        "retry_attempts": int(res.get("attempt") or 1),
                    }
                else:
                    # keep error record (but mark it as retried)
                    replacements[org_id] = {
                        "org_id": org_id,
                        "name": name,
                        "role": role,
                        "error": True,
                        "http_status": res.get("http_status"),
                        "message": res.get("error") or old.get("message") or "Fetch failed",
                        "extraction_timestamp": ts,
                        "retried": True,
                        "retry_attempts": int(res.get("attempt") or args.max_attempts),
                    }

                total_done += 1
                if i % 10 == 0 or i == len(batch):
                    ok_in_batch = sum(1 for oid in batch[:i] if replacements.get(oid, {}).get("error") is not True)
                    print(f"  {i}/{len(batch)} done (ok: {ok_in_batch}/{i})")

                time.sleep(max(0.0, args.sleep_entities))

            browser.close()

    # Write patched file (always to a temp path first)
    tmp_out = out.with_suffix(out.suffix + ".tmp")
    rewrite_with_replacements(inp, tmp_out, replacements)

    if args.inplace:
        backup = inp.with_suffix(inp.suffix + f".bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(inp, backup)
        os.replace(tmp_out, inp)
        final_path = inp
        print(f"\n✅ Patched in-place: {inp}")
        print(f"🧷 Backup saved:    {backup}")
    else:
        os.replace(tmp_out, out)
        final_path = out
        print(f"\n✅ Patched output written: {out}")

    # Verification
    stats = verify_publications_file(final_path)
    print("\n" + "=" * 70)
    print("POST-PATCH VERIFICATION")
    print("=" * 70)
    print(f"File: {final_path}")
    print(f"Lines: {stats['lines']:,}")
    print(f"Unique org_ids: {stats['unique_org_ids']:,}")
    print(f"Error records: {stats['error_count']:,}")
    print(f"Missing `publications` key: {stats['missing_publications_key']:,}")


if __name__ == "__main__":
    # run from repo root
    if not Path("research").exists():
        raise SystemExit("Run from repo root: cd /Users/oak/Documents/epo")
    main()


