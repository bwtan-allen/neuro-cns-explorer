"""Project publication windows and publish registry-linked, evidence-backed snapshots."""
import argparse
import copy
import datetime
import json
from collections import Counter
from pathlib import Path

from .data_quality import audit_dataset, count_available
from .evidence import DEFAULT_DATABASE, EvidenceStore
from .profiles import DEFAULT_REGISTRY, institution_name, load_registry, matching_fingerprint, profile_for, research_context
from .storage import write_json
from .taxonomy import TAG_METHOD_VERSION, retag_paper
from .unified_recount import decide, has_full_given_name


PREFIXES = ("cns", "noncns", "fieldtier", "elife")
ROOT = Path(__file__).resolve().parents[1]


def window_record(record, years):
    """Recompute every displayed total for the selected years; null stays unknown."""
    row = copy.deepcopy(record)
    years = [str(year) for year in years]
    for prefix in PREFIXES:
        source = row.get(f"{prefix}_by_year", {})
        original_total = record.get(f"{prefix}_total")
        if (original_total is not None and source and all(value is not None for value in source.values())
                and original_total != sum(source.values())):
            note = f"{prefix}: source total {original_total} differs from its saved annual sum {sum(source.values())}."
            notes = row.setdefault("source_review_notes", [])
            if note not in notes:
                notes.append(note)
        if not row.get("yearly_coverage_explicit") and not count_available(row, prefix):
            source = {}
        annual = {year: source.get(year) for year in years}
        available = all(value is not None for value in annual.values())
        row[f"{prefix}_by_year"] = annual
        row[f"{prefix}_total"] = sum(annual.values()) if available else None
        if prefix in ("cns", "noncns"):
            row[f"{prefix}_available"] = available
    row["fieldjournals_available"] = row["fieldtier_total"] is not None and row["elife_total"] is not None
    row["cns_gap_years"] = [year for year in years if row["cns_by_year"][year] == 0] if row["cns_available"] else None
    row["cns_years_covered"] = (len(years) - len(row["cns_gap_years"])) if row["cns_available"] else None
    row["publications"] = [retag_paper(paper) for paper in row.get("publications", []) if str(paper["year"]) in years]
    row["excluded_publications"] = [paper for paper in row.get("excluded_publications", [])
                                    if paper.get("year") is None or str(paper["year"]) in years]
    row["unresolved_papers"] = sum(paper.get("decision") == "unresolved" for paper in row["excluded_publications"])
    row["topics"] = sorted({tag for paper in row["publications"] for tag in paper.get("topics", [])})
    row["methods"] = sorted({tag for paper in row["publications"] for tag in paper.get("methods", [])})
    row.pop("organisms", None)
    row["paper_species_mentions"] = sorted({tag for paper in row["publications"] for tag in paper.get("species_mentions", [])})
    row["tag_method_version"] = TAG_METHOD_VERSION
    end_year = int(years[-1])
    profile = row.get("profile", {})
    row.update(research_context(profile))
    career = profile.get("career", {}).get("lab_start_year", {})
    verified = career.get("status") == "source-backed" and career.get("value") is not None
    row["lab_start_verified"] = verified
    row["active_years_in_window"] = None
    row["cns_per_active_year"] = None
    if verified:
        start = career["value"]
        row["lab_start_year"] = start
        row["lab_age"] = max(0, end_year - start) if start <= end_year else None
        row["lab_age_source"] = "source-backed independent-lab start"
        active = sum(int(year) >= start for year in years)
        row["active_years_in_window"] = active
        if active and row["cns_total"] is not None:
            row["cns_per_active_year"] = round(
                sum(value for year, value in row["cns_by_year"].items() if int(year) >= start) / active, 2
            )
    else:
        proxies = profile.get("career_proxies") or row.get("career_proxies") or {
            "orcid_employment_year": record.get("lab_start_year"),
            "first_senior_paper_year": record.get("first_senior_paper_yr"),
        }
        row["career_proxies"] = copy.deepcopy(proxies)
        row["lab_start_year"] = None
        start = proxies.get("orcid_employment_year") or proxies.get("first_senior_paper_year")
        row["lab_age"] = end_year - start if start is not None and start <= end_year else None
        row["lab_age_source"] = ("ORCID employment (unverified)" if proxies.get("orcid_employment_year")
                                 else "first-paper proxy" if start is not None else "")
    row["career_reference_year"] = end_year
    row["yearly_coverage_explicit"] = True
    return row


def project_snapshot(snapshot, start_year=None, end_year=None):
    years = snapshot["years"]
    start_year = years[0] if start_year is None else start_year
    end_year = years[-1] if end_year is None else end_year
    selected = [year for year in years if start_year <= year <= end_year]
    if not selected or start_year not in years or end_year not in years:
        raise ValueError("The selected window must be within the published snapshot.")
    return {**snapshot, "years": selected, "records": [window_record(record, selected) for record in snapshot["records"]],
            "career_reference_year": selected[-1], "partial_calendar_year": selected[-1] == datetime.date.today().year}


def profile_record(record, profile):
    row = copy.deepcopy(record)
    row["researcher_id"] = profile["id"]
    row["name"] = profile["name"]
    row["profile"] = copy.deepcopy(profile)
    row.update(research_context(profile))
    current_year = datetime.date.today().year
    current = [item["institution"] for item in profile["affiliations"]
               if item.get("current") is True and item["status"] == "source-backed"
               and (item.get("start_year") is None or item["start_year"] <= current_year)
               and (item.get("end_year") is None or item["end_year"] >= current_year)]
    row["current_institution"] = "; ".join(current) if current else None
    row["institution"] = row["current_institution"] or "; ".join(
        dict.fromkeys(institution_name(label) for label in record["institution"].split(";") if label.strip())
    )
    row["institution_status"] = "source-backed current profile" if current else "unreviewed roster label"
    row["identity_status"] = profile["identity"]["status"]
    faculty = profile["career"]["faculty_appointment_year"]
    row["faculty_appointment_year"] = faculty["value"] if faculty["status"] == "source-backed" else None
    row["faculty_appointment_status"] = faculty["status"]
    row["orcid"] = profile["orcid"]["value"] if profile["orcid"]["status"] == "source-backed" else None
    row["hhmi_status"] = profile["hhmi"]["value"]
    row["hhmi_source_status"] = profile["hhmi"]["status"]
    row["awards"] = [{"award": item["value"], "year": item.get("year"), "status": item["status"],
                      "sources": item["sources"]} for item in profile["awards"] if item["value"]]
    row["award_names"] = ", ".join(sorted({item["award"] for item in row["awards"]}))
    row["n_awards"] = len(row["awards"])
    row["publication_model"] = row.get("publication_model", "legacy-aggregates")
    return row


def with_evidence(record, profile, result, years):
    row = copy.deepcopy(record)
    usable_identity = (any(has_full_given_name(alias["given"]) for alias in profile["aliases"])
                       or profile["orcid"]["status"] == "source-backed")
    if usable_identity and record.get("identity_warning", "").startswith("No usable full given-name alias or sourced ORCID"):
        row.pop("identity_warning", None)
    covered = {year for year in years if result["start_year"] <= year <= result["end_year"]}
    decisions = []
    for original in result["papers"]:
        paper = retag_paper(original)
        decision, reason = decide(profile, paper, years[0], years[-1])
        decisions.append({**paper, "decision": decision, "reason": reason, "match": reason, "given_name_warning": ""})
    included = [paper for paper in decisions if paper["decision"] == "included"]
    by_tier = Counter((paper["tier"], paper["year"]) for paper in included)
    for prefix, tiers in (("cns", ("cns",)), ("noncns", ("field", "elife", "other")),
                           ("fieldtier", ("field",)), ("elife", ("elife",))):
        row[f"{prefix}_by_year"] = {
            str(year): sum(by_tier[tier, year] for tier in tiers) if year in covered else None for year in years
        }
        values = row[f"{prefix}_by_year"].values()
        row[f"{prefix}_total"] = sum(values) if all(value is not None for value in values) else None
    row.pop("source_review_notes", None)
    row["publications"] = included
    review_fields = ("pmid", "year", "journal", "title", "last_author", "decision", "reason",
                     "url", "doi", "publication_types", "match")
    row["excluded_publications"] = [
        {key: paper[key] for key in review_fields} for paper in decisions if paper["decision"] != "included"
    ]
    row["count_source"] = "unified_pubmed(full-name/affiliation-or-ORCID)"
    row["count_method_version"] = result["method_version"]
    row["count_fetched_at"] = result["fetched_at"]
    row["count_query"] = result["query"]
    row["count_policy"] = result["count_policy"]
    row["count_coverage"] = {"start_year": result["start_year"], "end_year": result["end_year"]}
    row["evidence_needs_refresh"] = result["profile_fingerprint"] != matching_fingerprint(profile)
    row["publication_model"] = "unified-papers"
    row["yearly_coverage_explicit"] = True
    return window_record(row, years)


def build_snapshot(source, registry, store=None, start_year=None, end_year=None):
    if not source["records"]:
        raise ValueError("The source roster is empty; refusing to replace the published snapshot.")
    start_year = source["years"][0] if start_year is None else start_year
    end_year = source["years"][-1] if end_year is None else end_year
    if not 1800 <= start_year <= end_year <= datetime.date.today().year:
        raise ValueError("Invalid publication window.")
    years = list(range(start_year, end_year + 1))
    records = []
    for record in source["records"]:
        profile = profile_for(record, registry)
        row = profile_record(record, profile)
        result = store.result(profile["id"]) if store is not None else None
        usable_identity = (any(has_full_given_name(alias["given"]) for alias in profile["aliases"])
                           or profile["orcid"]["status"] == "source-backed")
        if result is None and not usable_identity:
            if "legacy_counts" not in row:
                row["legacy_counts"] = {
                    key: copy.deepcopy(value) for key, value in record.items()
                    if key == "count_source" or any(key in (f"{prefix}_total", f"{prefix}_by_year") for prefix in PREFIXES)
                }
            for prefix in PREFIXES:
                row[f"{prefix}_by_year"] = {str(year): None for year in years}
                row[f"{prefix}_total"] = None
            row["publications"] = []
            row["excluded_publications"] = []
            row["count_method_version"] = None
            row["count_fetched_at"] = None
            row["count_source"] = "unresolved identity; legacy aggregates archived"
            row["publication_model"] = "unresolved-identity"
            row["yearly_coverage_explicit"] = True
            row["identity_warning"] = "No usable full given-name alias or sourced ORCID; legacy counts are archived, not treated as established matches."
        records.append(with_evidence(row, profile, result, years) if result is not None else window_record(row, years))
    snapshot = {
        **source, "years": years, "records": records, "schema_version": 4, "tag_method_version": TAG_METHOD_VERSION,
        "generated": datetime.date.today().isoformat(),
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "authorship_measure": "last-author matches, not verified corresponding authorship",
        "career_reference_year": end_year, "partial_calendar_year": end_year == datetime.date.today().year,
    }
    snapshot["coverage"] = {
        "registered": len(records),
        "unified_evidence": sum(record["publication_model"] == "unified-papers" for record in records),
        "source_backed_identities": sum(record["identity_status"] == "source-backed" for record in records),
        "source_backed_lab_starts": sum(record.get("lab_start_verified", False) for record in records),
        "source_backed_award_claims": sum(
            award["status"] == "source-backed" for record in records for award in record.get("awards", [])
        ),
        "source_backed_contribution_profiles": sum(bool(record["contribution_titles"]) for record in records),
        "contribution_profiles_reviewed": sum(
            bool(record["contribution_titles"]) or bool(record["profile"].get("contribution_review"))
            for record in records
        ),
        "contribution_profiles_needing_review": sum(
            record["profile"].get("contribution_review", {}).get("status") == "needs-review"
            for record in records
        ),
        "source_backed_model_profiles": sum(bool(record["model_organisms"]) for record in records),
    }
    issues = audit_dataset(snapshot)
    fatal = {"duplicate_pmid", "paper_evidence_mismatch"}
    if any(issue["Code"] in fatal or issue["Code"].endswith("_total_mismatch") for issue in issues):
        raise ValueError("Counts or saved paper evidence disagree; the published snapshot was not replaced.")
    return snapshot


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "neuro_stats.json")
    parser.add_argument("--output", type=Path, default=ROOT / "neuro_stats.json")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--start-year", type=int)
    parser.add_argument("--end-year", type=int)
    args = parser.parse_args(argv)
    with args.input.open(encoding="utf-8") as handle:
        source = json.load(handle)
    registry = load_registry(args.registry)
    if args.database.exists():
        with EvidenceStore(args.database, readonly=True) as store:
            snapshot = build_snapshot(source, registry, store, args.start_year, args.end_year)
    else:
        snapshot = build_snapshot(source, registry, None, args.start_year, args.end_year)
    write_json(args.output, snapshot)
    print(f"Published {len(snapshot['records'])} registry-linked records; coverage: {snapshot['coverage']}")


if __name__ == "__main__":
    main()
