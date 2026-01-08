# Research: European Deeptech Startup Analysis

This directory contains data, analysis code, and variable documentation for investigating the EU-US deeptech startup performance gap.

## 🎯 Research Question

**Why do European deeptech startups underperform compared to American counterparts?**

Hypotheses to test:
- Product positioning clarity
- Market strategy articulation
- University spinout structures
- Patent quality vs. commercial success
- Ecosystem connections

## 📊 Variables & Definitions

This section explains what data we collect and **why it matters** for understanding European deeptech performance.

### EPO Dataset Variables (Currently Extracted)

#### Entity Identification
| Variable | Explanation |
|----------|-------------|
| `unique_ID` | Unique identifier (e.g., "FR0283") — use this to join datasets and track entities across time. |
| `name` | Company/university name — the entity we're analyzing. |
| `role` | Entity type: "company" (startup), "school" (university), "pro" (research org) — lets us segment by organizational form and compare spinout vs independent performance. |
| `country_name` | Home country (39 EU countries covered) — enables geographic clustering and cross-country comparison of deeptech intensity. |
| `city` | City location — useful for regional ecosystems (e.g., Munich vs Berlin, Cambridge vs London). |
| `latitude`, `longitude` | Precise coordinates — enables mapping, distance calculations, and proximity to universities/hubs. |
| `homepageUrl` | Company website URL — the primary source for scraping product descriptions, positioning, and strategy signals. |
| `tagline` | Brief description (e.g., "Renewable and harvestable marine resource") — gives a first signal of positioning clarity and market focus. |

**Coverage**: All entities have complete identification data except ~2% missing city and ~17% missing tagline.

#### Patent Variables (Innovation Metrics)

**Aggregate counts** (from `applicants` endpoint — 100% coverage):
| Variable | Explanation |
|----------|-------------|
| `totalPatents` | Total patent applications filed — measures innovation output intensity; hypothesis: EU startups may file fewer patents than US peers. |
| `totalGrantedPatents` | Total patents granted — measures innovation quality/success; compare to US to see if EU patents have lower grant rates. |

**Individual patent records** (from `publications` endpoint — extracted):  
Each entity can have 0-N patents. We extract these to analyze patent *quality*, not just quantity.  
Example extract filename: `research/data/raw/epo_publications_YYYY-MM-DD.jsonl.gz` (generated locally; not committed to git).

| Field | Explanation |
|-------|-------------|
| `title` | Patent title (e.g., "BONE FIXATION DEVICE") — reveals what the technology actually does; enables LLM assessment of commercial relevance vs pure research. |
| `labels` | Technical field (e.g., "Oncology", "Energy") — shows technology focus; lets us test if EU startups are over-concentrated in certain fields vs diversified. |
| `docdb_filing_date` | When patent was filed — timing patterns reveal strategy: do EU startups file too early (research stage) or too late (after competitors)? |
| `granted` | Status: "EP granted", "Pending", "Refused / Withdrawn" — grant success rate may indicate patent quality; refused patents suggest weak IP strategy. |
| `pn` | Publication number — unique patent identifier for citation analysis (if extended). |
| `intention_to_license` | Whether entity offers to license — signals commercialization intent vs defensive patenting. |
| `applicant_orgs` | Co-applicants on the patent — reveals collaboration: EU startups often co-patent with universities, which may slow commercialization. |

**Why patent details matter**:  
Aggregate counts (`totalPatents=17`) don't tell you if those are high-quality commercial patents or low-quality research spillovers. Individual records let us score patent quality, measure technology diversity, and detect timing/collaboration patterns that may explain EU performance gaps.

#### Company Metadata (Business Characteristics)
These fields are nested in `company_info` (sourced from Dealroom/EPO partners, coverage ~85-90% for companies):

| Variable | Explanation |
|----------|-------------|
| `industries` | Industry labels (e.g., ["Health Tech", "Energy"]) — enables sector-specific analysis; test if certain industries underperform in EU vs US. |
| `growth_stage` | Lifecycle stage ("Founding", "Early Growth", "Late Growth", "Acquired", "Closed") — tracks progression; compare EU vs US advancement rates. |
| `company_status` | Operational status ("Operational", "Acquired", "Closed") — survival/exit outcomes; key performance indicator for ecosystem health. |
| `employee_count` | Employee range ("2-10", "11-50", etc.) — proxy for growth and scale; hypothesis: EU startups stay smaller longer than US peers. |
| `founded_on_dt` | Founding date (YYYY-MM-DD) — enables cohort analysis and time-to-milestone calculations (e.g., years to Series A). |

#### Ecosystem Connections (Network Position)
| Variable | Explanation |
|----------|-------------|
| `investors` | List of linked investors/institutions — reveals funding networks; test if EU startups have less VC access or more reliance on public funding. |
| `spinoutsOfUniversity` | Parent university if spun out — identifies academic origins; university spinouts may have different dynamics (more IP, less market focus). |
| `spinoutsOfPRO` | Parent research org if spun out — similar to university spinouts but from institutes like Fraunhofer; may indicate deeper tech but slower GTM. |

**Why ecosystem matters**:  
EU has strong university-industry linkages but this may create path dependencies (academic governance, slower pivots). Investor presence signals access to growth capital vs bootstrapping.

### Variables to Add via Web Scraping & LLM Analysis

These variables will be extracted from company websites and scored by LLM to measure **positioning quality** — a potential differentiator between EU and US startups.

#### Product Positioning (Website Scraping → LLM Scoring)

**Implemented pipeline (raw → structured)**:
- **Raw website captures**: `python3 data_collection/enrich_websites.py`  
  Output: `research/data/enriched/websites_raw_YYYY-MM-DD.jsonl`  
  Each company record contains a `pages` array (homepage + a few internal pages) and a `combined_text` field.
- **Positioning extraction (schema v1)**: `python3 research/analysis/03_positioning_extraction.py`  
  Output: `research/data/enriched/positioning_v1_YYYY-MM-DD.jsonl`  
  The v1 schema is versioned in code (`POSITIONING_SCHEMA_V1`) and includes both structured fields and 0..1 scores.

**Positioning schema v1 (high-level fields)**:
- `positioning_statement`, `one_liner`, `product_category`
- `target_customers`, `target_users`, `job_to_be_done`, `use_cases`, `verticals`
- `business_model` (motion, offering_type, revenue_model)
- `value_props`, `differentiators`, `proof_points`, `evidence_quotes`
- `scores`: `positioning_clarity`, `market_focus`, `commercial_readiness`, `differentiation_strength`, `technical_credibility`

#### Market Presence & Validation
| Variable | Explanation | Why It Matters |
|----------|-------------|----------------|
| `linkedin_followers` | LinkedIn follower count — proxy for market attention and brand strength; compare EU vs US for similar-stage companies. |
| `employee_count` | Current employee count (from LinkedIn/website) — growth proxy; test if EU startups scale teams slower than US equivalents. |
| `recent_news_count` | News mentions in last 12 months — media visibility may correlate with fundraising success; EU startups may have lower PR investment. |
| `partnership_announcements` | Count of announced corporate/academic partnerships — signals commercial traction; hypothesis: EU startups form partnerships but may not convert to revenue. |

#### LLM-Extracted Strategy Scores (0-1 scale)
These will be computed from website text to quantify "soft" factors that traditional reports miss:

| Variable | What LLM Evaluates | Research Hypothesis |
|----------|-------------------|---------------------|
| `positioning_clarity` | Can a reader quickly understand what the company does and who it serves? | EU startups may have weaker GTM communication due to academic origins or tech-first culture. |
| `market_focus` | Is the target market well-defined or vague/aspirational? | EU startups may target "Europe" broadly vs US startups targeting specific verticals/segments. |
| `commercial_readiness` | Do they show customer traction, case studies, or is it all R&D? | EU deeptech may stay in "development" stage longer (valley of death). |
| `competitive_differentiation` | Do they clearly articulate advantages vs alternatives? | Weak differentiation → harder fundraising → slower growth. |
| `technical_credibility` | Are technical claims credible/specific or generic/buzzwordy? | This should be an EU *strength* if messaging is effective. |

### Dealroom variables (imported, not scraped)

Dealroom (as shown in the UI screenshots) can provide variables like:
- employee range, founding date, HQ location (as listed)
- funding rounds (round, date, amount), investor names
- valuations/enterprise value (if available), “signals”/scores, tags/categories

We do **not** scrape Dealroom directly in this repository. The intended workflow is:
1) Export a Dealroom CSV through an allowed route
2) Merge it onto our EPO company table by website domain/name

See `data_collection/import_dealroom_export.py`.

## 📁 Data Organization

```
research/
├── data/
│   ├── raw/                    # Raw extracted data
│   │   └── epo_deeptech_complete_YYYY-MM-DD.json
│   ├── processed/              # Cleaned & structured data
│   │   ├── entities.csv        # Main dataset
│   │   ├── companies.csv       # Companies only
│   │   ├── universities.csv    # Universities only
│   └── enriched/               # + Web scraping & LLM analysis
│       ├── companies_enriched.csv
│       └── llm_scores.csv
│
├── analysis/                   # Analysis scripts
│   ├── 00_verify_data_integrity.py # Validate raw extract
│   └── 01_data_processing.py       # Clean & process raw data into CSV
│
├── docs/                       # Research documentation
│   ├── project_plan.md         # Overall research plan
│   ├── variable_definitions.md # Detailed variable docs
│
└── README.md                   # This file
```

## 🔬 Analysis Pipeline

### Phase 1: Data Processing (Week 1)
```bash
python3 analysis/01_data_processing.py
# Input:  data/raw/epo_deeptech_complete_*.json
# Output: data/processed/entities.csv
```

Future phases (EDA, enrichment scrapers, LLM extraction, statistical testing) will be added as new scripts under `research/analysis/` and documented here when they exist.

## 📊 Expected Analyses

1. **Descriptive Statistics**
   - Geographic distribution of deeptech
   - Patent activity by country/field
   - Funding progression patterns
   - Spinout vs. independent startups

2. **Correlation Analysis**
   - Positioning clarity ↔ Funding success
   - Patent count ↔ Commercial readiness
   - University affiliation ↔ Survival rate
   - Technical field ↔ Growth trajectory

3. **Comparative Analysis** (if US data available)
   - EU vs. US positioning clarity
   - Patent-to-commercial ratios
   - Spinout performance differences
   - Market communication patterns

4. **Predictive Modeling**
   - What predicts funding success?
   - What predicts survival/acquisition?
   - Can we identify "at-risk" startups?

## 📝 Variable Extension Protocol

When adding new variables:

1. **Document in this README**
   - Add to appropriate table above
   - Specify source, coverage, priority

2. **Update `docs/variable_definitions.md`**
   - Detailed definition
   - Collection methodology
   - Example values
   - Known limitations

3. **Add to processing scripts**
   - Update relevant analysis scripts
   - Ensure compatibility with existing pipeline

4. **Version control**
   - Note date added
   - Track which analyses use it

## 🎓 Citation & Attribution

### Data Sources
- **EPO Deep Tech Finder**: European Patent Office (https://dtf.epo.org)
- **Additional sources**: To be added as we extend dataset

### Publication Guidelines
When publishing results:
1. Cite EPO Deep Tech Finder as primary data source
2. Document extraction date (data is point-in-time)
3. Note any filtering/exclusions applied
4. Share variable definitions and methodology
5. Consider making processed data available (if legally permissible)

## 🔄 Data Updates

- **EPO Data**: Re-extract quarterly for freshness
- **Web Data**: Re-scrape annually (websites change slowly)
- **LLM Variables**: Re-compute if prompts change significantly

---

**Last Updated**: December 2025  
**Dataset Version**: 1.0  
**Total Variables**: 15 (EPO) + ~25 (planned)

