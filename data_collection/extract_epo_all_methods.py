#!/usr/bin/env python3
"""
EPO Data Extraction - Try Multiple Methods Automatically

This script tries multiple extraction methods in order until one succeeds:
1. Playwright with real user interactions (best for Cloudflare)
2. Cloudscraper (lightweight Cloudflare bypass)
3. Falls back to manual instructions if all automated methods fail

Requirements:
    pip3 install playwright cloudscraper
    python3 -m playwright install chromium

Usage:
    python3 data_collection/extract_epo_all_methods.py
"""

import sys
from pathlib import Path


def try_playwright():
    """Try Playwright method."""
    print("\n" + "="*70)
    print("METHOD 1: Playwright with Real User Interactions")
    print("="*70)
    try:
        import sys
        from pathlib import Path
        # Add current directory to path for imports
        script_dir = Path(__file__).parent
        if str(script_dir) not in sys.path:
            sys.path.insert(0, str(script_dir))
        from extract_epo_playwright import main as playwright_main
        playwright_main()
        return True
    except ImportError as e:
        print(f"❌ Playwright not installed: {e}")
        print("   Install with: pip install playwright && playwright install chromium")
        return False
    except Exception as e:
        print(f"❌ Playwright method failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def try_cloudscraper():
    """Try cloudscraper method."""
    print("\n" + "="*70)
    print("METHOD 2: Cloudscraper (Cloudflare Bypass)")
    print("="*70)
    try:
        import sys
        from pathlib import Path
        # Add current directory to path for imports
        script_dir = Path(__file__).parent
        if str(script_dir) not in sys.path:
            sys.path.insert(0, str(script_dir))
        from extract_epo_cloudscraper import main as cloudscraper_main
        cloudscraper_main()
        return True
    except ImportError as e:
        print(f"❌ Cloudscraper not installed: {e}")
        print("   Install with: pip install cloudscraper")
        return False
    except Exception as e:
        print(f"❌ Cloudscraper method failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def show_manual_instructions():
    """Show manual extraction instructions."""
    print("\n" + "="*70)
    print("MANUAL EXTRACTION METHOD")
    print("="*70)
    print("""
Since automated methods failed, use manual browser extraction:

1. Open: data_collection/EXTRACT_NOW.html in your browser
   OR
   Navigate to: https://dtf.epo.org/datav/public/dashboard-frontend/host_epoorg.html#/explore?dataSet=1

2. Open browser Developer Tools (F12 or Cmd+Option+I)

3. Go to Console tab

4. Paste this script:

(async () => {
  const API = 'https://dtf.epo.org/datav/public/datavisualisation/api/dataset/1/applicants';
  const results = { extraction_date: new Date().toISOString(), entities: [], total: 0 };
  let token = "";
  let page = 0;

  while (true) {
    page += 1;
    console.log(`Page ${page} token="${token}"...`);
    const resp = await fetch(API, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json, text/plain, */*',
        'Origin': 'https://dtf.epo.org',
        'Referer': 'https://dtf.epo.org/datav/public/dashboard-frontend/host_epoorg.html'
      },
      body: JSON.stringify({ nextPageToken: token, filters: [] })
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    const content = data.applicants || data.content || [];
    results.entities.push(...content);
    console.log(`  got ${content.length}, total ${results.entities.length}`);
    token = data.nextPageToken || "";
    if (!token) break;
    await new Promise(r => setTimeout(r, 300));
  }

  results.total = results.entities.length;
  const blob = new Blob([JSON.stringify(results, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `epo_deeptech_complete_${new Date().toISOString().split('T')[0]}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
})();

5. Press Enter and wait for download

6. Move downloaded file to: research/data/raw/
""")


def main():
    print("="*70)
    print("EPO DATA EXTRACTION - Multi-Method Attempt")
    print("="*70)
    print("\nThis script will try multiple extraction methods until one succeeds.")
    print("Methods are tried in order of reliability.\n")
    
    # Check if data already exists
    raw_dir = Path('research/data/raw')
    if raw_dir.exists():
        existing_files = list(raw_dir.glob('epo_deeptech_complete_*.json'))
        if existing_files:
            print(f"⚠️  Found {len(existing_files)} existing extraction(s):")
            for f in existing_files:
                print(f"   - {f.name}")
            # Auto-continue in non-interactive mode (when stdin is not a TTY)
            import sys
            if sys.stdin.isatty():
                response = input("\nContinue anyway? (y/n): ")
                if response.lower() != 'y':
                    print("Aborted.")
                    return
            else:
                print("\n⚠️  Non-interactive mode: Continuing automatically...")
    
    # Try methods in order
    methods = [
        ("Playwright", try_playwright),
        ("Cloudscraper", try_cloudscraper),
    ]
    
    for method_name, method_func in methods:
        print(f"\n🔄 Attempting {method_name} method...")
        if method_func():
            print(f"\n✅ SUCCESS with {method_name} method!")
            return
    
    # All automated methods failed
    print("\n" + "="*70)
    print("❌ ALL AUTOMATED METHODS FAILED")
    print("="*70)
    show_manual_instructions()


if __name__ == "__main__":
    main()

