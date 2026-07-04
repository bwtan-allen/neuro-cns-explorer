#!/usr/bin/env python3
"""
Monthly data refresh for the Neuroscience CNS Publication Explorer.

Pipeline (all PubMed-based, resumable):
  1. Discovery  : neuro CNS last-author papers per institution  -> data/disc_*.json
  2. Aggregate  : non-HHMI established (CNS>=5) + rising (CNS 2-4)
  3. non-CNS    : established candidates                         -> data/cand_noncns.json
  4. Enrich     : rising candidates (first-PI year + non-CNS)    -> data/enrich.json
  5. (optional) : refresh HHMI PubMed tallies with --hhmi
  6. Build      : assemble                                       -> neuro_stats.json

Usage:
  python refresh_data.py            # incremental monthly refresh (recommended)
  python refresh_data.py --full     # also clear non-CNS/enrich caches and recompute all
  python refresh_data.py --hhmi     # also re-run HHMI CNS + non-CNS tallies

Caches are keyed by author name, so incremental runs only query newly-appearing people.
"""
import os, sys, glob, json, subprocess, unicodedata
from collections import defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.join(ROOT, "pipeline")
DATA = os.path.join(ROOT, "data")
sys.path.insert(0, PIPE)
os.makedirs(DATA, exist_ok=True)

FULL = "--full" in sys.argv
HHMI = "--hhmi" in sys.argv
ALLYRS = set(range(2016, 2026))


def log(msg):
    print(f"[refresh] {msg}", flush=True)


def run(script, *args):
    subprocess.run([sys.executable, os.path.join(PIPE, script), *args], cwd=DATA, check=False)


def norm(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))


# ---------- 1. Discovery ----------
import discover  # noqa: E402  (provides INST)
# Always refresh discovery (new papers appear monthly); name-keyed caches stay incremental.
for fn in glob.glob(os.path.join(DATA, "disc_*.json")):
    os.remove(fn)
for inst in discover.INST:
    fn = os.path.join(DATA, f"disc_{inst.replace(' ', '_')}.json")
    if os.path.exists(fn):
        continue
    log(f"discovery: {inst}")
    run("discover.py", inst)

# ---------- 2. Aggregate established + rising ----------
log("aggregating candidates")
hhmi_ex = set(json.load(open(os.path.join(DATA, "hhmi_exclude.json"))))
recs = defaultdict(lambda: {"pmids": set(), "yrs": [], "insts": set(), "aff": "", "name": ""})
for fn in glob.glob(os.path.join(DATA, "disc_*.json")):
    for x in json.load(open(fn)):
        if not x["neuro"]:
            continue
        if f"{x['ln']} {x['ini'].lower()}" in hhmi_ex:
            continue
        r = recs[(x["ln"], x["ini"])]
        if x["pmid"] in r["pmids"]:
            continue
        r["pmids"].add(x["pmid"]); r["yrs"].append(x["yr"]); r["insts"].add(x["inst"])
        r["aff"] = r["aff"] or x["aff"]; r["name"] = x["name"]

established, rising = [], []
for (ln, ini), r in recs.items():
    n = len(r["pmids"]); ys = sorted(set(r["yrs"]))
    row = {"ln": ln, "ini": ini, "name": r["name"], "cns": n, "cns_yrs": len(ys),
           "cns_years": ys, "cns_gaps": sorted(ALLYRS - set(ys)), "insts": sorted(r["insts"]), "aff": r["aff"]}
    if n >= 5:
        established.append(row)
    elif n >= 2:
        rising.append(row)
established.sort(key=lambda x: -x["cns"]); rising.sort(key=lambda x: -x["cns"])
json.dump(established, open(os.path.join(DATA, "candidates2.json"), "w"))
json.dump(rising, open(os.path.join(DATA, "rising_base.json"), "w"))
log(f"established={len(established)}  rising={len(rising)}")

# ---------- 3 & 4. non-CNS (established) + enrich (rising) ----------
if FULL:
    for c in ["cand_noncns.json", "enrich.json"]:
        p = os.path.join(DATA, c)
        if os.path.exists(p):
            os.remove(p)
log("non-CNS for established candidates")
run("cand_noncns.py")
log("enriching rising candidates (career stage + non-CNS)")
run("enrich.py")

# ---------- 5. Lab-start (ORCID + full names) for rising candidates ----------
log("ORCID appointment year + full names for rising candidates")
run("orcid_start.py")

# ---------- 6. Awards: compile list + enrich awardees ----------
log("compiling awards.json (Searle / Pew / McKnight / Klingenstein-Simons)")
run("build_awards.py")
log("enriching award recipients (pub-stats + career)")
run("awards_ingest.py")

# ---------- 7b. Field-tier journals (Neuron/Nat Neurosci) + eLife ----------
# needs a first-pass neuro_stats.json to know the roster; build once then enrich then rebuild
run("build_dataset.py", ".", os.path.join(ROOT, "neuro_stats.json"))
log("counting Neuron / Nature Neuroscience / eLife last-author papers")
run("field_journals.py")

# ---------- 7. Optional HHMI tally refresh ----------
if HHMI:
    log("refreshing HHMI CNS + non-CNS tallies")
    run("pm_all2.py")
    run("noncns_all.py")

# ---------- 8. Build dataset ----------
log("building neuro_stats.json")
run("build_dataset.py", ".", os.path.join(ROOT, "neuro_stats.json"))
log("DONE")
