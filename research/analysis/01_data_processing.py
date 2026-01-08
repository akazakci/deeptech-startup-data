"""
Step 1: Process Raw EPO Data

Converts raw EPO JSON into structured CSV files for analysis.

Input:  research/data/raw/epo_deeptech_complete_*.json
Output: research/data/processed/*.csv
"""

import json
import pandas as pd
from pathlib import Path
import sys
import re
from urllib.parse import urlparse


def load_raw_data():
    """Load the most recent EPO extraction file."""
    raw_dir = Path('research/data/raw')
    
    # Find most recent extraction file
    files = list(raw_dir.glob('epo_deeptech_complete_*.json'))
    if not files:
        print("❌ No EPO data found in research/data/raw/")
        print("   Run data_collection/EXTRACT_NOW.html first to get data")
        sys.exit(1)
    
    latest_file = max(files, key=lambda p: p.stat().st_mtime)
    print(f"📖 Loading: {latest_file.name}")
    
    with open(latest_file, 'r') as f:
        data = json.load(f)
    
    return data


def flatten_entity(entity):
    """Convert nested entity JSON to flat dictionary for CSV."""
    # Map actual EPO field names to our standardized names
    def normalize_url(u: str):
        if not u:
            return None
        u = str(u).strip()
        if not u:
            return None
        # Already has scheme
        if re.match(r"^https?://", u, flags=re.IGNORECASE):
            return u
        # Handle bare domains like 'www.example.com' or 'example.com'
        # Prefer https; downstream can still choose to validate/rewrite.
        return "https://" + u

    investors = entity.get('investors', [])
    if investors is None:
        investors = []
    if not isinstance(investors, list):
        # Defensive: if API ever changes, keep a JSON string
        investors_json = json.dumps(investors, ensure_ascii=False)
        investors = []
    else:
        investors_json = json.dumps(investors, ensure_ascii=False) if investors else None

    investor_ids = []
    investor_names = []
    for inv in investors:
        if isinstance(inv, dict):
            if inv.get('id') is not None:
                investor_ids.append(str(inv.get('id')))
            if inv.get('name') is not None:
                investor_names.append(str(inv.get('name')))

    industries = entity.get('company_info', {}).get('industries', [])
    if industries is None:
        industries = []
    if not isinstance(industries, list):
        industries = []

    flat = {
        # Identification (EPO uses unique_ID, role, country_name)
        'id': entity.get('unique_ID'),
        'name': entity.get('name'),
        'type': entity.get('role'),  # EPO uses 'role' not 'type'
        'country': entity.get('country_name'),  # EPO uses 'country_name'
        'city': entity.get('city'),
        'homepage_url': normalize_url(entity.get('homepageUrl')),
        'homepage_url_raw': entity.get('homepageUrl'),
        'tagline': entity.get('tagline'),
        
        # Location
        'latitude': entity.get('latitude'),
        'longitude': entity.get('longitude'),
        
        # Patents (EPO uses totalPatents, totalGrantedPatents)
        'patent_applications': entity.get('totalPatents', 0),
        'patent_grants': entity.get('totalGrantedPatents', 0),
        
        # Extract from company_info
        'industries': industries,
        'company_status': entity.get('company_info', {}).get('company_status'),
        'growth_stage': entity.get('company_info', {}).get('growth_stage'),
        'employee_count': entity.get('company_info', {}).get('employee_count'),
        'founded_date': entity.get('company_info', {}).get('founded_on_dt'),
        
        # Extract from school_info
        'total_students': entity.get('school_info', {}).get('total_students'),
        'total_academic_personnel': entity.get('school_info', {}).get('total_academic_personnel'),
        'total_phd_students': entity.get('school_info', {}).get('total_phd_students'),
        
        # Extract from pro_info
        'pro_total_personnel': entity.get('pro_info', {}).get('total_personnel'),
        
        # Relationships
        'investors_json': investors_json,
        'investor_ids': '|'.join(investor_ids) if investor_ids else None,
        'investor_names': '|'.join(investor_names) if investor_names else None,
        'spinouts_of_university': entity.get('spinoutsOfUniversity', []),
        'spinouts_of_pro': entity.get('spinoutsOfPRO'),
    }
    
    # Compute derived variables
    if flat['patent_applications'] and flat['patent_applications'] > 0:
        flat['patent_grant_rate'] = flat['patent_grants'] / flat['patent_applications']
    else:
        flat['patent_grant_rate'] = None
    
    # Handle arrays - convert to pipe-separated strings
    industries = flat.get('industries', [])
    flat['industries_str'] = '|'.join(industries) if industries else None
    flat['industry_count'] = len(industries)
    
    flat['investor_count'] = len(investors)
    flat['has_investors'] = len(investors) > 0
    
    spinouts_uni = flat.get('spinouts_of_university', [])
    flat['spinouts_uni_count'] = len(spinouts_uni) if isinstance(spinouts_uni, list) else 0
    flat['is_university'] = flat['type'] == 'school'
    flat['is_company'] = flat['type'] == 'company'
    flat['is_pro'] = flat['type'] == 'pro'
    
    # Check if spinout
    flat['is_spinout'] = (flat['spinouts_uni_count'] > 0) or (flat.get('spinouts_of_pro') is not None)
    
    return flat


def process_data(data):
    """Process raw data into structured datasets."""
    
    print("\n" + "="*60)
    print("PROCESSING EPO DATA")
    print("="*60)
    
    # Extract entities
    if 'entities' in data:
        entities = data['entities']
    elif isinstance(data, list):
        entities = data
    else:
        raise ValueError("Unknown data structure")
    
    print(f"\nTotal entities: {len(entities)}")
    
    # Convert to DataFrame
    print("\n📊 Converting to structured format...")
    df_all = pd.DataFrame([flatten_entity(e) for e in entities])
    
    # Split by type (EPO uses 'role' field, but we mapped it to 'type')
    df_companies = df_all[df_all['type'] == 'company'].copy()
    df_universities = df_all[df_all['type'] == 'school'].copy()
    df_research = df_all[df_all['type'] == 'pro'].copy()
    
    print(f"   • Companies: {len(df_companies)}")
    print(f"   • Universities: {len(df_universities)}")
    print(f"   • Research Orgs: {len(df_research)}")
    
    # Create output directory
    output_dir = Path('research/data/processed')
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save CSV files
    print("\n💾 Saving CSV files...")
    
    df_all.to_csv(output_dir / 'entities.csv', index=False)
    print(f"   ✓ entities.csv ({len(df_all)} rows)")
    
    df_companies.to_csv(output_dir / 'companies.csv', index=False)
    print(f"   ✓ companies.csv ({len(df_companies)} rows)")
    
    df_universities.to_csv(output_dir / 'universities.csv', index=False)
    print(f"   ✓ universities.csv ({len(df_universities)} rows)")
    
    df_research.to_csv(output_dir / 'research_orgs.csv', index=False)
    print(f"   ✓ research_orgs.csv ({len(df_research)} rows)")
    
    # Generate summary statistics
    print("\n" + "="*60)
    print("SUMMARY STATISTICS")
    print("="*60)
    
    print("\n📍 Top 10 Countries:")
    print(df_all['country'].value_counts().head(10))
    
    print("\n🏭 Industries:")
    # Industries is a list, so we need to flatten it
    all_industries = []
    for industries_list in df_all['industries']:
        if isinstance(industries_list, list):
            all_industries.extend(industries_list)
    if all_industries:
        from collections import Counter
        industry_counts = Counter(all_industries)
        for industry, count in industry_counts.most_common(10):
            print(f"   {industry}: {count}")
    else:
        print("   (No industry data)")
    
    print("\n📄 Patent Statistics:")
    print(f"   Total applications: {df_all['patent_applications'].sum():,}")
    print(f"   Total grants: {df_all['patent_grants'].sum():,}")
    print(f"   Average per entity: {df_all['patent_applications'].mean():.1f}")
    print(f"   Median per entity: {df_all['patent_applications'].median():.0f}")
    
    print("\n💰 Investors:")
    print(f"   Entities with investors: {df_all['has_investors'].sum():,} ({df_all['has_investors'].mean()*100:.1f}%)")
    print(f"   Average investors per entity: {df_all['investor_count'].mean():.1f}")
    print(f"   Max investors: {df_all['investor_count'].max()}")
    
    print("\n🎓 Spinouts:")
    spinout_count = df_all['is_spinout'].sum()
    spinout_pct = (spinout_count / len(df_all)) * 100
    print(f"   Total spinouts: {spinout_count:,} ({spinout_pct:.1f}%)")
    
    print("\n" + "="*60)
    print("✅ PROCESSING COMPLETE")
    print("="*60)
    print(f"\nOutput: research/data/processed/")
    print("\nNext steps:")
    print("  1. Explore data: open research/data/processed/companies.csv")
    print("  2. Verify integrity: python3 research/analysis/00_verify_data_integrity.py")
    print("  3. Build new analyses in research/analysis/ (EDA, modeling, enrichment)")
    
    return df_all, df_companies, df_universities, df_research


def main():
    """Main processing pipeline."""
    data = load_raw_data()
    process_data(data)


if __name__ == "__main__":
    # Check if running from correct directory
    if not Path('research').exists():
        print("❌ Please run from project root directory:")
        print("   cd /Users/oak/Documents/epo")
        print("   python research/analysis/01_data_processing.py")
        sys.exit(1)
    
    main()

