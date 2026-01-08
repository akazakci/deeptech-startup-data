# European Deeptech Startup Research

> Investigating the EU-US deeptech performance gap through systematic data analysis

## 🎯 Research Goal

Understand why European deeptech startups may underperform compared to American counterparts by analyzing:
- Patent activity and quality
- Company positioning and market communication  
- Ecosystem connections (universities, investors)
- Funding patterns and growth trajectories

## 📊 Dataset

**Primary Source**: EPO Deep Tech Finder  
**Coverage**: 11,270 European deeptech entities across 39 countries  
**Time Period**: Patent data 1978-2025, current business status

**Two-layer extraction**:
1. **Entity list** (11,270 companies/universities/research orgs) — includes patent *counts*, company metadata, investors
2. **Patent details** (per entity) — includes individual patent titles, technical fields, filing years, grant status

## 🗂️ Repository Structure

```
epo/
├── data_collection/          # Data extraction & scraping
│   ├── README.md            # Replication guide for data collection
│   ├── EXTRACT_NOW.html     # ⭐ Run this to get EPO data
│   └── epo_scraper/         # Alternative extraction scripts
│
├── research/                 # Analysis & research outputs
│   ├── README.md            # ⭐ Variables, sources, methodology
│   ├── data/                # All datasets
│   ├── analysis/            # Analysis scripts
│   └── docs/                # Research documentation
│
└── README.md                # This file
```

## ⚡ Quick Start

### 1. Extract EPO Data

**Option A: Automated Extraction (Recommended)**
```bash
# Install dependencies
pip3 install playwright cloudscraper
python3 -m playwright install chromium

# Run automated extraction (tries multiple methods)
python3 data_collection/extract_epo_all_methods.py
```

**Option B: Manual Browser Extraction**
```bash
open data_collection/EXTRACT_NOW.html
# Follow on-screen instructions
# Downloads ~15 MB JSON file automatically
mv ~/Downloads/epo_deeptech_complete_*.json research/data/raw/
```

The automated script uses Playwright to actually click around the UI like a human, bypassing Cloudflare protection.

### 2. Verify Integrity (Recommended)
```bash
python3 research/analysis/00_verify_data_integrity.py
```

### 3. Process to CSVs
```bash
python3 research/analysis/01_data_processing.py
```

## 📖 Documentation

- **[Data Collection Guide](data_collection/README.md)** - How to replicate data extraction
- **[Research Documentation](research/README.md)** - Variables, methods, analysis pipeline

## 🔬 Research Variables

### From EPO (Available Now)
- Entity info (name, type/role, country, city, coordinates)
- Patent totals (applications count + granted count)
- Industry labels (when present, via nested `company_info.industries`)
- Investor/spinout relations (when present, via `investors` + `spinoutsOf*`)

### To Be Added (Web Scraping + LLM)
- Company positioning clarity
- Product descriptions
- Market focus
- Technical credibility
- Employee counts
- Media presence

See [research/README.md](research/README.md) for complete variable list.

## 🎓 Academic Use

This repository enables:
1. **Replicable data collection** - Others can extract the same dataset
2. **Systematic variable extraction** - Clear definitions and methods
3. **Transparent analysis** - All code and methodology documented
4. **Extension** - Framework for adding new data sources

## 📝 Citation

When using this data/methodology:
```
European Deeptech Startup Dataset (2025)
Source: EPO Deep Tech Finder (https://dtf.epo.org)
Extraction Date: [Your extraction date]
```

## 🚀 Next Steps

1. **Extract EPO data** → `data_collection/EXTRACT_NOW.html`
2. **Review variables** → `research/README.md`
3. **Run exploratory analysis** → `research/analysis/`
4. **Add web scraping** → Extend with company websites
5. **Extract LLM variables** → Positioning clarity, etc.
6. **Analyze & publish** → Test hypotheses

---

**Status**: Data collection ready ✅ | Research in progress 🔄  
**Last Updated**: December 2025

