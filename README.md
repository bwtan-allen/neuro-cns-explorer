# 🧠 Neuroscience CNS Publication Explorer

Tracks **corresponding-author (last-author proxy)** publications in **Cell / Nature / Science**
(and non-CNS journals) for neuroscience PIs, 2016–2025, and visualizes them in a Streamlit app.

Covers cohorts across **30+ top US institutions**:
- **HHMI** neuroscience investigators
- **Established non-HHMI** PIs (CNS ≥ 5 in 10 yrs, i.e. ≥ 0.5/yr)
- **Rising-star junior PIs** (CNS 2–4, recent lab start)
- **Early-career award winners** — Searle Scholars, Pew Biomedical Scholars, McKnight Scholars,
  Klingenstein-Simons Fellows (neuroscience) — captures rising stars *before* they accrue CNS papers

**Lab start** = ORCID faculty-appointment year when available (accurate), else first senior-author
paper year (a lagging lower bound — new PIs take ~2–3 yr to publish their first senior paper).

## Quick start
```bash
pip install -r requirements.txt
streamlit run streamlit_app.py          # opens http://localhost:8501
```

## Files
| Path | Purpose |
|------|---------|
| `streamlit_app.py` | The interactive app (table, rankings, per-researcher, CNS-vs-nonCNS, rising stars) |
| `neuro_stats.json` | Data the app reads (per-year CNS + non-CNS, career stage) |
| `refresh_data.py` | Rebuilds `neuro_stats.json` from PubMed (see below) |
| `pipeline/` | Pipeline scripts (discovery, non-CNS, enrichment, dataset builder) |
| `data/` | Cached intermediate JSON (per-institution papers, tallies) |
| `exports/hhmi_neuro_corresponding_tally.csv` | HHMI table export |
| `exports/non_hhmi_neuro_CNS_corresponding.csv` | Established non-HHMI export |
| `com.neuro.cns.refresh.plist` | macOS launchd job for monthly refresh |

## Data method (all from PubMed E-utilities, no API key required)
- **Corresponding author ≈ last author** (standard in bio; a few consortium exceptions).
- **Discovery**: per institution, neuro CNS papers → `efetch` XML → keep papers whose *last author*
  is affiliated with that institution; exclude any with "Howard Hughes"/HHMI affiliation, plus a
  name list of ~1,700 HHMI profiles.
- **Neuroscience** filter: MeSH + title terms.
- **Career stage**: first year as last author (affiliation-bounded) → lab-age proxy.
- **Collision control**: common surnames are affiliation-scoped; distinctive names use no-affiliation recall.

## Monthly auto-refresh
`refresh_data.py` re-runs discovery (fresh each month) and incrementally computes new authors:
```bash
python refresh_data.py           # incremental (recommended monthly)
python refresh_data.py --full    # also recompute all non-CNS / enrichment caches
python refresh_data.py --hhmi    # also re-run the HHMI CNS + non-CNS tallies
```

### Schedule it (macOS launchd — runs 1st of each month, 03:00)
```bash
cp com.neuro.cns.refresh.plist ~/Library/LaunchAgents/
launchctl load  ~/Library/LaunchAgents/com.neuro.cns.refresh.plist
# to run once now:      launchctl start com.neuro.cns.refresh
# to disable:           launchctl unload ~/Library/LaunchAgents/com.neuro.cns.refresh.plist
```
Logs: `data/refresh.log`, `data/refresh.err.log`.

## Host it on GitHub (auto-refresh + auto-deploy)
This repo is ready to run itself on GitHub — no local machine needed.

### 1. Scheduled data refresh (GitHub Actions)
`.github/workflows/refresh-data.yml` runs `refresh_data.py` on the **1st of every month** (and on-demand
via the Actions tab), then commits the updated `neuro_stats.json` back to the repo.
- **Recommended:** add a free [NCBI API key](https://www.ncbi.nlm.nih.gov/account/) as a repo secret
  named `NCBI_API_KEY` (Settings → Secrets and variables → Actions). This raises the PubMed limit
  from 3→10 requests/s so CI runs are faster and avoid throttling. Without it, the refresh still runs
  (just slower). The scripts read the key automatically from the `NCBI_API_KEY` env var.

### 2. Live app (Streamlit Community Cloud — free)
1. Push this folder to a GitHub repo.
2. Go to https://share.streamlit.io → **New app** → pick your repo → main file `streamlit_app.py`.
3. It deploys automatically and **redeploys whenever the repo changes** — so each monthly data commit
   from the Action updates the live app with zero manual steps.

That gives you: **Actions refreshes the data monthly → commits it → Streamlit Cloud auto-redeploys.**

## Local monthly schedule (macOS launchd — alternative to GitHub)

> Note: a full refresh issues many PubMed queries; NCBI throttles unauthenticated bursts.
> For faster/heavier runs, add a free NCBI API key (`&api_key=`) in `pipeline/*.py`.

## Caveats
- "Last author" ≈ corresponding — a few genomics/consortium PIs are corresponding without being last.
- Discovery is affiliation-based, so it may miss papers listing affiliations unusually, or people who moved.
- Name-based HHMI exclusion may over-exclude a non-HHMI person sharing a name with an HHMI scientist.
- A few non-CNS counts for very common surnames may be collision-inflated (flagged where known).
