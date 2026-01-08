#!/usr/bin/env python3
"""
Step 3: Product positioning extraction from website raw captures (LLM-assisted).

Why this exists
---------------
`data_collection/enrich_websites.py` produces raw website captures:
  research/data/enriched/websites_raw_YYYY-MM-DD.jsonl

Those raw captures are useful but not analysis-ready: they are long, messy,
and heterogeneous. This script "compresses" the raw text into a stable schema of
positioning variables (category, target customer, value proposition, etc.)
using a versioned prompt.

Reproducibility
---------------
- The prompt and schema are embedded in this script and versioned via constants.
- Output records include prompt hash, model, and the raw LLM response.

Inputs
------
- research/data/enriched/websites_raw_*.jsonl

Outputs
-------
- research/data/enriched/positioning_v1_YYYY-MM-DD.jsonl
  (one JSON object per company)

Usage
-----
  # Dry-run: prints the prompt for the first record without calling any API
  python3 research/analysis/03_positioning_extraction.py --dry-run --limit 1

  # Run with OpenAI (requires OPENAI_API_KEY)
  OPENAI_API_KEY=... python3 research/analysis/03_positioning_extraction.py --limit 50
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests


PROMPT_VERSION = "positioning_v1_2026-01-06"
SCHEMA_VERSION = "v1"


POSITIONING_SCHEMA_V1: Dict[str, Any] = {
    "positioning_statement": "string. Canonical statement: For <target customer> who <need>, <company> is a <category> that <value>. Unlike <alternative>, it <differentiator>.",
    "one_liner": "string. A short plain-language description (<= 25 words).",
    "product_category": "string. The market category (e.g., 'battery materials', 'genomics platform', 'industrial robotics').",
    "target_customers": "array[string]. Buyer segments (e.g., 'hospitals', 'utilities', 'OEMs', 'pharma R&D').",
    "target_users": "array[string]. End users (if distinct from buyers).",
    "job_to_be_done": "string. The core job/problem the product solves.",
    "use_cases": "array[string]. Concrete use cases.",
    "verticals": "array[string]. Industry verticals.",
    "business_model": {
        "primary_motion": "string. One of: B2B | B2C | B2G | B2B2C | Other | Unknown",
        "offering_type": "string. One of: Software | Hardware | Biotech/Therapeutic | Materials/Chemistry | Services | Mixed | Unknown",
        "revenue_model": "string. Subscription | Usage-based | Licensing | Hardware sales | Services | R&D partnerships | Unknown",
    },
    "value_props": "array[string]. Customer-relevant benefits (not features).",
    "differentiators": "array[string]. Claimed advantages vs alternatives/competitors.",
    "proof_points": "array[string]. Evidence: named customers, deployments, trials, certifications, published metrics, etc.",
    "signals": {
        "mentions_customers": "boolean",
        "mentions_partners": "boolean",
        "mentions_pricing": "boolean",
        "mentions_case_studies": "boolean",
        "mentions_regulation_or_certification": "boolean",
    },
    "scores": {
        "positioning_clarity": "number 0..1. How quickly a neutral reader understands what it does + for whom.",
        "market_focus": "number 0..1. Specificity of target market/use case vs broad claims.",
        "commercial_readiness": "number 0..1. Presence of traction signals vs pure R&D.",
        "differentiation_strength": "number 0..1. Specificity and credibility of differentiation.",
        "technical_credibility": "number 0..1. Specific technical claims vs buzzwords.",
    },
    "rationales": {
        "positioning_clarity": "string. 1-2 sentences.",
        "market_focus": "string. 1-2 sentences.",
        "commercial_readiness": "string. 1-2 sentences.",
        "differentiation_strength": "string. 1-2 sentences.",
        "technical_credibility": "string. 1-2 sentences.",
    },
    "evidence_quotes": "array[string]. Up to 5 short quotes from the text that support the extraction.",
}


SYSTEM_PROMPT = (
    "You are a meticulous research assistant. "
    "Extract product positioning variables from a company's website text. "
    "Return ONLY valid JSON and nothing else."
)


def make_user_prompt(company_name: str, text: str) -> str:
    # Keep the prompt stable and explicit: schema + constraints.
    return f"""
Company: {company_name}

TASK
You will be given raw website text (homepage + a few internal pages).
Extract product positioning variables into a JSON object that conforms to the schema below.

IMPORTANT RULES
- Output MUST be valid JSON (no markdown, no commentary).
- If information is missing, use empty strings, empty arrays, or 'Unknown' where applicable.
- Scores MUST be numbers from 0 to 1.
- Evidence quotes MUST be short snippets copied from the provided text (not invented).
- Prefer concrete language over buzzwords.

SCHEMA (v1)
{json.dumps(POSITIONING_SCHEMA_V1, ensure_ascii=False, indent=2)}

RAW WEBSITE TEXT
{text}
""".strip()


def sha256_str(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8", errors="ignore")).hexdigest()


def latest_jsonl(pattern: str) -> Path:
    files = sorted(glob.glob(pattern))
    if not files:
        raise SystemExit(f"No files match {pattern}. Run website enrichment first.")
    return Path(max(files, key=lambda p: Path(p).stat().st_mtime))


def read_done_company_ids(out_path: Path) -> set:
    done = set()
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
            cid = obj.get("company_id")
            if cid:
                done.add(str(cid))
    return done


def call_openai_chat_completions(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    timeout: int,
) -> Tuple[str, Dict[str, Any]]:
    """
    Minimal OpenAI Chat Completions call via requests (no extra dependencies).
    Returns (content, meta) where meta includes status_code and usage if available.
    """
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        # best-effort JSON constraint (supported by many OpenAI models)
        "response_format": {"type": "json_object"},
    }
    r = requests.post(url, headers=headers, json=payload, timeout=timeout)
    meta: Dict[str, Any] = {"status_code": r.status_code}
    if not r.ok:
        meta["error_text"] = r.text[:5000]
        raise RuntimeError(f"OpenAI API error: HTTP {r.status_code}: {r.text[:200]}")
    data = r.json()
    meta["usage"] = data.get("usage")
    content = (((data.get("choices") or [{}])[0]).get("message") or {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("OpenAI response missing message.content")
    return content, meta


def normalize_input_text(text: str, max_chars: int) -> str:
    text = (text or "").strip()
    # collapse excessive whitespace but keep some structure
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{3,}", "  ", text)
    if max_chars and max_chars > 0:
        text = text[: max_chars]
    return text


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="", help="Input websites_raw JSONL (default: latest)")
    ap.add_argument("--output", default="", help="Output JSONL (default: research/data/enriched/positioning_v1_YYYY-MM-DD.jsonl)")
    ap.add_argument("--limit", type=int, default=0, help="Limit number of companies (debug/testing)")
    ap.add_argument("--resume", action="store_true", help="Skip company_ids already present in output")
    ap.add_argument("--dry-run", action="store_true", help="Print the prompt for the first record; do not call any API")

    ap.add_argument("--provider", default="openai", help="LLM provider (v1 supports: openai)")
    ap.add_argument("--model", default="gpt-4o-mini", help="Model name")
    ap.add_argument("--temperature", type=float, default=0.0, help="Sampling temperature")
    ap.add_argument("--timeout", type=int, default=60, help="HTTP timeout for provider API call (seconds)")
    ap.add_argument("--max-input-chars", type=int, default=40000, help="Max chars of website text to send to the model")
    args = ap.parse_args()

    inp = Path(args.input) if args.input else latest_jsonl("research/data/enriched/websites_raw_*.jsonl")
    if not inp.exists():
        raise SystemExit(f"Input not found: {inp}")

    out_dir = Path("research/data/enriched")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = Path(args.output) if args.output else (out_dir / f"positioning_v1_{datetime.utcnow().strftime('%Y-%m-%d')}.jsonl")

    done = read_done_company_ids(out) if args.resume else set()
    if done:
        print(f"Resume mode: skipping {len(done)} already-done companies")

    provider = (args.provider or "").strip().lower()
    if provider != "openai":
        raise SystemExit("Only --provider openai is supported in v1.")

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key and not args.dry_run:
        raise SystemExit("Missing OPENAI_API_KEY. Set it or use --dry-run.")

    prompt_stub = make_user_prompt("COMPANY_NAME", "RAW_TEXT")
    prompt_sha = sha256_str(prompt_stub.replace("COMPANY_NAME", "").replace("RAW_TEXT", ""))

    n_in = 0
    n_written = 0
    n_ok = 0
    n_err = 0

    print(f"Input:  {inp}")
    print(f"Output: {out}")

    with open(inp, "r", encoding="utf-8") as f_in, open(out, "a" if (args.resume and out.exists()) else "w", encoding="utf-8") as f_out:
        for line_no, line in enumerate(f_in, start=1):
            if not line.strip():
                continue
            n_in += 1
            if args.limit and n_in > args.limit:
                break

            obj = json.loads(line)
            company_id = str(obj.get("company_id") or "")
            company_name = obj.get("company_name") or ""

            if args.resume and company_id and company_id in done:
                continue

            combined_text = normalize_input_text(obj.get("combined_text") or "", max_chars=int(args.max_input_chars))
            if not combined_text:
                out_rec = {
                    "company_id": company_id,
                    "company_name": company_name,
                    "source_websites_file": str(inp),
                    "source_websites_line": line_no,
                    "created_at_utc": datetime.utcnow().isoformat() + "Z",
                    "ok": False,
                    "error": "No combined_text available from website capture",
                    "prompt_version": PROMPT_VERSION,
                    "schema_version": SCHEMA_VERSION,
                }
                f_out.write(json.dumps(out_rec, ensure_ascii=False) + "\n")
                n_written += 1
                n_err += 1
                continue

            user_prompt = make_user_prompt(company_name, combined_text)

            if args.dry_run:
                print("=" * 70)
                print("DRY RUN PROMPT (first record)")
                print("=" * 70)
                print(user_prompt[:12000])
                return

            try:
                content, meta = call_openai_chat_completions(
                    api_key=api_key,
                    model=args.model,
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    temperature=float(args.temperature),
                    timeout=int(args.timeout),
                )
                parsed = json.loads(content)
                out_rec = {
                    "company_id": company_id,
                    "company_name": company_name,
                    "source_websites_file": str(inp),
                    "source_websites_line": line_no,
                    "created_at_utc": datetime.utcnow().isoformat() + "Z",
                    "ok": True,
                    "extraction": parsed,
                    "llm_raw_response": content,
                    "provider": provider,
                    "model": args.model,
                    "temperature": float(args.temperature),
                    "prompt_version": PROMPT_VERSION,
                    "prompt_sha256": prompt_sha,
                    "schema_version": SCHEMA_VERSION,
                    "input_combined_text_sha256": sha256_str(combined_text),
                    "input_combined_text_char_count": len(combined_text),
                    "meta": meta,
                }
                n_ok += 1
            except Exception as e:
                out_rec = {
                    "company_id": company_id,
                    "company_name": company_name,
                    "source_websites_file": str(inp),
                    "source_websites_line": line_no,
                    "created_at_utc": datetime.utcnow().isoformat() + "Z",
                    "ok": False,
                    "error": str(e),
                    "provider": provider,
                    "model": args.model,
                    "temperature": float(args.temperature),
                    "prompt_version": PROMPT_VERSION,
                    "prompt_sha256": prompt_sha,
                    "schema_version": SCHEMA_VERSION,
                    "input_combined_text_sha256": sha256_str(combined_text),
                    "input_combined_text_char_count": len(combined_text),
                }
                n_err += 1

            f_out.write(json.dumps(out_rec, ensure_ascii=False) + "\n")
            n_written += 1

            if n_written % 10 == 0:
                print(f"  wrote {n_written} (ok={n_ok}, err={n_err})")

    print(f"✅ Done. Wrote {n_written} records (ok={n_ok}, err={n_err})")


if __name__ == "__main__":
    if not Path("research").exists():
        raise SystemExit("Run from repo root: cd /Users/oak/Documents/epo")
    main()


