#!/usr/bin/env python3
"""
EPO Publications Extractor - Batch Mode with Browser Restarts

Extracts patent publication details for each entity from the EPO Deep Tech Finder.
Restarts browser every N entities to avoid Cloudflare session timeouts.
"""

import json
import time
import sys
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any
from playwright.sync_api import sync_playwright

# Force unbuffered output
sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None
sys.stderr.reconfigure(line_buffering=True) if hasattr(sys.stderr, 'reconfigure') else None

EPO_EXPLORE_URL = "https://dtf.epo.org/datav/public/dashboard-frontend/host_epoorg.html#/explore?dataSet=1"
PUBLICATIONS_URL = "https://dtf.epo.org/datav/public/datavisualisation/api/dataset/1/publications"


def load_entities():
    """Load entities from the latest EPO extract."""
    raw_dir = Path("research/data/raw")
    files = list(raw_dir.glob("epo_deeptech_complete_*.json"))
    if not files:
        raise SystemExit("No EPO extract found. Run: python3 data_collection/extract_epo_playwright.py")
    latest = max(files, key=lambda p: p.stat().st_mtime)
    with open(latest, "r", encoding="utf-8") as f:
        d = json.load(f)
    return d.get("entities") or []


def load_done_ids(output_path):
    """Load org_ids that have already been extracted."""
    done_ids = set()
    if output_path.exists():
        with open(output_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    org_id = obj.get("org_id")
                    if org_id:
                        done_ids.add(str(org_id))
                except:
                    continue
    return done_ids


def fetch_publications_for_entity(page, org_id: str, name: str) -> Dict[str, Any]:
    """Fetch all publications for one entity."""
    all_pubs = []
    token = ""
    page_no = 0
    
    while True:
        page_no += 1
        payload = {
            "nextPageToken": token,
            "filters": [{"filter_id": "org_id", "filter_values": [{"id": org_id}]}],
        }
        payload_json = json.dumps(payload)
        
        try:
            result = page.evaluate(
                f"""async () => {{
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
                    const data = await resp.json();
                    return {{ ok: resp.ok, status: resp.status, data }}; 
                  }} catch (e) {{
                    return {{ ok: false, error: e.toString() }};
                  }}
                }}"""
            )
            
            if not result.get("ok"):
                return {
                    "org_id": org_id,
                    "name": name,
                    "error": True,
                    "http_status": result.get("status"),
                    "message": result.get("error")
                }
            
            data = result.get("data", {})
            pubs = data.get("publications", [])
            all_pubs.extend(pubs)
            
            token = data.get("nextPageToken", "")
            if not token or not pubs:
                break
                
        except Exception as e:
            return {
                "org_id": org_id,
                "name": name,
                "error": True,
                "message": str(e)
            }
        
        time.sleep(0.2)  # Small delay between pages
    
    return {
        "org_id": org_id,
        "name": name,
        "publications": all_pubs,
        "publication_count": len(all_pubs)
    }


def extract_batch(entities, output_path, batch_num, total_batches):
    """Extract publications for a batch of entities with a fresh browser session."""
    print(f"\n{'='*70}")
    print(f"BATCH {batch_num}/{total_batches}: {len(entities)} entities")
    print(f"{'='*70}\n")
    
    with sync_playwright() as p:
        print("Launching browser...")
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
        print(">>> MANUAL ACTION REQUIRED: Watch the browser window and solve Cloudflare challenge if prompted")
        print(">>> The script will wait 30 seconds for you to complete the challenge")
        try:
            page.goto(EPO_EXPLORE_URL, timeout=30000)  # Just 30s timeout
        except:
            pass  # Timeout is OK, page may have loaded anyway
        
        print("Waiting 30 seconds for manual Cloudflare completion...")
        time.sleep(30)
        print("✓ Continuing with extraction")
        
        print(f"Starting extraction for {len(entities)} entities...\n")
        
        success_count = 0
        mode = "a" if output_path.exists() else "w"
        
        with open(output_path, mode, encoding="utf-8") as f:
            for i, entity in enumerate(entities, start=1):
                org_id = str(entity.get("unique_ID"))
                name = entity.get("name")
                role = entity.get("role")
                
                result = fetch_publications_for_entity(page, org_id, name)
                result["role"] = role
                result["extraction_timestamp"] = datetime.utcnow().isoformat() + "Z"
                
                f.write(json.dumps(result, ensure_ascii=False) + "\n")
                f.flush()
                
                if not result.get("error"):
                    success_count += 1
                
                if i % 10 == 0:
                    print(f"  {i}/{len(entities)} complete (batch {batch_num})")
                
                time.sleep(0.3)  # Delay between entities
        
        browser.close()
        print(f"\n✓ Batch {batch_num} complete: {success_count}/{len(entities)} successful\n")
        return success_count


def main():
    parser = argparse.ArgumentParser(description="Extract EPO publications in batches with browser restarts.")
    parser.add_argument('--batch-size', type=int, default=500, help='Entities per batch (browser restart)')
    parser.add_argument('--roles', default="company", help='Comma-separated roles (company,school,pro)')
    parser.add_argument('--output', default="", help='Override output path')
    args = parser.parse_args()
    
    print("="*70)
    print("EPO PUBLICATIONS EXTRACTION - BATCH MODE")
    print("="*70)
    
    # Load entities
    roles = {r.strip() for r in args.roles.split(",") if r.strip()}
    all_entities = [e for e in load_entities() if e.get("role") in roles]
    
    # Setup output
    out_dir = Path("research/data/raw")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.output) if args.output else (out_dir / f"epo_publications_{datetime.now().strftime('%Y-%m-%d')}.jsonl")
    
    # Load already-done IDs
    done_ids = load_done_ids(out_path)
    remaining = [e for e in all_entities if str(e.get("unique_ID")) not in done_ids]
    
    print(f"\nTotal entities: {len(all_entities)}")
    print(f"Already extracted: {len(done_ids)}")
    print(f"Remaining: {len(remaining)}")
    print(f"Batch size: {args.batch_size}")
    print(f"Output: {out_path}")
    
    if not remaining:
        print("\n✓ All entities already extracted!")
        return
    
    # Split into batches
    batches = [remaining[i:i+args.batch_size] for i in range(0, len(remaining), args.batch_size)]
    print(f"\nProcessing {len(batches)} batches...\n")
    
    total_success = 0
    for batch_num, batch in enumerate(batches, start=1):
        success = extract_batch(batch, out_path, batch_num, len(batches))
        total_success += success
        
        # Pause between batches
        if batch_num < len(batches):
            print(f"Waiting 5 seconds before next batch...\n")
            time.sleep(5)
    
    print("="*70)
    print("EXTRACTION COMPLETE")
    print("="*70)
    print(f"Total extracted: {total_success}/{len(remaining)}")
    print(f"Output file: {out_path}")


if __name__ == "__main__":
    main()

