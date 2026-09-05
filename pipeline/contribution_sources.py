"""Collect primary-paper candidates for source-grounded contribution curation.

This does not generate achievement claims or change the publication-count ledger.
Citation counts help locate candidates, not rank scientists or establish priority.
Keep candidate abstracts in a review workspace, not the published app dataset.
"""
import argparse
import datetime
import html
import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .profiles import DEFAULT_REGISTRY, load_registry, normalize
from .storage import write_json
from .unified_recount import given_relation


BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
EXCLUDED_TYPES = {
    "review", "systematic review", "meta-analysis", "editorial", "comment", "news",
    "preprint", "retracted publication", "retraction of publication", "published erratum",
}


def request(query, page_size=50):
    params = {"query": query, "format": "json", "resultType": "core", "pageSize": page_size}
    url = BASE + "?" + urllib.parse.urlencode(params)
    for attempt in range(5):
        try:
            time.sleep(0.35)
            req = urllib.request.Request(url, headers={"User-Agent": "neuro-cns-explorer/source-review"})
            with urllib.request.urlopen(req, timeout=60) as response:
                result = json.load(response)
            if result.get("errMsg") or "resultList" not in result:
                raise ValueError("Europe PMC returned an unexpected search result.")
            return result
        except (OSError, ValueError) as error:
            print(f"Source request attempt {attempt + 1}/5 failed ({type(error).__name__}).", flush=True)
            if attempt == 4:
                raise
            time.sleep(min(2 ** attempt, 16))
    raise RuntimeError("Source request did not complete.")


def clean_text(value):
    text = html.unescape(value or "")
    text = re.sub(r"</?(?:sub|sup|i|b|em|strong)\b[^>]*>", "", text, flags=re.I)
    return " ".join(re.sub(r"<[^>]+>", " ", text).split())


def query_name(profile):
    aliases = profile["aliases"]
    usable = next((alias for alias in aliases if alias.get("given") and re.search(r"[A-Za-z]", alias["family"])), None)
    if usable is None:
        return None
    family = usable["family"]
    given = usable["given"]
    if "(" in family or re.search(r"\b(?:GW|JN)$", family):
        # Legacy display annotations are not part of a scientific author's surname.
        display = re.sub(r"\([^)]*\)", "", profile["name"]).strip()
        parts = display.split()
        if len(parts) > 2 and re.fullmatch(r"[A-Z]{2,3}", parts[-1]):
            parts.pop()
        if len(parts) >= 2:
            given, family = " ".join(parts[:-1]), parts[-1]
    initial = next((character for character in given if character.isalpha()), "")
    return (given, family, initial) if initial else None


def author_query_name(profile, full=False):
    parsed = query_name(profile)
    if parsed is None:
        return None
    given, family, initial = parsed
    text = f"{family} {given if full else initial}"
    return "".join(character for character in unicodedata.normalize("NFKD", text)
                   if not unicodedata.combining(character))


def author_matches(profile, author):
    family = author.get("lastName", "")
    given = author.get("firstName", "")
    candidates = [(alias["given"], alias["family"]) for alias in profile["aliases"]]
    parsed = query_name(profile)
    if parsed:
        candidates.append(parsed[:2])
    relations = [given_relation(expected, given) for expected, surname in candidates
                 if normalize(surname) == normalize(family)]
    if "matched" in relations:
        return "full-name"
    if "incomplete" in relations:
        return "initials-only"
    if relations:
        return "different-given-name"
    return "different-family-name"


def paper_record(record, profile):
    pmid = str(record.get("pmid") or "")
    if record.get("source") != "MED" or not pmid.isdigit():
        return None
    types = record.get("pubTypeList", {}).get("pubType", [])
    normalized_types = {value.casefold() for value in types}
    if normalized_types & EXCLUDED_TYPES or "journal article" not in normalized_types:
        return None
    corrections = record.get("commentCorrectionList", {}).get("commentCorrection", [])
    if any("retract" in str(item.get("type", "")).casefold() for item in corrections):
        return None
    title = clean_text(record.get("title", ""))
    if not title or re.match(r"^(?:author |publisher )?(?:correction|erratum|retraction)\s*:", title, re.I):
        return None
    authors = []
    for index, author in enumerate(record.get("authorList", {}).get("author", [])):
        given, family = author.get("firstName", ""), author.get("lastName", "")
        affiliations = [
            re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "", clean_text(item.get("affiliation", ""))).strip()
            for item in author.get("authorAffiliationDetailsList", {}).get("authorAffiliation", [])
        ]
        authors.append({
            "name": f"{given} {family}".strip() or author.get("fullName", ""),
            "given": given, "family": family, "initials": author.get("initials", ""),
            "position": index + 1, "affiliations": affiliations, "match": author_matches(profile, author),
        })
    matched = [author for author in authors if author["match"] in ("full-name", "initials-only")]
    if not matched:
        return None
    return {
        "pmid": pmid, "doi": record.get("doi", ""), "title": title,
        "year": int(record["pubYear"]), "journal": record.get("journalInfo", {}).get("journal", {}).get("title", ""),
        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", "pmcid": record.get("pmcid"),
        "abstract": clean_text(record.get("abstractText", "")),
        "authors": authors, "matched_authors": matched, "publication_types": types,
        "cited_by_count": record.get("citedByCount", 0),
        "article_affiliation": re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "", clean_text(record.get("affiliation", ""))).strip(),
        "source_api": "Europe PMC (PubMed-indexed MED record)",
    }


def collect_profile(profile, snapshot_record=None):
    parsed = query_name(profile)
    if parsed is None:
        return {"researcher_id": profile["id"], "name": profile["name"], "papers": [],
                "status": "identity-review", "reason": "No usable given-name query; resolve identity before curation."}
    name = author_query_name(profile)
    date = datetime.date.today().isoformat()
    base = f'FIRST_PDATE:[1900-01-01 TO {date}] AND SRC:MED AND NOT PUB_TYPE:"Review"'
    full_name = author_query_name(profile, full=True).replace(".", " ")
    queries = [f'AUTHOR:"{full_name}" AND {base} sort_cited:y',
               f'AUTH_LAST:"{name}" AND {base} sort_cited:y']
    papers = {}
    for query in queries:
        result = request(query)
        for item in result["resultList"].get("result", []):
            paper = paper_record(item, profile)
            if paper:
                papers[paper["pmid"]] = paper
    full = [paper for paper in papers.values() if any(author["match"] == "full-name" for author in paper["matched_authors"])]
    if len(full) < 5:
        query = f'AUTHOR:"{name}" AND {base} sort_cited:y'
        queries.append(query)
        result = request(query)
        for item in result["resultList"].get("result", []):
            paper = paper_record(item, profile)
            if paper:
                papers.setdefault(paper["pmid"], paper)
    ranked = sorted(papers.values(), key=lambda paper: (
        any(author["match"] == "full-name" for author in paper["matched_authors"]),
        paper["cited_by_count"],
    ), reverse=True)
    return {
        "researcher_id": profile["id"], "name": profile["name"],
        "institution": snapshot_record.get("institution", "") if snapshot_record else "",
        "field": snapshot_record.get("field", "") if snapshot_record else "",
        "aliases": profile["aliases"], "affiliations": profile["affiliations"],
        "identity": profile["identity"], "orcid": profile["orcid"],
        "status": "candidates" if ranked else "source-review",
        "queries": queries, "accessed": date, "papers": ranked[:12],
        "note": "Candidate selection is not a contribution claim. Verify identity, scientific interpretation and team credit before applying.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_REGISTRY.parent.parent / "neuro_stats.json")
    parser.add_argument("--output", type=Path, required=True, help="Private review-workspace cache; do not publish candidate abstracts.")
    parser.add_argument("--name", action="append")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--append", action="store_true", help="Preserve already reviewed paper metadata while adding sources for the same identity.")
    parser.add_argument("--pmid", action="append", default=[], help="Fetch an explicit primary-paper clue for one selected researcher.")
    args = parser.parse_args(argv)
    registry = load_registry(args.registry)
    with args.snapshot.open(encoding="utf-8") as handle:
        records = {record["researcher_id"]: record for record in json.load(handle)["records"]}
    if args.output.exists():
        with args.output.open(encoding="utf-8") as handle:
            output = json.load(handle)
    else:
        output = {}
    profiles = [profile for profile in registry["profiles"].values()
                if not args.name or profile["name"] in args.name]
    if args.name and {profile["name"] for profile in profiles} != set(args.name):
        parser.error("A selected name is not present in the registry.")
    if args.pmid and (len(profiles) != 1 or any(not pmid.isdigit() for pmid in args.pmid)):
        parser.error("--pmid requires exactly one selected researcher and numeric PMIDs.")
    if args.limit is not None:
        if args.limit < 1:
            parser.error("--limit must be positive.")
        profiles = profiles[:args.limit]
    for profile in profiles:
        if not args.force and profile["id"] in output:
            continue
        result = collect_profile(profile, records.get(profile["id"]))
        if args.pmid:
            query = "SRC:MED AND (" + " OR ".join(f"EXT_ID:{pmid}" for pmid in args.pmid) + ")"
            fetched = request(query)
            for item in fetched["resultList"].get("result", []):
                paper = paper_record(item, profile)
                if paper and paper["pmid"] not in {paper["pmid"] for paper in result["papers"]}:
                    result["papers"].append(paper)
        if args.append and profile["id"] in output:
            previous = output[profile["id"]]
            before = {(item["given"], item["family"]) for item in previous.get("aliases", [])}
            after = {(item["given"], item["family"]) for item in profile["aliases"]}
            if before != after:
                raise ValueError("Do not append candidate caches across identity corrections; use a fresh fetch instead.")
            retained = {paper["pmid"]: paper for paper in previous["papers"]}
            retained.update({paper["pmid"]: paper for paper in result["papers"]})
            result["papers"] = list(retained.values())
        result["status"] = "candidates" if result["papers"] else result["status"]
        output[profile["id"]] = result
        write_json(args.output, output)
        print(f"{profile['name']}: {len(result['papers'])} candidates ({result['status']})", flush=True)
    print(f"Source candidates retained for {len(output)} profiles; no contribution claims or counts changed.")


if __name__ == "__main__":
    main()
