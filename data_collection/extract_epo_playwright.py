#!/usr/bin/env python3
"""
EPO Data Extraction using Playwright with stealth and real user interactions.

This script:
1. Launches a real browser (non-headless) with stealth plugins
2. Actually clicks around the UI like a human would
3. Waits for Cloudflare to clear naturally
4. Extracts data via API calls from the browser context
5. Handles pagination automatically

Requirements:
    pip3 install playwright
    python3 -m playwright install chromium

Usage:
    python3 data_collection/extract_epo_playwright.py
"""

import json
import time
import random
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


API_URL = "https://dtf.epo.org/datav/public/datavisualisation/api/dataset/1/applicants"


def human_delay(min_ms=500, max_ms=2000):
    """Random delay to mimic human behavior."""
    time.sleep(random.uniform(min_ms / 1000, max_ms / 1000))


def extract_via_api(page, next_page_token=""):
    """Extract one page of data via API call from browser context."""
    payload = {"nextPageToken": next_page_token, "filters": []}
    payload_json = json.dumps(payload)
    
    result = page.evaluate(f"""
        async () => {{
            try {{
                const payload = {payload_json};
                const resp = await fetch('{API_URL}', {{
                    method: 'POST',
                    credentials: 'include',
                    headers: {{
                        'Content-Type': 'application/json',
                        'Accept': 'application/json, text/plain, */*',
                        'Origin': 'https://dtf.epo.org',
                        'Referer': 'https://dtf.epo.org/datav/public/dashboard-frontend/host_epoorg.html'
                    }},
                    body: JSON.stringify(payload)
                }});
                if (!resp.ok) {{
                    const text = await resp.text();
                    return {{ ok: false, error: `HTTP ${{resp.status}}: ${{text.substring(0, 200)}}` }};
                }}
                const data = await resp.json();
                return {{ ok: true, data: data }};
            }} catch (e) {{
                return {{ ok: false, error: e.toString() }};
            }}
        }}
    """)
    
    return result


def extract_all_entities(page):
    """Extract all entities using nextPageToken pagination."""
    all_entities = []
    token = ""
    page_num = 0
    
    print("  Starting pagination...")
    
    while True:
        page_num += 1
        print(f"  Page {page_num} (token={token[:20] if token else 'none'}...)")
        
        result = extract_via_api(page, token)
        
        if not result.get('ok'):
            error_msg = result.get('error', 'Unknown error')
            print(f"  ❌ Error: {error_msg}")
            # If it's a 500 or empty response, might be Cloudflare blocking
            if '500' in error_msg or 'empty' in error_msg.lower():
                print("  ⚠️  This might be Cloudflare blocking. Try manual browser console method.")
            break
        
        data = result['data']
        # The API returns 'applicants' not 'content'
        content = data.get('applicants') or data.get('content') or []
        
        # Debug: print what we got
        if page_num == 1:
            print(f"  Debug: Response keys: {list(data.keys())}")
            print(f"  Debug: Content length: {len(content)}")
            print(f"  Debug: Has nextPageToken: {bool(data.get('nextPageToken'))}")
            if 'totalNrOfRows' in data:
                print(f"  Debug: Total rows reported: {data.get('totalNrOfRows')}")
        
        if not content:
            print("  No more data, stopping.")
            # Check if we got any response at all
            if page_num == 1 and not data:
                print("  ⚠️  Empty response on first page - Cloudflare may be blocking")
            break
        
        all_entities.extend(content)
        print(f"  ✓ Got {len(content)} entities (total: {len(all_entities)})")
        
        token = data.get('nextPageToken') or ""
        if not token:
            print("  No nextPageToken, extraction complete.")
            break
        
        # Human-like delay between pages
        human_delay(300, 800)
    
    return all_entities


def main():
    print("="*70)
    print("EPO DATA EXTRACTION - Playwright with Real User Interactions")
    print("="*70)
    
    with sync_playwright() as p:
        # Launch browser with stealth settings
        print("\n🌐 Launching browser (non-headless for Cloudflare)...")
        browser = p.chromium.launch(
            headless=False,  # Must be visible for Cloudflare
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-setuid-sandbox',
            ]
        )
        
        # Create context with realistic settings
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36',
            locale='en-US',
            timezone_id='America/New_York',
        )
        
        # Add stealth scripts to hide automation
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            
            // Override permissions
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
            
            // Mock plugins
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            
            // Mock languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });
        """)
        
        page = context.new_page()
        
        try:
            # Navigate to EPO site
            url = "https://dtf.epo.org/datav/public/dashboard-frontend/host_epoorg.html#/explore?dataSet=1"
            print(f"📡 Navigating to EPO site...")
            page.goto(url, wait_until='networkidle', timeout=60000)
            
            # Wait for Cloudflare challenge to clear (if present)
            print("⏳ Waiting for Cloudflare challenge to clear...")
            human_delay(5000, 8000)  # Longer wait for Cloudflare
            
            # Check if page loaded successfully
            try:
                page.wait_for_selector('body', timeout=15000)
                print("✓ Page loaded successfully")
            except PlaywrightTimeout:
                print("⚠️  Page load timeout, but continuing...")
            
            # Simulate human behavior: move mouse, scroll
            print("🖱️  Simulating human interactions...")
            page.mouse.move(random.randint(100, 500), random.randint(100, 500))
            human_delay(1000, 2000)
            page.evaluate("window.scrollTo(0, 300)")
            human_delay(2000, 3000)
            page.evaluate("window.scrollTo(0, 0)")
            human_delay(1000, 2000)
            
            # Try to find and click the "Search" button if it exists
            # This helps establish a "real" session
            print("🔍 Looking for Search button to establish session...")
            search_clicked = False
            try:
                # Try multiple selectors for search button
                selectors = [
                    'button:has-text("Search")',
                    'button[type="submit"]',
                    '[role="button"]:has-text("Search")',
                    'button:has-text("Apply")',
                    'button:has-text("Filter")',
                ]
                for selector in selectors:
                    try:
                        search_button = page.locator(selector).first
                        if search_button.is_visible(timeout=3000):
                            print(f"  Found button with selector: {selector}")
                            search_button.click()
                            search_clicked = True
                            human_delay(3000, 5000)  # Wait after click
                            break
                    except:
                        continue
                if not search_clicked:
                    print("  (No Search button found, continuing...)")
            except Exception as e:
                print(f"  (Error looking for Search button: {e})")
            
            # Additional wait to ensure session is established
            print("⏳ Waiting for session to stabilize...")
            human_delay(2000, 3000)
            
            # Now extract data via API
            print("\n📊 Extracting data via API...")
            all_entities = extract_all_entities(page)
            
            if not all_entities:
                print("\n❌ No entities extracted. Possible issues:")
                print("   - Cloudflare still blocking")
                print("   - API endpoint changed")
                print("   - Network issues")
                print("\n💡 Try running the browser console script manually instead.")
                return
            
            # Save results
            output_dir = Path('research/data/raw')
            output_dir.mkdir(parents=True, exist_ok=True)
            date_str = datetime.now().strftime('%Y-%m-%d')
            out_file = output_dir / f"epo_deeptech_complete_{date_str}.json"
            
            results = {
                "extraction_date": datetime.now().isoformat(),
                "extraction_method": "playwright_with_real_interactions",
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
            
        except Exception as e:
            print(f"\n❌ Error during extraction: {e}")
            print("\n💡 Troubleshooting:")
            print("   1. Ensure Playwright is installed: pip install playwright")
            print("   2. Install browser: playwright install chromium")
            print("   3. Try manual browser console extraction instead")
            raise
        
        finally:
            print("\n🔄 Closing browser in 5 seconds (you can inspect the page)...")
            time.sleep(5)
            browser.close()


if __name__ == "__main__":
    main()

