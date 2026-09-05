#!/usr/bin/env python3
"""Refresh the registry's unified PubMed evidence and publish the app snapshot.

With data/researchers.json present, all journals and roster groups use the same
counter. --full forces recounts; --name/--id/--limit allow smaller runs; publication
windows can be selected explicitly. --legacy-discovery retains the historical
institution-discovery pipeline. Failed subprocesses stop snapshot publication.
"""
import argparse
import os, sys, glob, json, subprocess
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.join(ROOT, "pipeline")
DATA = os.path.join(ROOT, "data")
sys.path.insert(0, PIPE)
ALLYRS = set(range(2016, 2026))


def log(msg):
    print(f"[refresh] {msg}", flush=True)


def run(script, *args, cwd=DATA):
    subprocess.run([sys.executable, os.path.join(PIPE, script), *args], cwd=cwd, check=True)


def run_module(module, *args):
    subprocess.run([sys.executable, "-m", module, *args], cwd=ROOT, check=True)


def aggregate():
    from storage import write_json

    log("aggregating candidates")
    with open(os.path.join(DATA, "hhmi_exclude.json"), encoding="utf-8") as handle:
        hhmi_ex = set(json.load(handle))
    recs = defaultdict(lambda: {"pmids": set(), "yrs": [], "insts": set(), "aff": "", "name": ""})
    for fn in glob.glob(os.path.join(DATA, "disc_*.json")):
        with open(fn, encoding="utf-8") as handle:
            papers = json.load(handle)
        for x in papers:
            if not x["neuro"] or f"{x['ln']} {x['ini'].lower()}" in hhmi_ex:
                continue
            r = recs[(x["ln"], x["ini"])]
            r["insts"].add(x["inst"])
            if x["pmid"] in r["pmids"]:
                continue
            r["pmids"].add(x["pmid"])
            r["yrs"].append(x["yr"])
            r["aff"] = r["aff"] or x["aff"]
            r["name"] = x["name"]

    established, rising = [], []
    for (ln, ini), r in recs.items():
        n = len(r["pmids"]); ys = sorted(set(r["yrs"]))
        row = {"ln": ln, "ini": ini, "name": r["name"], "cns": n, "cns_yrs": len(ys),
               "cns_years": ys, "cns_gaps": sorted(ALLYRS - set(ys)), "insts": sorted(r["insts"]), "aff": r["aff"]}
        if n >= 5:
            established.append(row)
        elif n >= 2:
            rising.append(row)
    established.sort(key=lambda x: -x["cns"])
    rising.sort(key=lambda x: -x["cns"])
    write_json(os.path.join(DATA, "candidates2.json"), established)
    write_json(os.path.join(DATA, "rising_base.json"), rising)
    log(f"established={len(established)}  rising={len(rising)}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true",
                        help="Force unified recounts; in legacy mode, also clear enrichment/ORCID caches.")
    parser.add_argument("--hhmi", action="store_true",
                        help="Also recompute HHMI legacy caches in legacy mode; unified mode already includes HHMI.")
    parser.add_argument("--legacy-discovery", action="store_true",
                        help="Explicitly run the older institution-discovery/enrichment pipeline.")
    parser.add_argument("--name", action="append", help="Recount selected registry names only.")
    parser.add_argument("--id", action="append", dest="ids", help="Recount selected stable researcher IDs only.")
    parser.add_argument("--limit", type=int, help="Limit a unified recount for a small rollout.")
    parser.add_argument("--start-year", type=int)
    parser.add_argument("--end-year", type=int)
    parser.add_argument("--output", type=Path, default=Path(ROOT) / "neuro_stats.json")
    args = parser.parse_args(argv)
    registry = Path(DATA) / "researchers.json"
    if registry.exists() and not args.legacy_discovery:
        with (Path(ROOT) / "neuro_stats.json").open(encoding="utf-8") as handle:
            source = json.load(handle)
        start_year = args.start_year if args.start_year is not None else source["years"][0]
        end_year = args.end_year if args.end_year is not None else source["years"][-1]
        database = Path(DATA) / "publications.sqlite3"
        common = ["--registry", str(registry), "--database", str(database),
                  "--start-year", str(start_year), "--end-year", str(end_year)]
        selected = []
        for name in args.name or []:
            selected.extend(["--name", name])
        for researcher_id in args.ids or []:
            selected.extend(["--id", researcher_id])
        if args.limit is not None:
            selected.extend(["--limit", str(args.limit)])
        if args.full:
            selected.append("--force")
        log("unified all-journal recount (HHMI and non-HHMI use the same rules)")
        run_module("pipeline.unified_recount", *common, *selected)
        log("publishing registry-linked snapshot")
        run_module("pipeline.snapshot", *common, "--input", str(Path(ROOT) / "neuro_stats.json"),
                   "--output", str(args.output))
        if args.output.resolve() == (Path(ROOT) / "neuro_stats.json").resolve():
            run("make_exports.py")
        log("DONE")
        return 0
    if args.name or args.ids or args.limit is not None or args.start_year is not None or args.end_year is not None:
        parser.error("Selected researchers/windows require the unified registry pipeline, not legacy discovery.")
    if args.output.resolve() != (Path(ROOT) / "neuro_stats.json").resolve():
        parser.error("Preview output paths require the unified registry pipeline.")
    import discover

    os.makedirs(DATA, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".discovery-", dir=DATA) as staging:
        for inst in discover.INST:
            log(f"discovery: {inst}")
            run("discover.py", inst, cwd=staging)
        for inst in discover.INST:
            filename = f"disc_{inst.replace(' ', '_')}.json"
            os.replace(os.path.join(staging, filename), os.path.join(DATA, filename))
    aggregate()

    if args.full:
        for cache in ("cand_noncns.json", "enrich.json", "awards_enrich.json", "labstart.json"):
            path = os.path.join(DATA, cache)
            if os.path.exists(path):
                os.remove(path)
    for script, message in (
        ("cand_noncns.py", "non-CNS for established candidates"),
        ("enrich.py", "career proxies and non-CNS for rising candidates"),
        ("orcid_start.py", "ORCID employment proxies and full names"),
        ("build_awards.py", "compiling award recipients"),
        ("awards_ingest.py", "enriching award recipients"),
    ):
        log(message)
        run(script)
    log("per-person CNS / Neuron+NatNeuro / eLife recount")
    run("recount.py", *(("--force",) if args.full else ()))
    if args.hhmi:
        log("refreshing HHMI legacy tallies")
        run("pm_all2.py")
        run("noncns_all.py")
    log("building neuro_stats.json")
    run("build_dataset.py", DATA, os.path.join(ROOT, "neuro_stats.json"))
    log("writing exports/*.csv")
    run("make_exports.py")
    log("DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
