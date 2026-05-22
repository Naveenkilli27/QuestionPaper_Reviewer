# Question Paper Reviewer

Structured checks on uploaded question papers (no external API required):

1. **Step 1 — CO alignment** — For each parsed question: current CO (from text), expected CO (best match to your pasted CO lines), **MATCH** or **MISMATCH**.
2. **Step 2 — Bloom’s level** — If enabled: current level (L1–L6 / KL/BL tags in text) vs expected level (from question verbs), **MATCH** or **MISMATCH**.
3. **Step 3 — Duplicates** — Repeated questions **within** each set and **across** sets (when you upload more than one), using text similarity.
4. **Step 4 — Syllabus alignment** — If you paste syllabus lines (section 5), each question is matched to the best-fitting line by keyword overlap; **MATCH** / **MISMATCH** shows whether a line was found. Syllabus lines with no matched question are listed at the end of Step 4.

Parsing uses heuristics (regex / blocks); complex table layouts may need manual verification against the PDF/DOCX.

## Requirements

- Python 3.10+

## Setup

### Windows (PowerShell)

```powershell
cd "path\to\ai_app"
.\run_server.ps1
```

### Mac / Linux

```bash
cd "path/to/ai_app"
./run_server.sh
```

### Manual setup

```bash
python -m venv .venv
# Windows:
.venv\Scripts\pip install -r requirements.txt
# Mac/Linux:
.venv/bin/pip install -r requirements.txt

python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000** in your browser.

## How to use

1. Enter how many question paper sets (1–5)
2. Upload one PDF or DOCX per set
3. Paste course outcomes (`CO1: …`, one per line) for Step 1
4. Optionally paste syllabus units (one per line) for Step 4
5. Check “Paper tags Bloom’s / KL / BTL” if levels appear on the paper (Step 2)
6. Click **Run review**

## What you get

Only the four steps above appear in the report — no other sections.

## Supported formats

| Format | Notes |
|--------|-------|
| PDF | Text extracted — scanned/image PDFs are not supported |
| DOCX | Table and paragraph extraction |
| TXT / MD | Plain text |

## Project layout

- `app/main.py` — FastAPI routes
- `app/parser.py` — PDF/DOCX text extraction
- `app/review_engine.py` — Question splitting, CO/Bloom heuristics, duplication
- `app/structured_review.py` — Builds the four-step markdown report
- `app/ai_review.py` — Legacy Claude-based reviewer (not used by `/review` currently)
- `templates/` — HTML UI and report
- `static/` — CSS and JS
