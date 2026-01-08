#!/usr/bin/env python3
"""
Data Integrity Verification Script

Verifies the extracted EPO dataset for completeness and quality.
Run this after extraction to ensure data integrity.

Usage:
    python research/analysis/00_verify_data_integrity.py
"""

import json
from pathlib import Path
from collections import Counter
from datetime import datetime


def verify_integrity(json_file):
    """Verify data integrity of extracted JSON file."""
    
    print("="*70)
    print("EPO DATA INTEGRITY VERIFICATION")
    print("="*70)
    print()
    
    # Load data
    with open(json_file, 'r') as f:
        data = json.load(f)
    
    entities = data.get('entities', [])
    total_expected = data.get('total', len(entities))
    
    # 1. Basic completeness
    print("1. EXTRACTION COMPLETENESS")
    print("-" * 70)
    print(f"   Entities extracted: {len(entities):,}")
    print(f"   Expected: {total_expected:,}")
    completeness_ok = len(entities) == total_expected
    print(f"   Status: {'✅ COMPLETE' if completeness_ok else '❌ INCOMPLETE'}")
    print()
    
    # 2. Entity types
    print("2. ENTITY TYPE DISTRIBUTION")
    print("-" * 70)
    roles = Counter(e.get('role') for e in entities)
    for role, count in sorted(roles.items(), key=lambda x: -x[1]):
        pct = (count / len(entities)) * 100
        print(f"   {role:15s}: {count:5,} ({pct:5.1f}%)")
    print()
    
    # 3. Critical fields
    print("3. CRITICAL FIELDS")
    print("-" * 70)
    critical_fields = {
        'name': 'Name',
        'unique_ID': 'Unique ID',
        'role': 'Role/Type',
        'totalPatents': 'Total Patents',
        'totalGrantedPatents': 'Granted Patents',
        'city': 'City',
        'country_name': 'Country',
        'latitude': 'Latitude',
        'longitude': 'Longitude'
    }
    
    issues = []
    for field, label in critical_fields.items():
        if field in ['latitude', 'longitude']:
            present = sum(1 for e in entities 
                         if e.get(field) is not None 
                         and isinstance(e.get(field), (int, float)))
        else:
            present = sum(1 for e in entities 
                         if e.get(field) is not None 
                         and e.get(field) != "")
        
        pct = (present / len(entities)) * 100
        status = "✅" if pct >= 95 else "⚠️" if pct >= 50 else "❌"
        print(f"   {status} {label:20s}: {pct:5.1f}% complete")
        
        if pct < 95:
            issues.append(f"{label} only {pct:.1f}% complete")
    print()
    
    # 4. Data quality
    print("4. DATA QUALITY CHECKS")
    print("-" * 70)
    
    # Duplicate IDs
    ids = [e.get('unique_ID') for e in entities if e.get('unique_ID')]
    unique_ids = set(ids)
    if len(ids) != len(unique_ids):
        print(f"   ❌ Duplicate IDs: {len(ids) - len(unique_ids)} duplicates")
        issues.append(f"{len(ids) - len(unique_ids)} duplicate IDs")
    else:
        print(f"   ✅ No duplicate IDs")
    
    # Patent logic
    invalid_patents = sum(1 for e in entities 
                         if e.get('totalGrantedPatents', 0) > e.get('totalPatents', 0))
    if invalid_patents > 0:
        print(f"   ⚠️  Invalid patent counts: {invalid_patents} entities")
        issues.append(f"{invalid_patents} entities with invalid patent counts")
    else:
        print(f"   ✅ Patent counts are valid")
    
    # Coordinates
    has_coords = sum(1 for e in entities 
                    if e.get('latitude') is not None 
                    and e.get('longitude') is not None)
    print(f"   ✅ {has_coords:,} entities have coordinates ({has_coords/len(entities)*100:.1f}%)")
    print()
    
    # 5. Optional fields (nulls are expected)
    print("5. OPTIONAL FIELDS (NULLs are EXPECTED)")
    print("-" * 70)
    optional_fields = ['tagline', 'homepageUrl', 'spinoutsOfUniversity', 
                      'spinoutsOfPRO', 'investors']
    
    for field in optional_fields:
        nulls = sum(1 for e in entities 
                   if e.get(field) is None 
                   or e.get(field) == [] 
                   or e.get(field) == "")
        pct_null = (nulls / len(entities)) * 100
        present = len(entities) - nulls
        print(f"   {field:25s}: {present:5,} present ({100-pct_null:5.1f}%), "
              f"{nulls:5,} null ({pct_null:5.1f}%)")
    print()
    
    # 6. Summary
    print("="*70)
    print("VERIFICATION SUMMARY")
    print("="*70)
    
    if completeness_ok and len(issues) == 0:
        print("✅ DATA INTEGRITY: EXCELLENT")
        print("   All checks passed. Data is complete and valid.")
    elif completeness_ok:
        print("⚠️  DATA INTEGRITY: GOOD (with minor issues)")
        print("   Extraction complete, but some quality issues found:")
        for issue in issues:
            print(f"   - {issue}")
    else:
        print("❌ DATA INTEGRITY: ISSUES FOUND")
        print("   Please review the issues above.")
    
    print()
    print("Note: NULL values in optional fields (tagline, spinouts, etc.)")
    print("      are EXPECTED and indicate missing data in the EPO source,")
    print("      not extraction errors.")
    
    return len(issues) == 0 and completeness_ok


if __name__ == "__main__":
    # Find latest extraction file
    raw_dir = Path('research/data/raw')
    json_files = list(raw_dir.glob('epo_deeptech_complete_*.json'))
    
    if not json_files:
        print("❌ No extraction files found in research/data/raw/")
        exit(1)
    
    # Use most recent
    latest_file = max(json_files, key=lambda p: p.stat().st_mtime)
    print(f"Verifying: {latest_file.name}\n")
    
    success = verify_integrity(latest_file)
    exit(0 if success else 1)

