"""Corroborate existing McKnight Scholar claims against the official awardee page.

Default is a read-only preview. --apply records source-backed matches with an audit
history. Unmatched claims are not declared false or automatically corrected.
"""
import argparse
import copy
import datetime
import re
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

from .profiles import DEFAULT_REGISTRY, apply_updates, load_registry, name_parts, normalize
from .storage import write_json
from .unified_recount import affiliation_terms, given_matches


MCKNIGHT_URL = "https://www.mcknight.org/programs/the-mcknight-endowment-fund-for-neuroscience/scholar-awards/awardees/"


class McKnightRecipients(HTMLParser):
    def __init__(self):
        super().__init__()
        self.heading = None
        self.paragraph = None
        self.name = []
        self.in_name = False
        self.year = None
        self.period = ""
        self.recipients = []

    def handle_starttag(self, tag, attrs):
        if tag in ("h1", "h2", "h3", "h4"):
            self.heading = []
        if tag == "p":
            self.paragraph = []
            self.name = []
        if tag == "strong" and self.paragraph is not None and not self.name:
            self.in_name = True

    def handle_data(self, data):
        if self.heading is not None:
            self.heading.append(data)
        if self.paragraph is not None:
            self.paragraph.append(data)
        if self.in_name:
            self.name.append(data)

    def handle_endtag(self, tag):
        if tag in ("h1", "h2", "h3", "h4") and self.heading is not None:
            title = " ".join("".join(self.heading).split())
            if re.fullmatch(r"(?:19|20)\d{2}(?:\s*[-\u2013\u2014]\s*(?:19|20)\d{2})?", title):
                self.year, self.period = int(title[:4]), title
            elif tag in ("h1", "h2", "h3"):
                self.year, self.period = None, ""
            self.heading = None
        if tag == "strong":
            self.in_name = False
        if tag == "p" and self.paragraph is not None:
            raw_name = "".join(self.name).strip()
            credential = re.search(r"\b(?:Ph\.?\s*D\.?|M\.?\s*D\.?)", raw_name, re.I)
            if self.year is not None and credential:
                name = raw_name[:credential.start()].strip(" ,")
                if len(name.split()) >= 2:
                    recipient = {
                        "name": name, "year": self.year, "period": self.period,
                        "context": " ".join("".join(self.paragraph).split()),
                    }
                    if recipient not in self.recipients:
                        self.recipients.append(recipient)
            self.paragraph = None
            self.name = []
            self.in_name = False


def parse_recipients(html):
    parser = McKnightRecipients()
    parser.feed(html)
    if not parser.recipients:
        raise ValueError("No recipient records were parsed; the source layout may have changed. No claims were updated.")
    return parser.recipients


def corroborate(registry, recipients, accessed):
    updates = []
    report = []
    families = defaultdict(set)
    terms = {}
    for profile in registry["profiles"].values():
        for alias in profile["aliases"]:
            families[normalize(alias["family"])].add(profile["id"])
        terms[profile["id"]] = affiliation_terms(profile)
    corroborated = defaultdict(list)
    for recipient in recipients:
        given, family = name_parts(recipient["name"])
        owners = []
        for researcher_id in families[normalize(family)]:
            profile = registry["profiles"][researcher_id]
            if not any(normalize(alias["family"]) == normalize(family)
                       and given_matches(alias["given"], given) for alias in profile["aliases"]):
                continue
            institutions = [term for term in terms[researcher_id]
                            if normalize(term) in normalize(recipient["context"])]
            if institutions:
                owners.append((researcher_id, max(institutions, key=len)))
        if len(owners) == 1:
            researcher_id, institution = owners[0]
            corroborated[researcher_id, recipient["year"]].append((recipient, institution))
    for profile in registry["profiles"].values():
        awards = copy.deepcopy(profile["awards"])
        changed = False
        for award in awards:
            if award["value"] != "McKnight Scholar":
                continue
            matches = corroborated[profile["id"], award.get("year")]
            matched = len(matches) == 1
            report.append({"name": profile["name"], "year": award.get("year"), "corroborated": matched})
            if matched:
                recipient, institution = matches[0]
                source = {
                    "url": MCKNIGHT_URL, "accessed": accessed,
                    "supports": f"The {recipient['period']} Scholar cohort lists {recipient['name']} with {institution}.",
                }
                award.update({
                    "status": "source-backed", "sources": [source],
                    "note": "Award-year cohort corroborated by full given/family name and a known institutional label. "
                            "The listed institution is not assumed to be current; the cohort period is not a lab-start date.",
                })
                changed = True
        if changed:
            updates.append({
                "researcher_id": profile["id"],
                "reason": "Corroborated matching McKnight Scholar claims against the official cohort, name, and institution listing.",
                "changes": {"awards": awards},
            })
    return updates, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    registry = load_registry(args.registry)
    request = Request(MCKNIGHT_URL, headers={"User-Agent": "neuro-cns-explorer/1.0 (source corroboration)"})
    with urlopen(request, timeout=60) as response:
        html = response.read().decode("utf-8")
    recipients = parse_recipients(html)
    updates, report = corroborate(registry, recipients, datetime.date.today().isoformat())
    confirmed = [item for item in report if item["corroborated"]]
    print(f"Source recipient records: {len(recipients)}; corroborated claims: {len(confirmed)}/{len(report)}")
    for item in confirmed[:5]:
        print(f"  {item['name']}: McKnight Scholar {item['year']}")
    if args.apply:
        if not updates:
            raise ValueError("No uniquely corroborated claims; registry left unchanged.")
        write_json(args.registry, apply_updates(registry, updates))
        print(f"Recorded source-backed awards for {len(updates)} profiles; unmatched claims remain unreviewed.")
    else:
        print("Preview only: registry unchanged. Use --apply to record these corroborated sources.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
