"""Shared snapshot validation and review flags; no network requests or data edits."""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from pipeline.profiles import research_context, validate_research_context
else:
    from .profiles import research_context, validate_research_context


METRICS = (
    ('cns', 'CNS', 'cns_available'),
    ('noncns', 'non-CNS', 'noncns_available'),
    ('fieldtier', 'Neuron + Nature Neuroscience', 'fieldjournals_available'),
    ('elife', 'eLife', 'fieldjournals_available'),
)


def count_available(record, prefix):
    flag = next(flag for key, _, flag in METRICS if key == prefix)
    return record.get(flag, record.get(f'{prefix}_total') is not None)


def validate_snapshot(data):
    if not isinstance(data, dict):
        raise ValueError("The snapshot must be a JSON object.")
    years = data.get('years')
    if (not isinstance(years, list) or not years
            or any(type(y) is not int or y < 1 for y in years)
            or years != sorted(set(years))):
        raise ValueError("Snapshot years must be a nonempty, ascending list of unique integer years.")
    if not isinstance(data.get('records'), list):
        raise ValueError("Snapshot records must be a list.")
    researcher_ids = set()
    for index, record in enumerate(data['records']):
        if not isinstance(record, dict):
            raise ValueError(f"Record {index} must be an object.")
        for field in ('name', 'group', 'institution'):
            if not isinstance(record.get(field), str) or not record[field].strip():
                raise ValueError(f"Record {index} has no usable {field}.")
        if data.get("schema_version", 0) >= 3:
            researcher_id = record.get("researcher_id", "")
            if not re.fullmatch(r"pi_[0-9a-f]{32}", researcher_id) or researcher_id in researcher_ids:
                raise ValueError("Registry-linked snapshots require a unique stable researcher ID per record.")
            researcher_ids.add(researcher_id)
        if data.get("schema_version", 0) >= 4:
            profile = record.get("profile", {})
            validate_research_context(profile)
            if "organisms" in record:
                raise ValueError("Ambiguous organism tags must be separated into sourced lab models and paper species mentions.")
            context = research_context(profile)
            for key in ("contribution_titles", "contribution_keywords", "model_organisms"):
                if record.get(key) != context[key]:
                    raise ValueError(f"{record['name']}: {key} must derive from the source-backed profile, not publication tags.")
        for prefix, label, flag in METRICS:
            if flag in record and type(record[flag]) is not bool:
                raise ValueError(f"{record['name']}: {flag} must be a boolean.")
            total = record.get(f'{prefix}_total')
            by_year = record.get(f'{prefix}_by_year', {})
            if not isinstance(by_year, dict):
                raise ValueError(f"{record['name']}: {label} annual counts must be an object.")
            for value in [total, *by_year.values()]:
                if value is not None and (type(value) is not int or value < 0):
                    raise ValueError(f"{record['name']}: {label} counts must be nonnegative integers or null.")
            if count_available(record, prefix):
                if total is None or any(by_year.get(str(y)) is None for y in years):
                    raise ValueError(f"{record['name']}: available {label} counts need a total and every year.")
        papers = record.get('publications', [])
        if not isinstance(papers, list):
            raise ValueError(f"{record['name']}: publications must be a list.")
        for paper in papers:
            if not isinstance(paper, dict):
                raise ValueError(f"{record['name']}: publication evidence must contain objects.")
            for field in ('pmid', 'journal', 'title', 'last_author', 'match', 'url'):
                if not isinstance(paper.get(field), str):
                    raise ValueError(f"{record['name']}: publication evidence needs a string {field}.")
            if paper.get('tier') not in ('cns', 'field', 'elife', 'other') or type(paper.get('year')) is not int:
                raise ValueError(f"{record['name']}: publication evidence needs a valid tier and integer year.")
            if data.get("schema_version", 0) >= 4 and "organisms" in paper:
                raise ValueError("A paper's organism mentions must not be represented as lab-model claims.")


def record_issues(record, years):
    issues = []

    def add(severity, code, message):
        issues.append({'Severity': severity, 'Code': code, 'Issue': message})

    years = [str(y) for y in years]
    for prefix, label, _ in METRICS:
        if not count_available(record, prefix):
            add('Missing', f'missing_{prefix}', f'{label} counts are unavailable, not zero.')
        else:
            total = record[f'{prefix}_total']
            annual = sum(record[f'{prefix}_by_year'][y] for y in years)
            if total != annual:
                add('Conflict', f'{prefix}_total_mismatch',
                    f'{label} total ({total}) differs from its annual sum ({annual}).')

    if all(count_available(record, key) for key in ('noncns', 'fieldtier', 'elife')):
        subset = record['fieldtier_total'] + record['elife_total']
        if subset > record['noncns_total']:
            add('Conflict', 'noncns_subset_total',
                f"Neuron/Nature Neuroscience + eLife ({subset}) exceeds non-CNS "
                f"({record['noncns_total']}); reconcile coverage and author matching.")
        conflicts = [
            y for y in years
            if record['fieldtier_by_year'][y] + record['elife_by_year'][y]
            > record['noncns_by_year'][y]
        ]
        if conflicts:
            add('Conflict', 'noncns_subset_years',
                f"Journal subsets exceed non-CNS in {', '.join(conflicts)}; "
                "date policies or search coverage may differ.")

    if record.get('identity_warning'):
        add('Review', 'identity_match', record['identity_warning'])
    for note in record.get("source_review_notes", []):
        add("Conflict", "source_total_mismatch", note)
    papers = record.get('publications', [])
    name_conflicts = [paper['pmid'] for paper in papers if paper.get('given_name_warning')]
    if name_conflicts:
        add('Review', 'given_name_mismatch',
            f"Different full given names in counted PMIDs: {', '.join(name_conflicts)}. "
            "Review for aliases or namesakes; these papers are still included.")
    if len({paper['pmid'] for paper in papers}) != len(papers):
        add('Conflict', 'duplicate_pmid', 'The counted-paper evidence includes repeated PMIDs.')
    if papers or record.get('count_method_version'):
        by_tier = Counter((paper['tier'], str(paper['year'])) for paper in papers)
        for prefix, tier in (('cns', 'cns'), ('fieldtier', 'field'), ('elife', 'elife')):
            if count_available(record, prefix):
                if any(by_tier[tier, year] != record[f'{prefix}_by_year'][year] for year in years):
                    add('Conflict', 'paper_evidence_mismatch',
                        f'{prefix} annual counts disagree with the saved counted-paper list.')
        if record.get("publication_model") == "unified-papers" and count_available(record, "noncns"):
            if any(sum(by_tier[tier, year] for tier in ("field", "elife", "other"))
                   != record["noncns_by_year"][year] for year in years):
                add("Conflict", "paper_evidence_mismatch",
                    "non-CNS annual counts disagree with the same included-paper list used for CNS.")
    if not record.get('count_method_version') or not record.get('count_fetched_at'):
        add('Review', 'legacy_count', 'Legacy count: method version and/or retrieval date are unrecorded.')
    elif sum(record.get(f'{key}_total') or 0 for key in ('cns', 'fieldtier', 'elife')):
        if not record.get('publications'):
            add('Review', 'missing_paper_evidence', 'Counted-paper evidence is not attached to this record.')
    proxy_year = record.get("profile", {}).get("career_proxies", {}).get("orcid_employment_year")
    if (record.get('lab_start_year') is not None or proxy_year is not None) and not record.get('lab_start_verified', False):
        add('Review', 'unverified_lab_start',
            'ORCID employment is a career proxy, not a verified independent-lab start.')
    if record.get("profile"):
        if record["profile"]["identity"]["status"] != "source-backed":
            add("Review", "unreviewed_identity", "The registry preserves this identity, but independent source evidence is still needed.")
        if record.get("institution_status") == "unreviewed roster label":
            add("Review", "unreviewed_affiliation", "This institution is a historical roster label, not a sourced current appointment.")
        context = research_context(record["profile"])
        if not context["model_organisms"]:
            add("Review", "uncurated_lab_models", "Lab model organisms are not yet source-backed; article-species mentions do not establish a lab model.")
        if not context["contribution_titles"]:
            review = record["profile"].get("contribution_review")
            add("Review", "uncurated_contributions",
                f"Contribution evidence needs follow-up: {review['reason']}" if review else
                "Selected scientific contributions have not yet been source-curated; this is not absence of contributions.")
    if record.get("evidence_needs_refresh"):
        add("Review", "changed_identity_inputs", "Profile matching inputs changed after this query; refresh to cover new aliases.")
    if record.get("unresolved_papers", 0):
        add("Review", "unresolved_publications",
            f"{record['unresolved_papers']} candidate papers remain unresolved and are not included in totals.")
    namesakes = [paper["pmid"] for paper in record.get("excluded_publications", [])
                 if paper.get("reason") == "different_full_given_name"]
    if namesakes:
        add("Review", "excluded_given_names",
            f"Excluded {len(namesakes)} different-given-name candidates; review aliases if any exclusion is unexpected.")
    return issues


def audit_dataset(data):
    validate_snapshot(data)
    issues = [
        {'Record': index, 'Name': record['name'], 'Institution': record['institution'], **issue}
        for index, record in enumerate(data['records'])
        for issue in record_issues(record, data['years'])
    ]
    assigned = {}
    for index, record in enumerate(data["records"]):
        if record.get("publication_model") == "unified-papers":
            for paper in record.get("publications", []):
                assigned.setdefault(paper["pmid"], []).append(index)
    for pmid, indices in assigned.items():
        if len(indices) > 1:
            for index in indices:
                record = data["records"][index]
                issues.append({"Record": index, "Name": record["name"], "Institution": record["institution"],
                               "Severity": "Conflict", "Code": "shared_last_author_pmid",
                               "Issue": f"PMID {pmid} is assigned to {len(indices)} researcher IDs; review identity links."})
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot', nargs='?', type=Path,
                        default=Path(__file__).resolve().parents[1] / 'neuro_stats.json')
    parser.add_argument('--strict', action='store_true', help='Exit nonzero if counts conflict.')
    args = parser.parse_args()
    with args.snapshot.open(encoding='utf-8') as handle:
        data = json.load(handle)
    issues = audit_dataset(data)
    print(f"Records: {len(data['records'])}; snapshot built: {data.get('generated', 'unknown')}")
    for code, count in sorted(Counter(issue['Code'] for issue in issues).items()):
        print(f"{code}: {count}")
    return int(args.strict and any(issue['Severity'] == 'Conflict' for issue in issues))


if __name__ == '__main__':
    raise SystemExit(main())
