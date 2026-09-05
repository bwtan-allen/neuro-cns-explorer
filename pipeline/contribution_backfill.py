"""Prepare bounded review batches and apply cited contribution curations safely."""
import argparse
import datetime
import json
from pathlib import Path
from urllib.parse import urlparse

from .profiles import DEFAULT_REGISTRY, apply_updates, load_registry, normalize, validate_research_context
from .storage import write_json


def prepare_batches(registry, candidates, directory, batch_size=30):
    if batch_size < 1:
        raise ValueError("Batch size must be positive.")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    assigned = set()
    existing = sorted(directory.glob("batch-*.json"))
    for path in existing:
        with path.open(encoding="utf-8") as handle:
            assigned.update(item["researcher_id"] for item in json.load(handle)["researchers"])
    ready = [
        result for researcher_id, result in candidates.items()
        if researcher_id not in assigned and not registry["profiles"][researcher_id].get("contributions")
        and result.get("papers")
    ]
    paths = []
    for offset in range(0, len(ready), batch_size):
        batch = []
        for result in ready[offset:offset + batch_size]:
            profile = {key: result.get(key) for key in
                       ("researcher_id", "name", "institution", "field", "accessed", "note")}
            profile["aliases"] = [{key: alias.get(key) for key in ("given", "family", "status")} for alias in result.get("aliases", [])]
            profile["papers"] = []
            for paper in result["papers"][:6]:
                source = {key: paper.get(key) for key in
                          ("pmid", "doi", "title", "year", "journal", "url", "pmcid", "abstract",
                           "publication_types", "article_affiliation", "matched_authors")}
                source["coauthors"] = [author["name"] for author in paper.get("authors", [])[:5]]
                source["last_authors"] = [author["name"] for author in paper.get("authors", [])[-3:]]
                source["author_count"] = len(paper.get("authors", []))
                profile["papers"].append(source)
            batch.append(profile)
        path = directory / f"batch-{len(existing) + len(paths) + 1:03d}.json"
        write_json(path, {"researchers": batch, "instructions": (
            "Select up to three distinct, source-supported scientific/tool contributions per researcher. "
            "Read candidate evidence, verify identity and preserve team credit; do not invent priority or sole-inventor claims. "
            "Candidates and citation counts are discovery aids, not proof of core career importance. "
            "When full names or identity are ambiguous, mark needs-review and provide the evidence gap instead of guessing."
        )})
        paths.append(path)
    return paths


def validate_curation(profile, entry, candidates):
    if entry["researcher_id"] != profile["id"]:
        raise ValueError("Curation must target the same stable researcher ID.")
    if entry.get("status") not in {"complete", "needs-review"} or not entry.get("reason"):
        raise ValueError("Each curation needs a complete/needs-review status and a reason.")
    contributions = entry.get("contributions", [])
    validate_research_context({"contributions": contributions})
    if entry["status"] == "complete" and not contributions:
        raise ValueError("A complete contribution curation cannot be empty.")
    known = {paper["pmid"]: paper for paper in candidates.get(profile["id"], {}).get("papers", [])}
    for item in contributions:
        if item["status"] != "source-backed":
            raise ValueError("Backfill applies only source-backed claims; unresolved candidates belong in the review report.")
        if len(item["summary"].split()) > 110:
            raise ValueError("Contribution summaries must remain bounded, not copied full abstracts.")
        attribution = item["attribution"].casefold()
        collaborative = any(word in attribution for word in ("coauthor", "co-author", "team", "collaborat", "joint", "co-develop"))
        sole = "sole-authored" in attribution or "sole author" in attribution
        cited = [known[str(source["pmid"])] for source in item["sources"]
                 if str(source.get("pmid")) in known]
        verified_sole = sole and cited and all(len(paper.get("authors", [])) == 1 for paper in cited)
        if not collaborative and not verified_sole:
            raise ValueError("Contribution attribution must preserve collaborative credit or document a genuinely sole-authored paper.")
        anchor_years = set()
        full_name_anchor = False
        initial_only_anchor = False
        for source in item["sources"]:
            pmid = source.get("pmid")
            if pmid is None:
                continue
            pmid = str(pmid)
            if not pmid.isdigit():
                raise ValueError("Primary-paper PMIDs must be numeric.")
            if pmid in known:
                anchor_years.add(known[pmid]["year"])
                matches = known[pmid].get("matched_authors", [])
                full_name_anchor |= any(author["match"] == "full-name" for author in matches)
                initial_only_anchor |= bool(matches) and not any(author["match"] == "full-name" for author in matches)
                expected_doi = known[pmid].get("doi", "").casefold()
                actual_doi = (source.get("doi") or "").casefold()
                if actual_doi and expected_doi and actual_doi != expected_doi:
                    raise ValueError(f"DOI/PMID mismatch in curation for {profile['name']}.")
                if source.get("title") and normalize(source["title"]) != normalize(known[pmid]["title"]):
                    raise ValueError(f"Paper title/PMID mismatch in curation for {profile['name']}.")
                parsed = urlparse(source["url"])
                if parsed.hostname == "pubmed.ncbi.nlm.nih.gov" and parsed.path.strip("/") != pmid:
                    raise ValueError(f"PubMed link/PMID mismatch in curation for {profile['name']}.")
            elif not entry.get("additional_sources_verified"):
                raise ValueError(f"{profile['name']}: additional PMID {pmid} needs explicit source-verification evidence.")
        if anchor_years and item["year"] not in anchor_years:
            raise ValueError(f"{profile['name']}: contribution year must identify a cited anchor publication.")
        if initial_only_anchor and not full_name_anchor and not entry.get("additional_sources_verified"):
            raise ValueError(f"{profile['name']}: initials-only paper attribution requires additional verified identity evidence.")
    return contributions


def apply_curations(registry, entries, candidates, require_all=False):
    if require_all:
        addressed = {entry["researcher_id"] for entry in entries}
        missing = [profile["name"] for researcher_id, profile in registry["profiles"].items()
                   if researcher_id not in addressed and not profile.get("contributions")]
        if missing:
            raise ValueError(f"Full-roster review is incomplete for {len(missing)} profiles: {', '.join(missing[:12])}")
    updates = []
    seen = set()
    report = {}
    for entry in entries:
        researcher_id = entry["researcher_id"]
        if researcher_id in seen:
            raise ValueError(f"Duplicate curation target: {researcher_id}")
        seen.add(researcher_id)
        profile = registry["profiles"][researcher_id]
        contributions = validate_curation(profile, entry, candidates)
        existing = profile.get("contributions", [])
        if existing and contributions:
            raise ValueError(f"{profile['name']}: preserve existing curated contributions; explicit edits use profiles apply.")
        report[researcher_id] = {
            "name": profile["name"], "status": entry["status"],
            "reason": entry["reason"], "contributions": len(contributions),
            "reviewed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        }
        review = {key: report[researcher_id][key] for key in ("status", "reason", "reviewed_at")}
        if entry.get("review_sources"):
            review["sources"] = entry["review_sources"]
            report[researcher_id]["sources"] = entry["review_sources"]
        changes = {"contribution_review": review}
        if contributions:
            changes["contributions"] = contributions
        updates.append({"researcher_id": researcher_id, "reason": entry["reason"], "changes": changes})
    return apply_updates(registry, updates), report


def merge_curations(paths, overrides=()):
    entries = {}
    for path in paths:
        with Path(path).open(encoding="utf-8") as handle:
            batch = json.load(handle)
        for entry in batch:
            researcher_id = entry["researcher_id"]
            if researcher_id in entries:
                raise ValueError(f"Overlapping ordinary curation batches: {researcher_id}")
            entries[researcher_id] = entry
    replaced = set()
    for path in overrides:
        with Path(path).open(encoding="utf-8") as handle:
            batch = json.load(handle)
        for entry in batch:
            researcher_id = entry["researcher_id"]
            if researcher_id in replaced:
                raise ValueError(f"Overlapping explicit curation overrides: {researcher_id}")
            replaced.add(researcher_id)
            entries[researcher_id] = entry
    return list(entries.values())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--candidates", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="action", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--directory", type=Path, required=True)
    prepare.add_argument("--batch-size", type=int, default=30)
    apply = subparsers.add_parser("apply")
    apply.add_argument("curations", type=Path, nargs="+")
    apply.add_argument("--report", type=Path, required=True)
    apply.add_argument("--require-all", action="store_true", help="Refuse to publish if any uncurated profile is unaddressed.")
    apply.add_argument("--override", type=Path, action="append", default=[],
                       help="Explicit source/identity review replacing a draft entry for the same ID.")
    audit = subparsers.add_parser("audit")
    audit.add_argument("curations", type=Path, nargs="+")
    audit.add_argument("--require-all", action="store_true")
    audit.add_argument("--override", type=Path, action="append", default=[])
    args = parser.parse_args(argv)
    registry = load_registry(args.registry)
    with args.candidates.open(encoding="utf-8") as handle:
        candidates = json.load(handle)
    if args.action == "prepare":
        paths = prepare_batches(registry, candidates, args.directory, args.batch_size)
        print(f"Prepared {len(paths)} source-review batches.")
        for path in paths:
            print(path)
    else:
        entries = merge_curations(args.curations, args.override)
        updated, report = apply_curations(registry, entries, candidates, args.require_all)
        if args.action == "audit":
            print(f"Validated {len(report)} researcher curations without writing the registry.")
            return
        write_json(args.registry, updated)
        write_json(args.report, report)
        print(f"Applied {sum(bool(item['contributions']) for item in report.values())} contribution profiles; "
              f"{sum(item['status'] == 'needs-review' for item in report.values())} need further source review.")


if __name__ == "__main__":
    main()
