#!/usr/bin/env python3
"""
EPO Data Extraction using cloudscraper (Cloudflare bypass library).

This is an alternative approach using cloudscraper, which is specifically
designed to bypass Cloudflare's anti-bot protection.

Requirements:
    pip install cloudscraper

Usage:
    python data_collection/extract_epo_cloudscraper.py
"""

import json
import time
from pathlib import Path
from datetime import datetime
import cloudscraper


API_URL = "https://dtf.epo.org/datav/public/datavisualisation/api/dataset/1/applicants"


def fetch_page(scraper, next_page_token=""):
    """Fetch one page of data."""
    payload = {"nextPageToken": next_page_token, "filters": []}
    
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json, text/plain, */*',
        'Origin': 'https://dtf.epo.org',
        'Referer': 'https://dtf.epo.org/datav/public/dashboard-frontend/host_epoorg.html',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36',
    }
    
    try:
        resp = scraper.post(API_URL, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  ❌ Error: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"     Response: {e.response.text[:200]}")
        return None


def main():
    print("="*70)
    print("EPO DATA EXTRACTION - Cloudscraper (Cloudflare Bypass)")
    print("="*70)
    
    # Create cloudscraper session
    print("\n🌐 Creating cloudscraper session...")
    scraper = cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'darwin',
            'desktop': True
        }
    )
    
    # First, visit the main page to establish session
    print("📡 Visiting EPO site to establish session...")
    try:
        main_url = "https://dtf.epo.org/datav/public/dashboard-frontend/host_epoorg.html#/explore?dataSet=1"
        resp = scraper.get(main_url, timeout=30)
        print(f"✓ Main page loaded (status: {resp.status_code})")
        time.sleep(2)  # Brief pause
    except Exception as e:
        print(f"⚠️  Warning: Could not load main page: {e}")
        print("   Continuing anyway...")
    
    # Extract data
    print("\n📊 Extracting data via API...")
    all_entities = []
    token = ""
    page_num = 0
    
    while True:
        page_num += 1
        print(f"  Page {page_num} (token={token[:20] if token else 'none'}...)")
        
        data = fetch_page(scraper, token)
        
        if not data:
            print("  ❌ Failed to fetch page, stopping.")
            break
        
        # The API returns 'applicants' not 'content'
        content = data.get('applicants') or data.get('content') or []
        
        if not content:
            print("  No more data, stopping.")
            break
        
        all_entities.extend(content)
        print(f"  ✓ Got {len(content)} entities (total: {len(all_entities)})")
        
        token = data.get('nextPageToken') or ""
        if not token:
            print("  No nextPageToken, extraction complete.")
            break
        
        time.sleep(0.5)  # Polite delay
    
    if not all_entities:
        print("\n❌ No entities extracted.")
        print("\n💡 Cloudscraper may not be sufficient for this site.")
        print("   Try Playwright approach or manual browser console extraction.")
        return
    
    # Save results
    output_dir = Path('research/data/raw')
    output_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime('%Y-%m-%d')
    out_file = output_dir / f"epo_deeptech_complete_{date_str}.json"
    
    results = {
        "extraction_date": datetime.now().isoformat(),
        "extraction_method": "cloudscraper",
        "total": len(all_entities),
        "entities": all_entities
    }
    
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    file_size_mb = out_file.stat().st_size / 1024 / 1024
    print(f"\n✅ SUCCESS!")
    print(f"   Extracted: {len(all_entities)} entities")
    print(f"   Saved to: {out_file}")
    print(f"   File size: {file_size_mb:.2f} MB")


if __name__ == "__main__":
    main()

