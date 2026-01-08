#!/usr/bin/env python3
"""
Audit EPO Deep Tech Finder *website* schema vs our extracted JSON schema.

Why this exists
---------------
The EPO site may call multiple API endpoints behind the scenes. Our current
extraction pulls the list payload from:
  POST /datav/public/datavisualisation/api/dataset/1/applicants

To ensure we are not missing variables exposed elsewhere in the UI, this script:
- Opens the EPO UI in a real (non-headless) browser session (Cloudflare-compatible)
- Records ALL requests to /datav/public/datavisualisation/api/
- Detects the main JS bundle URL(s) and extracts referenced API paths via regex
- Saves a JSON report with:
  - endpoints observed
  - endpoints referenced in JS bundle
  - applicants keys from a live response (if seen)
  - applicants keys from our latest saved extract

Requirements:
  pip3 install playwright
  python3 -m playwright install chromium

Usage:
  # Quick audit (Explore page endpoints + live applicants schema)
  python3 data_collection/audit_epo_site_schema_playwright.py

  # Deep audit (also clicks into per-entity views like Funding history / patents table)
  python3 data_collection/audit_epo_site_schema_playwright.py --deep
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Set

from playwright.sync_api import sync_playwright


EPO_EXPLORE_URL = "https://dtf.epo.org/datav/public/dashboard-frontend/host_epoorg.html#/explore?dataSet=1"


def find_playwright_chromium_executable() -> str:
    """
    Playwright sometimes mis-detects platform/arch and looks for a browser that
    isn't installed (e.g., mac-x64 vs mac-arm64). We defensively pick whichever
    executable exists on disk.
    """
    candidates = [
        # Apple Silicon
        "/Users/oak/Library/Caches/ms-playwright/chromium-1200/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
        # Intel
        "/Users/oak/Library/Caches/ms-playwright/chromium-1200/chrome-mac-x64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
    ]
    for p in candidates:
        if Path(p).exists():
            return p
    return ""


def load_latest_extract_schema() -> Dict[str, Any]:
    raw_dir = Path("research/data/raw")
    files = list(raw_dir.glob("epo_deeptech_complete_*.json"))
    if not files:
        return {"file": None, "entity_keys": []}
    latest = max(files, key=lambda p: p.stat().st_mtime)
    with open(latest, "r", encoding="utf-8") as f:
        d = json.load(f)
    entities = d.get("entities") or []
    keys = sorted(list(entities[0].keys())) if entities else []
    return {"file": str(latest), "entity_keys": keys}


def safe_json(resp_text: str):
    try:
        return json.loads(resp_text)
    except Exception:
        return None


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--deep", action="store_true", help="Click into entity detail views and record additional endpoints")
    args = parser.parse_args()

    report: Dict[str, Any] = {
        "audit_date": datetime.now().isoformat(),
        "epo_explore_url": EPO_EXPLORE_URL,
        "mode": "deep" if args.deep else "quick",
        "observed_api_requests": [],
        "observed_api_endpoints": [],
        "observed_dtf_requests": [],
        "observed_dtf_paths": [],
        "bundle_urls": [],
        "endpoints_found_in_bundles": [],
        "live_applicants_response_keys": None,
        "live_applicants_entity_keys": None,
        "live_filters_response_keys": None,
        "deep_clicks_attempted": [],
        "latest_saved_extract": load_latest_extract_schema(),
        "notes": [
            "If endpoints_found_in_bundles contains endpoints not observed during this run, "
            "it may mean the UI only calls them after clicking into details views.",
            "If you find additional endpoints, we should extend extraction to call them per entity."
        ],
    }

    api_urls_seen: Set[str] = set()
    endpoints_seen: Set[str] = set()
    dtf_urls_seen: Set[str] = set()
    dtf_paths_seen: Set[str] = set()
    bundle_urls: Set[str] = set()
    endpoints_in_bundles: Set[str] = set()

    applicants_live_keys = None
    applicants_entity_keys = None
    filters_live_keys = None

    with sync_playwright() as p:
        executable_path = find_playwright_chromium_executable()
        launch_kwargs = {
            "headless": False,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        }
        if executable_path:
            launch_kwargs["executable_path"] = executable_path

        browser = p.chromium.launch(
            **launch_kwargs,
        )
        context = browser.new_context(viewport={"width": 1600, "height": 900})
        page = context.new_page()

        def on_request(req):
            url = req.url
            # Track all dtf.epo.org requests (useful for per-entity detail endpoints)
            if url.startswith("https://dtf.epo.org/"):
                dtf_urls_seen.add(url)
                m = re.search(r"https?://[^/]+(/[^?#]+)", url)
                if m:
                    dtf_paths_seen.add(m.group(1))

            if "/datav/public/datavisualisation/api/" in url:
                api_urls_seen.add(url)
                # record path-like endpoint
                m = re.search(r"https?://[^/]+(/datav/public/datavisualisation/api/[^?#]+)", url)
                if m:
                    endpoints_seen.add(m.group(1))

            # track main bundle(s) (hash changes)
            if "/datav/public/dashboard-frontend/static/" in url and url.endswith(".js"):
                bundle_urls.add(url)

        def on_response(resp):
            nonlocal applicants_live_keys, applicants_entity_keys
            url = resp.url
            if "/datav/public/datavisualisation/api/dataset/1/applicants" in url:
                try:
                    txt = resp.text()
                except Exception:
                    return
                data = safe_json(txt)
                if isinstance(data, dict) and applicants_live_keys is None:
                    applicants_live_keys = sorted(list(data.keys()))
                    arr = data.get("applicants") or data.get("content") or []
                    if isinstance(arr, list) and arr:
                        applicants_entity_keys = sorted(list(arr[0].keys()))

        page.on("request", on_request)
        page.on("response", on_response)

        page.goto(EPO_EXPLORE_URL, wait_until="networkidle", timeout=60000)

        # Try to click Search to trigger applicants call (best-effort)
        for selector in [
            'button:has-text("Search")',
            'button[type="submit"]',
            '[role="button"]:has-text("Search")',
        ]:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=3000):
                    btn.click()
                    break
            except Exception:
                continue

        # Allow network to settle / additional calls
        page.wait_for_timeout(8000)

        # Guaranteed live schema capture (independent of response handlers / compression)
        try:
            live = page.evaluate(
                """async () => {
                  const url = 'https://dtf.epo.org/datav/public/datavisualisation/api/dataset/1/applicants';
                  const resp = await fetch(url, {
                    method: 'POST',
                    credentials: 'include',
                    headers: {
                      'Content-Type': 'application/json',
                      'Accept': 'application/json, text/plain, */*',
                      'Origin': 'https://dtf.epo.org',
                      'Referer': 'https://dtf.epo.org/datav/public/dashboard-frontend/host_epoorg.html'
                    },
                    body: JSON.stringify({ nextPageToken: '', filters: [] })
                  });
                  const data = await resp.json();
                  const batch = data.applicants || data.content || [];
                  return {
                    responseKeys: Object.keys(data),
                    entityKeys: batch && batch.length ? Object.keys(batch[0]) : null
                  };
                }"""
            )
            if isinstance(live, dict):
                applicants_live_keys = sorted(live.get("responseKeys") or []) or applicants_live_keys
                ek = live.get("entityKeys")
                applicants_entity_keys = sorted(ek) if isinstance(ek, list) else applicants_entity_keys
        except Exception:
            pass

        # Capture filters payload keys (lists of available filters / option sets)
        try:
            filt = page.evaluate(
                """async () => {
                  const url = 'https://dtf.epo.org/datav/public/datavisualisation/api/dataset/1/filters';
                  const resp = await fetch(url, { method: 'GET', credentials: 'include' });
                  const data = await resp.json();
                  return { keys: Object.keys(data) };
                }"""
            )
            if isinstance(filt, dict):
                filters_live_keys = sorted(filt.get("keys") or []) or filters_live_keys
        except Exception:
            pass

        # Optional: deep click into per-entity details (as shown in the UI screenshots)
        if args.deep:
            # Best-effort attempt to open an entity popup:
            # - try clicking a map marker (Leaflet)
            # - if that fails, just look for already-open popup content
            deep_steps = []
            try:
                # Click first Leaflet marker if present
                marker = page.locator(".leaflet-marker-icon").first
                if marker.count() > 0:
                    marker.click()
                    deep_steps.append("clicked .leaflet-marker-icon")
                    page.wait_for_timeout(1500)
            except Exception:
                pass

            # Leaflet often renders interactive circles/paths as SVG with .leaflet-interactive
            try:
                inter = page.locator(".leaflet-interactive").nth(5)
                if inter.count() > 0:
                    inter.click()
                    deep_steps.append("clicked .leaflet-interactive (nth=5)")
                    page.wait_for_timeout(1500)
            except Exception:
                pass

            # Click "+ Add" (opens patent table modal in the UI screenshots)
            try:
                add_btn = page.locator("button:has-text('Add'), a:has-text('Add')").first
                if add_btn.is_visible(timeout=3000):
                    add_btn.click()
                    deep_steps.append("clicked '+ Add'")
                    page.wait_for_timeout(2500)
            except Exception:
                pass

            # Try to click "Funding history" and "European patent applications"
            for label in ["Funding history", "European patent applications"]:
                try:
                    loc = page.get_by_text(label, exact=False).first
                    if loc.is_visible(timeout=3000):
                        loc.click()
                        deep_steps.append(f"clicked {label!r}")
                        page.wait_for_timeout(2500)
                except Exception:
                    # Some UI renders these as links/buttons with icons
                    try:
                        loc = page.locator(f"a:has-text('{label}'), button:has-text('{label}')").first
                        if loc.is_visible(timeout=2000):
                            loc.click()
                            deep_steps.append(f"clicked {label!r} via link/button selector")
                            page.wait_for_timeout(2500)
                    except Exception:
                        pass

            report["deep_clicks_attempted"] = deep_steps

        # Download and scan bundle(s) for API endpoints
        for bu in sorted(bundle_urls):
            try:
                r = context.request.get(bu, timeout=60000)
                if not r.ok:
                    continue
                body = r.text()
            except Exception:
                continue

            # Find API paths referenced in the JS (minified bundle may use different string forms)
            for m in re.finditer(r"(?:https?://[^\"'\\s]+)?/datav/public/datavisualisation/api/[^\"'\\s]+", body):
                endpoints_in_bundles.add(m.group(0))
            for m in re.finditer(r"datavisualisation/api/[^\"'\\s]+", body):
                endpoints_in_bundles.add(m.group(0))

        report["observed_api_requests"] = sorted(api_urls_seen)
        report["observed_api_endpoints"] = sorted(endpoints_seen)
        report["observed_dtf_requests"] = sorted(dtf_urls_seen)
        report["observed_dtf_paths"] = sorted(dtf_paths_seen)
        report["bundle_urls"] = sorted(bundle_urls)
        report["endpoints_found_in_bundles"] = sorted(endpoints_in_bundles)
        report["live_applicants_response_keys"] = applicants_live_keys
        report["live_applicants_entity_keys"] = applicants_entity_keys
        report["live_filters_response_keys"] = filters_live_keys

        out_dir = Path("research/data/raw")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"epo_schema_audit_{datetime.now().strftime('%Y-%m-%d')}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        print(f"✅ Wrote schema audit report: {out_path}")

        browser.close()


if __name__ == "__main__":
    main()


