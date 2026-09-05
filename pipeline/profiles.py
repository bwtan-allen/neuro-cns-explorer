"""Persistent researcher identities and source-bearing profile claims.

Run with python -m pipeline.profiles migrate|apply|show. Migration never merges
people by surname/initials or treats a legacy employment year as lab independence.
"""
import argparse
import copy
import datetime
import hashlib
import json
import re
import unicodedata
import uuid
from pathlib import Path
from urllib.parse import urlparse

from .storage import write_json


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "data" / "researchers.json"
STATUSES = {"unknown", "unreviewed", "source-backed"}
PARTICLES = {"da", "de", "del", "della", "den", "der", "di", "dos", "du", "la", "le", "van", "von"}
INSTITUTION_ALIASES = {
    "ucsf": "University of California, San Francisco",
    "ucsd": "University of California, San Diego",
    "ucla": "University of California, Los Angeles",
    "uc berkeley": "University of California, Berkeley",
    "mit": "Massachusetts Institute of Technology",
    "caltech": "California Institute of Technology",
    "nyu": "New York University",
    "stanford": "Stanford University",
    "rockefeller": "Rockefeller University",
    "the rockefeller university": "Rockefeller University",
    "columbia": "Columbia University",
    "princeton": "Princeton University",
    "yale": "Yale University",
    "duke": "Duke University",
    "penn": "University of Pennsylvania",
    "usc": "University of Southern California",
    "washu st louis": "Washington University in St. Louis",
    "washington university in st louis": "Washington University in St. Louis",
    "ut southwestern": "University of Texas Southwestern Medical Center",
    "ut southwestern medical center": "University of Texas Southwestern Medical Center",
    "baylor": "Baylor College of Medicine",
    "cshl": "Cold Spring Harbor Laboratory",
    "mpfi": "Max Planck Florida Institute for Neuroscience",
    "salk": "Salk Institute for Biological Studies",
    "scripps": "Scripps Research",
    "mount sinai": "Icahn School of Medicine at Mount Sinai",
    "weill cornell": "Weill Cornell Medicine",
}


def normalize(value):
    text = ''.join(c for c in unicodedata.normalize("NFKD", value or "")
                   if not unicodedata.combining(c)).casefold()
    return re.sub(r"[\W_]+", " ", text).strip()


def institution_name(value):
    return INSTITUTION_ALIASES.get(normalize(value), value.strip())


def source_key(record):
    return normalize(record["name"]) + "|" + normalize(record["institution"])


def name_parts(name, pubmed_name=None):
    parts = name.strip().split()
    candidate = (pubmed_name or name).rsplit(" ", 1)
    if len(candidate) == 2 and re.fullmatch(r"[A-Z]{1,4}", candidate[1]):
        family = candidate[0]
        size = len(family.split())
        if len(parts) > size and normalize(" ".join(parts[-size:])) == normalize(family):
            return " ".join(parts[:-size]), family
        if pubmed_name is None or name == pubmed_name:
            return "", family
    if len(parts) < 2:
        return "", name.strip()
    index = len(parts) - 1
    while index > 1 and normalize(parts[index - 1]) in PARTICLES:
        index -= 1
    return " ".join(parts[:index]), " ".join(parts[index:])


def claim(value=None, status=None, sources=None, note=""):
    return {"value": value, "status": status or ("unknown" if value is None else "unreviewed"),
            "sources": sources or [], "note": note}


def normalize_orcid(value):
    text = str(value or "").strip().removeprefix("https://orcid.org/").removeprefix("http://orcid.org/")
    compact = text.replace("-", "").upper()
    if not re.fullmatch(r"\d{15}[\dX]", compact):
        raise ValueError("ORCID must contain 16 checksum-valid digits (the last may be X).")
    total = 0
    for digit in compact[:-1]:
        total = (total + int(digit)) * 2
    checksum = (12 - total % 11) % 11
    if compact[-1] != ("X" if checksum == 10 else str(checksum)):
        raise ValueError("ORCID checksum is invalid.")
    return "-".join(compact[index:index + 4] for index in range(0, 16, 4))


def _validate_sources(sources):
    if not isinstance(sources, list):
        raise ValueError("Sources must be a list.")
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("Each source must be an object.")
        url = urlparse(source.get("url", ""))
        if url.scheme not in ("http", "https") or not url.netloc:
            raise ValueError("A profile source needs an absolute HTTP(S) URL.")
        datetime.date.fromisoformat(source["accessed"])
        if not source.get("supports"):
            raise ValueError("A source must say which fact it supports.")


def _validate_claim(value):
    if not isinstance(value, dict) or value.get("status") not in STATUSES:
        raise ValueError("Profile claims need an explicit unknown/unreviewed/source-backed status.")
    _validate_sources(value.get("sources", []))
    if value["status"] == "source-backed" and not value.get("sources"):
        raise ValueError("A source-backed claim must cite its evidence.")
    if value["status"] == "source-backed" and value.get("value") is None:
        raise ValueError("A source-backed claim needs an established value; missing facts remain unknown.")
    if value.get("status") == "unknown" and value.get("value") is not None:
        raise ValueError("An unknown claim cannot assert a value.")


def validate_registry(registry):
    if registry.get("schema_version") != 1 or not isinstance(registry.get("profiles"), dict):
        raise ValueError("Unsupported researcher registry schema.")
    linked = {}
    for researcher_id, profile in registry["profiles"].items():
        if profile.get("id") != researcher_id or not re.fullmatch(r"pi_[0-9a-f]{32}", researcher_id):
            raise ValueError("Researcher IDs must be stable pi_ UUID identifiers.")
        if not isinstance(profile.get("name"), str) or not profile["name"].strip():
            raise ValueError(f"{researcher_id}: a display name is required.")
        for key in profile.get("legacy_keys", []):
            if key in linked and linked[key] != researcher_id:
                raise ValueError("A legacy record is linked to multiple researcher IDs.")
            linked[key] = researcher_id
        for field in ("identity", "orcid", "hhmi"):
            _validate_claim(profile[field])
        if profile["orcid"]["status"] == "source-backed":
            normalize_orcid(profile["orcid"]["value"])
        for field in ("lab_start_year", "faculty_appointment_year"):
            _validate_claim(profile["career"][field])
            year = profile["career"][field]["value"]
            if year is not None and (type(year) is not int or not 1800 <= year <= 2100):
                raise ValueError("Career years must be integers, not inferred dates or free text.")
        for alias in profile["aliases"]:
            if not isinstance(alias.get("given"), str) or not isinstance(alias.get("family"), str) or not alias["family"]:
                raise ValueError("Name aliases require separate given and family names.")
            _validate_claim(alias)
            if alias["status"] == "unknown":
                raise ValueError("Do not add unknown aliases to identity matching; omit them until a name is reported.")
        for affiliation in profile["affiliations"]:
            _validate_claim(affiliation)
            if affiliation["status"] == "unknown":
                raise ValueError("Do not add unknown affiliation relationships to matching; an empty history is allowed.")
            if not isinstance(affiliation.get("institution"), str) or not affiliation["institution"].strip():
                raise ValueError("Affiliations require an institution name.")
            for field in ("start_year", "end_year"):
                year = affiliation.get(field)
                if year is not None and (type(year) is not int or not 1800 <= year <= 2100):
                    raise ValueError("Affiliation years must be integers or null.")
            start, end = affiliation.get("start_year"), affiliation.get("end_year")
            if start is not None and end is not None and start > end:
                raise ValueError("An affiliation cannot end before it starts.")
        for award in profile["awards"]:
            _validate_claim(award)
        for override in profile.get("paper_overrides", []):
            if override.get("decision") not in ("include", "exclude") or not str(override.get("pmid", "")).isdigit():
                raise ValueError("Paper overrides need a PMID and an include/exclude decision.")
            if not override.get("reason") or not override.get("sources"):
                raise ValueError("Paper overrides require a reason and source evidence.")
            _validate_sources(override["sources"])


def load_registry(path=DEFAULT_REGISTRY):
    with Path(path).open(encoding="utf-8") as handle:
        registry = json.load(handle)
    validate_registry(registry)
    return registry


def migrate(snapshot, registry=None):
    result = copy.deepcopy(registry or {"schema_version": 1, "profiles": {}, "changes": []})
    validate_registry(result)
    linked = {key: profile["id"] for profile in result["profiles"].values() for key in profile["legacy_keys"]}
    seen = set()
    for record in snapshot["records"]:
        key = source_key(record)
        if key in seen:
            raise ValueError("Duplicate legacy name/institution records need explicit identity resolution.")
        seen.add(key)
        known_id = record.get("researcher_id") or linked.get(key)
        if known_id:
            if known_id not in result["profiles"]:
                raise ValueError(f"Unknown persisted researcher ID: {known_id}")
            continue
        researcher_id = "pi_" + uuid.uuid5(uuid.NAMESPACE_URL, "neuro-cns-explorer:legacy:" + key).hex
        given, family = name_parts(record["name"], record.get("pubmed_name"))
        affiliations = []
        for label in record["institution"].split(";"):
            if label.strip():
                affiliations.append({
                    **claim(label.strip()), "institution": institution_name(label),
                    "start_year": None, "end_year": None, "current": None,
                })
        profile = {
            "id": researcher_id, "name": record["name"], "legacy_keys": [key],
            "identity": claim(record["name"], note="Imported roster identity; not independently established."),
            "aliases": [{**claim(record["name"]), "given": given, "family": family}],
            "orcid": claim(record.get("orcid")),
            "affiliations": affiliations,
            "career": {
                "lab_start_year": claim(),
                "faculty_appointment_year": claim(),
            },
            "career_proxies": {
                "orcid_employment_year": record.get("lab_start_year"),
                "first_senior_paper_year": record.get("first_senior_paper_yr"),
                "legacy_source": record.get("lab_age_source", ""),
            },
            "hhmi": claim("Listed in legacy HHMI cohort" if record["group"] == "HHMI" else None),
            "awards": [{**claim(award.get("award")), "year": award.get("year")} for award in record.get("awards", [])],
            "paper_overrides": [],
            "legacy_snapshot": snapshot.get("generated"),
        }
        result["profiles"][researcher_id] = profile
        linked[key] = researcher_id
    validate_registry(result)
    return result


def profile_for(record, registry):
    if record.get("researcher_id"):
        return registry["profiles"][record["researcher_id"]]
    key = source_key(record)
    matches = [profile for profile in registry["profiles"].values() if key in profile["legacy_keys"]]
    if len(matches) != 1:
        raise ValueError(f"{record['name']}: no unique registry link; migrate or curate this record first.")
    return matches[0]


def matching_fingerprint(profile):
    fields = {key: profile[key] for key in ("aliases", "orcid", "affiliations", "paper_overrides")}
    return hashlib.sha256(json.dumps(fields, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def profile_evidence(profile):
    """Flatten claims without discarding unknown or uncited facts."""
    if not profile:
        return []
    claims = [(label, profile[field]) for label, field in
              (("Identity", "identity"), ("ORCID", "orcid"), ("HHMI status", "hhmi"))]
    claims += [(label, profile["career"][field]) for label, field in
               (("Independent lab start", "lab_start_year"), ("Faculty appointment", "faculty_appointment_year"))]
    claims += [("Name alias", item) for item in profile["aliases"]]
    claims += [(f"Affiliation: {item['institution']}", item) for item in profile["affiliations"]]
    claims += [(f"Award ({item.get('year') or 'year unknown'})", item) for item in profile["awards"]]
    rows = []
    for label, item in claims:
        for source in item.get("sources") or [{}]:
            rows.append({
                "Claim": label, "Value": item.get("value"), "Status": item["status"],
                "URL": source.get("url", ""), "Accessed": source.get("accessed", ""),
                "Supports": source.get("supports", ""), "Note": item.get("note", ""),
            })
    return rows


def apply_updates(registry, updates):
    result = copy.deepcopy(registry)
    allowed = {"name", "identity", "aliases", "orcid", "affiliations", "career", "hhmi", "awards", "paper_overrides"}
    for update in updates:
        researcher_id = update["researcher_id"]
        changes = update["changes"]
        if not update.get("reason") or not changes or not changes.keys() <= allowed:
            raise ValueError("Curation needs a reason and explicit editable profile fields; IDs cannot change.")
        profile = result["profiles"][researcher_id]
        before = {key: copy.deepcopy(profile[key]) for key in changes}
        profile.update(copy.deepcopy(changes))
        result["changes"].append({
            "researcher_id": researcher_id, "reason": update["reason"],
            "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "before": before, "after": copy.deepcopy(changes),
        })
    validate_registry(result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    subparsers = parser.add_subparsers(dest="action", required=True)
    migration = subparsers.add_parser("migrate")
    migration.add_argument("--snapshot", type=Path, default=ROOT / "neuro_stats.json")
    migration.add_argument("--limit", type=int, help="Preview the first N legacy records in a separate registry.")
    update = subparsers.add_parser("apply")
    update.add_argument("updates", type=Path, help="JSON list of ID-addressed changes with reasons.")
    show = subparsers.add_parser("show")
    show.add_argument("--name", help="Exact display name (may return multiple distinct IDs).")
    args = parser.parse_args(argv)
    registry = load_registry(args.registry) if args.registry.exists() else None
    if args.action == "migrate":
        with args.snapshot.open(encoding="utf-8") as handle:
            snapshot = json.load(handle)
        if args.limit is not None:
            if args.limit < 1:
                parser.error("--limit must be positive")
            snapshot["records"] = snapshot["records"][:args.limit]
        registry = migrate(snapshot, registry)
        write_json(args.registry, registry)
        print(f"Registry: {len(registry['profiles'])} stable identities; source status preserved.")
    elif registry is None:
        parser.error("The registry does not exist; migrate the snapshot first.")
    elif args.action == "apply":
        with args.updates.open(encoding="utf-8") as handle:
            updates = json.load(handle)
        registry = apply_updates(registry, updates)
        write_json(args.registry, registry)
        print(f"Applied {len(updates)} profile updates with a change history.")
    else:
        for profile in registry["profiles"].values():
            if args.name is None or profile["name"] == args.name:
                print(profile["id"], profile["name"], profile["identity"]["status"])


if __name__ == "__main__":
    main()
