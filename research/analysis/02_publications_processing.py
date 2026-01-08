#!/usr/bin/env python3
"""
Step 2: Process EPO patent/publication rows into a flat table.

Input:
  research/data/raw/epo_publications_*.jsonl OR research/data/raw/epo_publications_*.jsonl.gz

Output:
  research/data/processed/publications.csv

Notes:
  - One row per publication record (patent application/publication entry).
  - Keeps org_id so you can join with research/data/processed/companies.csv on id.
"""

import csv
import gzip
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional


_PUB_RE = re.compile(r"^epo_publications_(\d{4}-\d{2}-\d{2})\.jsonl(?:\.gz)?$")


def _parse_pub_date(p: Path) -> Optional[datetime]:
    m = _PUB_RE.match(p.name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d")
    except Exception:
        return None


def latest_publications_file() -> Path:
    raw_dir = Path("research/data/raw")
    candidates = list(raw_dir.glob("epo_publications_*.jsonl")) + list(raw_dir.glob("epo_publications_*.jsonl.gz"))
    if not candidates:
        raise SystemExit("No files match research/data/raw/epo_publications_*.jsonl(.gz). Run publications extraction first.")

    dated = [(d, p) for p in candidates if (d := _parse_pub_date(p)) is not None]
    if dated:
        return max(dated, key=lambda t: t[0])[1]

    # Fallback: pick newest by mtime (useful locally if naming is unexpected)
    return max(candidates, key=lambda p: p.stat().st_mtime)


def open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return open(path, "r", encoding="utf-8")


def main():
    inp = latest_publications_file()
    out_dir = Path("research/data/processed")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "publications.csv"

    # Define stable columns (subset of what we saw in the response)
    fieldnames = [
        "org_id",
        "org_name",
        "org_role",
        "pn",
        "docn",
        "appn_key",
        "title",
        "labels",
        "label",
        "granted",
        "docdb_filing_date",
        "docdb_filing_office",
        "pub_date",
        "family_fn",
        "family_earliest_pub_date",
        "family_earliest_filing_date",
        "intention_to_license",
        "ipf",
    ]

    def to_str(x):
        if x is None:
            return ""
        return str(x)

    rows_written = 0
    orgs_seen = 0
    with open_text(inp) as f_in, open(out, "w", encoding="utf-8", newline="") as f_out:
        w = csv.DictWriter(f_out, fieldnames=fieldnames)
        w.writeheader()

        for line in f_in:
            if not line.strip():
                continue
            obj = json.loads(line)
            org_id = to_str(obj.get("org_id"))
            org_name = obj.get("name")
            org_role = obj.get("role")
            orgs_seen += 1 if org_id else 0

            if obj.get("error"):
                continue

            pubs = obj.get("publications") or []
            for p in pubs:
                fam = p.get("family") or {}
                office = p.get("docdb_filing_office") or {}
                w.writerow(
                    {
                        "org_id": org_id,
                        "org_name": org_name or "",
                        "org_role": org_role or "",
                        "pn": to_str(p.get("pn")),
                        "docn": to_str(p.get("docn")),
                        "appn_key": to_str(p.get("appn_key")),
                        "title": (p.get("title") or "").strip(),
                        "labels": "|".join(p.get("labels") or []) if isinstance(p.get("labels"), list) else "",
                        "label": to_str(p.get("label")),
                        "granted": to_str(p.get("granted")),
                        "docdb_filing_date": to_str(p.get("docdb_filing_date")),
                        "docdb_filing_office": to_str(office.get("filing_office") or office.get("filing_office_name")),
                        "pub_date": to_str(p.get("pub_date")),
                        "family_fn": to_str(fam.get("fn")),
                        "family_earliest_pub_date": to_str(fam.get("fn_earliest_pub_date")),
                        "family_earliest_filing_date": to_str(fam.get("fn_earliest_appn_fil_date")),
                        "intention_to_license": to_str(p.get("intention_to_license")),
                        "ipf": to_str(p.get("ipf")),
                    }
                )
                rows_written += 1

    print(f"📖 Input: {inp}")
    print(f"💾 Output: {out}")
    print(f"✅ Rows written: {rows_written:,}")


if __name__ == "__main__":
    # run from repo root
    if not Path("research").exists():
        raise SystemExit("Run from repo root: cd /Users/oak/Documents/epo")
    main()


