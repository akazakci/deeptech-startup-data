#!/usr/bin/env python3
"""
Run website enrichment in resumable batches and show overall progress.

Why this exists
---------------
Scraping ~10k company sites can take hours and is subject to transient failures.
This orchestrator runs `data_collection/enrich_websites.py` repeatedly in batches
(`--limit N` per run) using `--resume`, and shows overall progress on the terminal.

Progress display
----------------
- Uses tqdm if available (pip install tqdm)
- Falls back to simple prints if tqdm is not installed

Typical usage
-------------
  # Continue from an existing output file (recommended)
  python3 data_collection/run_website_enrichment_batches.py \\
    --output research/data/enriched/websites_raw_2026-01-06_run1.jsonl \\
    --batch-size 500 --max-pages 2

  # Start a fresh run
  python3 data_collection/run_website_enrichment_batches.py --batch-size 500 --max-pages 2

Notes
-----
This script does not do parallel scraping by default. If you want parallelism,
run multiple shards in separate terminals using `--shard-index/--shard-total`.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Optional, Set, Tuple

import pandas as pd

# Ensure timely logs even when stdout is not a TTY (e.g., piping/CI)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass


def sha256_int(s: str) -> int:
    # deterministic sharding compatible with enrich_websites.py
    import hashlib

    h = hashlib.sha256((s or "").encode("utf-8", errors="ignore")).hexdigest()
    return int(h, 16)


def shard_for_company_id(company_id: str, shard_total: int) -> int:
    shard_total = max(1, int(shard_total))
    return sha256_int(company_id) % shard_total


def load_eligible_company_ids(companies_csv: Path, shard_index: int, shard_total: int) -> Set[str]:
    df = pd.read_csv(companies_csv)
    urls = df[["id", "homepage_url", "homepage_url_raw"]].copy()
    urls["url"] = urls["homepage_url"].fillna(urls["homepage_url_raw"])
    urls = urls[urls["url"].notna()].copy()

    urls["id"] = urls["id"].astype(str)
    urls = urls.sort_values(by=["id"], kind="mergesort")

    shard_total = max(1, int(shard_total))
    shard_index = int(shard_index)
    if shard_index < 0 or shard_index >= shard_total:
        raise SystemExit(f"Invalid shard: --shard-index must be in [0, {shard_total - 1}]")

    if shard_total > 1:
        urls = urls[urls["id"].map(lambda cid: shard_for_company_id(cid, shard_total) == shard_index)]

    return set(urls["id"].tolist())


def read_done_company_ids(out_path: Path) -> Set[str]:
    done: Set[str] = set()
    if not out_path.exists():
        return done
    with open(out_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            cid = obj.get("company_id") or obj.get("id")
            if cid is not None:
                done.add(str(cid))
    return done


def read_company_ids_file(path: Path) -> Set[str]:
    ids: Set[str] = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = (line or "").strip()
            if not line:
                continue
            ids.add(str(line))
    return ids


def get_tqdm():
    try:
        from tqdm import tqdm  # type: ignore

        return tqdm
    except Exception:
        return None


def run_one_batch(
    *,
    out_path: Path,
    batch_limit: int,
    enrich_script: Path,
    args_passthrough: Dict[str, str],
    on_progress: Optional[callable] = None,
) -> Tuple[int, int]:
    """
    Run one batch and stream logs.
    Returns: (written_count, ok_company_count_estimate)
    """
    cmd = [
        sys.executable,
        "-u",
        str(enrich_script),
        "--resume",
        "--limit",
        str(int(batch_limit)),
        "--output",
        str(out_path),
    ]
    # append passthrough args
    for k, v in args_passthrough.items():
        if v is None:
            continue
        cmd.extend([k, str(v)])

    print(f"\n--- Running batch (limit={batch_limit}) ---")
    print(" ".join(cmd))

    written = 0
    ok_companies = 0
    last_written_seen = 0

    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    assert p.stdout is not None
    for line in p.stdout:
        line = line.rstrip("\n")
        # Print logs; if tqdm is used, the caller can provide a wrapper that uses tqdm.write
        print(line)
        # Example lines:
        #   wrote 25 records (scanned 63/10217)
        # ✅ Done. Wrote 500 companies (397 with >=1 successful page).
        if line.startswith("  wrote ") and " records" in line:
            try:
                written = int(line.split("  wrote ", 1)[1].split(" records", 1)[0].strip())
            except Exception:
                pass
            if on_progress is not None and written > last_written_seen:
                try:
                    on_progress(written - last_written_seen)
                except Exception:
                    pass
                last_written_seen = written
        if "✅ Done. Wrote " in line and " companies" in line:
            try:
                tail = line.split("✅ Done. Wrote ", 1)[1]
                written = int(tail.split(" companies", 1)[0].strip())
            except Exception:
                pass
            if on_progress is not None and written > last_written_seen:
                try:
                    on_progress(written - last_written_seen)
                except Exception:
                    pass
                last_written_seen = written
            try:
                # "(397 with >=1 successful page)."
                if "(" in line and "with >=1 successful page" in line:
                    inside = line.split("(", 1)[1].split("with", 1)[0].strip()
                    ok_companies = int(inside)
            except Exception:
                pass

    rc = p.wait()
    if rc != 0:
        raise RuntimeError(f"Batch failed with exit code {rc}")
    return written, ok_companies


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="", help="Output JSONL to append to (default: websites_raw_YYYY-MM-DD.jsonl)")
    ap.add_argument("--batch-size", type=int, default=500, help="Companies to write per batch")
    ap.add_argument("--sleep-between-batches", type=float, default=5.0, help="Seconds to wait between batches")
    ap.add_argument("--max-batches", type=int, default=0, help="Stop after N batches (0 = no limit)")
    ap.add_argument("--company-ids-file", default="", help="Optional newline-delimited company_id list to restrict this run")
    ap.add_argument(
        "--company-ids-order",
        default="sorted",
        choices=["sorted", "file", "sha256"],
        help="When --company-ids-file is used, choose iteration order: sorted (default), file order, or sha256(id) order.",
    )

    # pass-through controls to enrich_websites.py
    ap.add_argument("--max-pages", type=int, default=2, help="Max pages per company (homepage + internal pages)")
    ap.add_argument("--timeout", type=int, default=20, help="HTTP timeout seconds")
    ap.add_argument("--retries", type=int, default=3, help="Max fetch attempts per page")
    ap.add_argument("--sleep", type=float, default=0.4, help="Base delay between requests (seconds)")
    ap.add_argument("--domain-delay", type=float, default=1.0, help="Min delay between requests to same domain (seconds)")
    ap.add_argument("--jitter", type=float, default=0.2, help="Random jitter (seconds)")
    ap.add_argument("--max-bytes", type=int, default=2_000_000, help="Max bytes per response")
    ap.add_argument("--max-text-chars", type=int, default=60000, help="Max extracted text chars per page")
    ap.add_argument("--max-combined-chars", type=int, default=180000, help="Max combined text chars per company")
    ap.add_argument("--max-runtime-minutes", type=float, default=0.0, help="Time-box each batch run (0 = no limit)")
    ap.add_argument("--shard-index", type=int, default=0, help="Shard index (0-based)")
    ap.add_argument("--shard-total", type=int, default=1, help="Total shards")
    args = ap.parse_args()

    repo_root = Path(".")
    if not (repo_root / "research").exists():
        raise SystemExit("Run from repo root: cd /Users/oak/Documents/epo")

    enrich_script = repo_root / "data_collection" / "enrich_websites.py"
    if not enrich_script.exists():
        raise SystemExit(f"Missing script: {enrich_script}")

    out_dir = repo_root / "research" / "data" / "enriched"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.output) if args.output else (out_dir / f"websites_raw_{datetime.utcnow().strftime('%Y-%m-%d')}.jsonl")

    companies_csv = repo_root / "research" / "data" / "processed" / "companies.csv"
    if not companies_csv.exists():
        raise SystemExit("Missing research/data/processed/companies.csv. Run: python3 research/analysis/01_data_processing.py")

    eligible_ids = load_eligible_company_ids(companies_csv, args.shard_index, args.shard_total)
    if args.company_ids_file:
        ids_path = Path(str(args.company_ids_file)).expanduser()
        if not ids_path.exists():
            raise SystemExit(f"Missing --company-ids-file: {ids_path}")
        requested = read_company_ids_file(ids_path)
        eligible_ids = eligible_ids.intersection(requested)
    done_ids = read_done_company_ids(out_path)
    done_in_shard = eligible_ids.intersection(done_ids)

    total = len(eligible_ids)
    done = len(done_in_shard)

    print("=" * 70)
    print("WEBSITE ENRICHMENT - BATCH ORCHESTRATOR")
    print("=" * 70)
    if args.shard_total > 1:
        print(f"Shard: {args.shard_index}/{args.shard_total} (deterministic by company_id hash)")
    print(f"Eligible companies (this run): {total}")
    print(f"Already done (in output):      {done}")
    print(f"Remaining:                     {total - done}")
    print(f"Output:                        {out_path}")
    print(f"Batch size:                    {args.batch_size}")
    print()

    tqdm = get_tqdm()
    pbar = None
    if tqdm is not None:
        pbar = tqdm(total=total, initial=done, desc="websites_raw", unit="company")

    passthrough = {
        "--max-pages": str(args.max_pages),
        "--timeout": str(args.timeout),
        "--retries": str(args.retries),
        "--sleep": str(args.sleep),
        "--domain-delay": str(args.domain_delay),
        "--jitter": str(args.jitter),
        "--max-bytes": str(args.max_bytes),
        "--max-text-chars": str(args.max_text_chars),
        "--max-combined-chars": str(args.max_combined_chars),
        "--max-runtime-minutes": str(args.max_runtime_minutes),
        "--shard-index": str(args.shard_index),
        "--shard-total": str(args.shard_total),
        "--company-ids-file": str(args.company_ids_file) if args.company_ids_file else None,
        "--company-ids-order": str(args.company_ids_order) if args.company_ids_file else None,
    }

    batch_num = 0
    try:
        while True:
            done_ids = read_done_company_ids(out_path)
            done_in_shard = eligible_ids.intersection(done_ids)
            done = len(done_in_shard)
            remaining = total - done
            if remaining <= 0:
                break

            batch_num += 1
            if args.max_batches and args.max_batches > 0 and batch_num > int(args.max_batches):
                print(f"Stopping: reached --max-batches={args.max_batches}")
                break

            batch_limit = min(int(args.batch_size), remaining)
            before_done = done

            def _on_progress(delta: int) -> None:
                if pbar is not None and delta > 0:
                    pbar.update(int(delta))

            written, ok_companies = run_one_batch(
                out_path=out_path,
                batch_limit=batch_limit,
                enrich_script=enrich_script,
                args_passthrough=passthrough,
                on_progress=_on_progress if pbar is not None else None,
            )

            # Recompute truth from file (resume-safe)
            done_ids = read_done_company_ids(out_path)
            done_in_shard = eligible_ids.intersection(done_ids)
            done = len(done_in_shard)
            delta = max(0, done - before_done)

            # Correct tqdm position to ground truth (in case of partial writes / interruptions)
            if pbar is not None and pbar.n != done:
                pbar.update(done - pbar.n)
            print(
                f"Batch {batch_num} complete: wrote≈{written}, ok_companies≈{ok_companies}. "
                f"Overall: {done}/{total} ({(100.0*done/total):.1f}%)"
            )

            if args.sleep_between_batches and args.sleep_between_batches > 0:
                time.sleep(float(args.sleep_between_batches))
    finally:
        if pbar is not None:
            pbar.close()

    print("\n✅ Orchestrator finished.")
    print(f"Output: {out_path}")


if __name__ == "__main__":
    main()


