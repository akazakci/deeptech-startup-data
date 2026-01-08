#!/usr/bin/env python3
"""
Dealroom enrichment (import + merge).

We do NOT scrape Dealroom directly in this repo (login/ToS). Instead:
- You export a CSV from Dealroom (or receive one via an allowed workflow)
- We merge it onto our EPO companies table.

Inputs:
  - research/data/processed/companies.csv
  - a Dealroom CSV export you provide (path argument)

Output:
  - research/data/enriched/companies_with_dealroom_{YYYY-MM-DD}.csv

Matching strategy (best-effort):
  1) website domain (preferred)
  2) normalized name (fallback)

Usage:
  python3 data_collection/import_dealroom_export.py --dealroom /path/to/dealroom_export.csv
"""

import argparse
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd


def norm_name(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\\s+", " ", s).strip()
    return s


def domain(u: str):
    if not u or not isinstance(u, str):
        return None
    u = u.strip()
    if not u:
        return None
    if not re.match(r"^https?://", u, flags=re.IGNORECASE):
        u = "https://" + u
    try:
        p = urlparse(u)
        host = p.netloc.lower()
        host = host[4:] if host.startswith("www.") else host
        return host or None
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dealroom", required=True, help="Path to Dealroom CSV export")
    args = ap.parse_args()

    epo_path = Path("research/data/processed/companies.csv")
    if not epo_path.exists():
        raise SystemExit("Missing research/data/processed/companies.csv. Run: python3 research/analysis/01_data_processing.py")

    deal_path = Path(args.dealroom).expanduser()
    if not deal_path.exists():
        raise SystemExit(f"Dealroom file not found: {deal_path}")

    epo = pd.read_csv(epo_path)
    dr = pd.read_csv(deal_path)

    # Heuristics: try to find likely Dealroom columns
    dr_cols = {c.lower(): c for c in dr.columns}
    dr_name_col = dr_cols.get("name") or dr_cols.get("company") or dr_cols.get("company name")
    dr_website_col = dr_cols.get("website") or dr_cols.get("website url") or dr_cols.get("url")

    if not dr_name_col:
        raise SystemExit("Dealroom CSV must include a company name column (e.g., 'Name').")

    dr["_dr_name_norm"] = dr[dr_name_col].astype(str).map(norm_name)
    epo["_epo_name_norm"] = epo["name"].astype(str).map(norm_name)

    if dr_website_col:
        dr["_dr_domain"] = dr[dr_website_col].astype(str).map(domain)
    else:
        dr["_dr_domain"] = None

    # EPO has normalized homepage_url and raw
    epo["_epo_domain"] = epo["homepage_url"].astype(str).map(domain)
    epo["_epo_domain"] = epo["_epo_domain"].where(epo["_epo_domain"].notna(), epo["homepage_url_raw"].astype(str).map(domain))

    # Prefer domain join
    merged = epo.merge(
        dr.drop_duplicates(subset=["_dr_domain"]).copy(),
        how="left",
        left_on="_epo_domain",
        right_on="_dr_domain",
        suffixes=("", "_dealroom"),
    )

    # Fill remaining via name join (only where domain didn't match)
    need = merged[dr_name_col].isna() if dr_name_col in merged.columns else merged["_dr_name_norm"].isna()
    if need.any():
        by_name = epo.merge(
            dr.drop_duplicates(subset=["_dr_name_norm"]).copy(),
            how="left",
            left_on="_epo_name_norm",
            right_on="_dr_name_norm",
            suffixes=("", "_dealroom"),
        )
        # Replace only rows where we have no domain match
        for c in dr.columns:
            if c in merged.columns:
                merged.loc[need, c] = by_name.loc[need, c]

    out_dir = Path("research/data/enriched")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"companies_with_dealroom_{datetime.now().strftime('%Y-%m-%d')}.csv"

    # Drop internal columns
    drop_cols = [c for c in merged.columns if c.startswith("_epo_") or c.startswith("_dr_")]
    merged.drop(columns=drop_cols, inplace=True, errors="ignore")

    merged.to_csv(out_path, index=False)
    print(f"✅ Wrote: {out_path}")

    # Simple match stats
    matched = merged[dr_name_col].notna().sum() if dr_name_col in merged.columns else 0
    print(f"Matched {matched}/{len(merged)} companies to Dealroom rows (best-effort).")


if __name__ == "__main__":
    main()


