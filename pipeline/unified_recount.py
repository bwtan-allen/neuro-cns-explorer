"""All-journal last-author evidence using stable identities and one counting policy.

python -m pipeline.unified_recount --name 'Xiaowei Zhuang' --database /tmp/review.sqlite3
"""
import argparse
import datetime
import re
from collections import Counter
from pathlib import Path

from . import person_cns as pubmed
from .evidence import DEFAULT_DATABASE, EvidenceStore
from .inst_keywords import keywords_for
from .profiles import DEFAULT_REGISTRY, load_registry, matching_fingerprint, normalize, normalize_orcid
from .taxonomy import classify, retag_paper


METHOD_VERSION = 3
DEFAULT_START_YEAR, DEFAULT_END_YEAR = 2016, 2025
BAD_TYPES = pubmed.BAD_PUBTYPES | {"preprint"}
COUNT_POLICY = (
    "All journals; affiliation-scoped last-author query including middle initials; compatible given-name components "
    "with at least one shared full component plus a known affiliation, linked ORCID, or source-backed override; "
    "electronic year preferred; Journal Article required; notices/retractions/preprints excluded."
)


def given_components(value):
    return [normalize(part).replace(" ", "") for part in re.split(r"[\s.]+", value) if normalize(part)]


def has_full_given_name(value):
    return any(len(part) > 1 for part in given_components(value))


def given_relation(expected, observed):
    expected_parts, observed_parts = given_components(expected), given_components(observed)
    if not expected_parts or not observed_parts:
        return "incomplete"
    if ("".join(expected_parts) == "".join(observed_parts)
            and has_full_given_name(expected) and has_full_given_name(observed)):
        return "matched"
    full_component = False
    for left, right in zip(expected_parts, observed_parts):
        if left == right:
            full_component |= len(left) > 1
        elif not ((len(left) == 1 or len(right) == 1) and left[0] == right[0]):
            return "conflict"
    return "matched" if full_component else "incomplete"


def given_matches(expected, observed):
    return given_relation(expected, observed) == "matched"


def affiliation_terms(profile):
    terms = []
    for affiliation in profile["affiliations"]:
        for term in [affiliation["institution"], *keywords_for(affiliation["institution"], fallback=False)]:
            if normalize(term) and normalize(term) not in {"la jolla", "riverside", "california", "florida"}:
                terms.append(term)
    return list(dict.fromkeys(terms))


def query_for(profile, start_year, end_year):
    authors = []
    for alias in profile["aliases"]:
        given = alias["given"].strip()
        if has_full_given_name(given):
            # LAUT does not expand D to DJ automatically; the explicit prefix keeps middle initials.
            authors.append(f'"{alias["family"]} {given[0]}*"[LAUT]')
    clauses = []
    affiliations = affiliation_terms(profile)
    if authors and affiliations:
        author_query = " OR ".join(dict.fromkeys(authors))
        affiliation_query = " OR ".join(f'"{term}"[ad]' for term in affiliations)
        clauses.append(f'(({author_query}) AND ({affiliation_query}))')
    if profile["orcid"]["status"] == "source-backed":
        clauses.append(f'"{normalize_orcid(profile["orcid"]["value"])}"[AUID]')
    if not clauses:
        raise ValueError(f"{profile['name']}: a full given-name alias with known affiliations, or a source-backed ORCID, is required.")
    return f'({" OR ".join(clauses)}) AND ("{start_year}"[dp]:"{end_year}"[dp])'


def search(profile, start_year, end_year):
    query = query_for(profile, start_year, end_year)
    try:
        ids = pubmed.esearch_all(query)
    except pubmed.SearchTooLarge:
        if start_year == end_year:
            raise pubmed.SearchTooLarge(f"{profile['name']}: even a one-year author search is too broad; curate identity aliases.")
        middle = (start_year + end_year) // 2
        left = search(profile, start_year, middle)
        right = search(profile, middle + 1, end_year)
        return list(dict.fromkeys(left + right))
    if ids is None:
        raise RuntimeError(f"PubMed search failed for {profile['name']}; previous evidence was retained.")
    return ids


def eligibility(paper, start_year, end_year):
    types = {value.casefold() for value in paper["publication_types"]}
    if types & BAD_TYPES or paper.get("retracted"):
        return "excluded", "excluded_publication_type_or_retraction"
    if "journal article" not in types:
        return "excluded", "not_indexed_as_journal_article"
    if re.match(r"^(?:author |publisher )?(?:correction|erratum|retraction)\s*:", paper["title"], re.I):
        return "excluded", "correction_notice"
    if paper["year"] is None:
        return "unresolved", "missing_publication_year"
    if not start_year <= paper["year"] <= end_year:
        return "excluded", "outside_publication_window"
    return None


def decide(profile, paper, start_year, end_year):
    ineligible = eligibility(paper, start_year, end_year)
    if ineligible:
        return ineligible
    override = next((item for item in profile["paper_overrides"] if str(item["pmid"]) == paper["pmid"]), None)
    if override:
        if override["decision"] == "include" and not any(
            normalize(alias["family"]) == normalize(paper["last_author_family"])
            for alias in profile["aliases"]
        ):
            return "unresolved", "include_override_requires_last_author_family_alias"
        return ("included" if override["decision"] == "include" else "excluded"), "source_backed_override: " + override["reason"]
    orcid = profile["orcid"]
    if orcid["status"] == "source-backed":
        target = normalize_orcid(orcid["value"])
        identifiers = set()
        for identifier in paper["last_author_orcids"]:
            try:
                matched = normalize_orcid(identifier)
            except ValueError:
                warnings = paper.setdefault("metadata_warnings", [])
                warning = "Invalid last-author ORCID supplied by PubMed."
                if warning not in warnings:
                    warnings.append(warning)
                continue
            identifiers.add(matched)
        if identifiers == {target}:
            return "included", "last_author_orcid"
        if identifiers:
            return "unresolved", "conflicting_last_author_orcid"
    aliases = [alias for alias in profile["aliases"]
               if normalize(alias["family"]) == normalize(paper["last_author_family"])]
    if not aliases:
        return "excluded", "different_last_author_family_name"
    given = paper["last_author_given"]
    relations = [given_relation(alias["given"], given) for alias in aliases]
    if "matched" not in relations and "incomplete" in relations:
        return "unresolved", "incomplete_given_name_metadata"
    if "matched" not in relations:
        return "excluded", "different_full_given_name"
    affiliation = normalize(" | ".join(paper["last_author_affiliations"]))
    if any(normalize(term) in affiliation for term in affiliation_terms(profile)):
        return "included", "last_author_full_name_and_known_affiliation"
    return "unresolved", "full_name_matches_but_affiliation_unconfirmed"


def recount(profile, start_year=DEFAULT_START_YEAR, end_year=DEFAULT_END_YEAR):
    query = query_for(profile, start_year, end_year)
    ids = search(profile, start_year, end_year)
    ids = list(dict.fromkeys([*ids, *(str(item["pmid"]) for item in profile["paper_overrides"])]))
    papers = []
    fetched_at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    for index in range(0, len(ids), 200):
        batch = ids[index:index + 200]
        xml = pubmed.call("efetch.fcgi", {"db": "pubmed", "id": ",".join(batch), "retmode": "xml"}, "xml")
        if xml is None:
            raise RuntimeError(f"PubMed article retrieval failed for {profile['name']}; previous evidence was retained.")
        for paper in pubmed.parse_articles(xml, batch):
            decision, reason = decide(profile, paper, start_year, end_year)
            tags = classify(paper["title"], paper["mesh"], paper["keywords"])
            papers.append({**paper, **tags, "decision": decision, "reason": reason, "retrieved_at": fetched_at})
    missing_overrides = {str(item["pmid"]) for item in profile["paper_overrides"]} - {paper["pmid"] for paper in papers}
    if missing_overrides:
        raise ValueError(f"Override PMIDs are not available as PubMed article records: {', '.join(sorted(missing_overrides))}")
    return {
        "researcher_id": profile["id"], "query": query, "start_year": start_year, "end_year": end_year,
        "method_version": METHOD_VERSION, "profile_fingerprint": matching_fingerprint(profile),
        "fetched_at": fetched_at, "papers": papers,
        "retrieved_records": len(ids), "parsed_article_records": len(papers),
        "omitted_non_article_records": len(ids) - len(papers),
        "count_policy": COUNT_POLICY,
    }


def reclassify(profile, result):
    """Reuse raw evidence only when the current query covers exactly the same input scope."""
    if result["method_version"] != METHOD_VERSION:
        raise ValueError("A changed retrieval method requires fresh PubMed evidence.")
    if result["query"] != query_for(profile, result["start_year"], result["end_year"]):
        raise ValueError(f"{profile['name']}: changed query scope requires a fresh recount, not offline reclassification.")
    required = {str(item["pmid"]) for item in profile["paper_overrides"]}
    if not required <= {paper["pmid"] for paper in result["papers"]}:
        raise ValueError(f"{profile['name']}: newly referenced override papers require a fresh recount.")
    papers = []
    for original in result["papers"]:
        paper = retag_paper(original)
        decision, reason = decide(profile, paper, result["start_year"], result["end_year"])
        papers.append({**paper, "decision": decision, "reason": reason})
    return {
        **result, "papers": papers, "profile_fingerprint": matching_fingerprint(profile),
        "count_policy": COUNT_POLICY,
        "reclassified_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    }


def cache_current(metadata, profile, start_year, end_year, max_age_days=30):
    if not metadata or metadata.get("method_version") != METHOD_VERSION:
        return False
    if metadata.get("profile_fingerprint") != matching_fingerprint(profile):
        return False
    if metadata.get("start_year", end_year + 1) > start_year or metadata.get("end_year", start_year - 1) < end_year:
        return False
    if metadata.get("query") != query_for(profile, metadata["start_year"], metadata["end_year"]):
        return False
    try:
        fetched_at = datetime.datetime.fromisoformat(metadata.get("fetched_at", ""))
    except (ValueError, TypeError):
        return False
    if fetched_at.tzinfo is None:
        return False
    age = datetime.datetime.now(datetime.timezone.utc) - fetched_at
    return datetime.timedelta(0) <= age < datetime.timedelta(days=max_age_days)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--name", action="append", help="Exact registry name; ambiguous names require --id.")
    parser.add_argument("--id", action="append", dest="ids", help="Stable researcher ID.")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--start-year", type=int, default=DEFAULT_START_YEAR)
    parser.add_argument("--end-year", type=int, default=DEFAULT_END_YEAR)
    parser.add_argument("--max-age-days", type=int, default=30)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reclassify-only", action="store_true",
                        help="Re-evaluate existing raw evidence without network calls; changed queries require a fresh recount.")
    args = parser.parse_args(argv)
    if not 1800 <= args.start_year <= args.end_year <= datetime.date.today().year:
        parser.error("Choose a valid publication window, ending no later than the current year.")
    if args.limit is not None and args.limit < 1 or args.max_age_days < 0:
        parser.error("Limit must be positive and cache age cannot be negative.")
    registry = load_registry(args.registry)
    profiles = registry["profiles"]
    selected = list(profiles) if not args.ids and not args.name else list(args.ids or [])
    if any(researcher_id not in profiles for researcher_id in selected):
        parser.error("An unknown researcher ID was selected.")
    for name in args.name or []:
        matches = [key for key, profile in profiles.items() if profile["name"] == name]
        if len(matches) != 1:
            parser.error(f"Name {name!r} has {len(matches)} registry matches; choose an exact --id.")
        selected.extend(matches)
    selected = list(dict.fromkeys(selected))
    if args.limit:
        selected = selected[:args.limit]
    if args.dry_run:
        for researcher_id in selected:
            print(researcher_id, profiles[researcher_id]["name"])
        return 0
    completed = 0
    skipped = 0
    with EvidenceStore(args.database) as store:
        for researcher_id in selected:
            profile = profiles[researcher_id]
            has_given = any(has_full_given_name(alias["given"]) for alias in profile["aliases"])
            if not has_given and profile["orcid"]["status"] != "source-backed":
                if args.ids or args.name:
                    raise ValueError(f"{profile['name']}: curate a full given-name alias or linked ORCID before recounting.")
                print(f"NEEDS IDENTITY REVIEW: {profile['name']} ({researcher_id}); retained as legacy, not counted as zero.",
                      flush=True)
                skipped += 1
                continue
            if args.reclassify_only:
                existing = store.result(researcher_id)
                if existing is None:
                    print(f"NEEDS INITIAL FETCH: {profile['name']} ({researcher_id}); no evidence to reclassify.", flush=True)
                    skipped += 1
                    continue
                store.save(researcher_id, reclassify(profile, existing))
                completed += 1
                continue
            if not args.force and cache_current(store.metadata(researcher_id), profile,
                                                 args.start_year, args.end_year, args.max_age_days):
                continue
            result = recount(profile, args.start_year, args.end_year)
            store.save(researcher_id, result)
            counts = Counter(paper["decision"] for paper in result["papers"])
            completed += 1
            print(f"{profile['name']}: {dict(counts)}", flush=True)
    print(f"Unified evidence updated for {completed} researchers; {skipped} skipped (see explicit reasons above).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
