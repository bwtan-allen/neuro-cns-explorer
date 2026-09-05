# Neuroscience Publication Explorer

An auditable researcher-discovery app built around **stable researcher IDs,
source-bearing profiles, and paper-level PubMed evidence**. The original roster
covers 2016-2025 and combines HHMI profiles, institution-based discovery, early-career
awards, and manual supplements. It is not a complete or current institutional census.

**Last author is not necessarily corresponding author. Counts and journal names
are not measures of researcher quality.** Use this for finding relevant people and
papers, not automated hiring, funding, or promotion judgments.

## Run the app

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

The explorer supports publication-window selection, shared sidebar filters,
paper-derived topic/method/organism tags, researcher comparisons, source-bearing
profiles, included/excluded paper evidence, and a data-quality review queue.
Only the selected view is rendered. A changed snapshot invalidates the app cache.
The app itself does not make PubMed calls or modify profiles.

## Data architecture

```text
researchers.json (stable identities, aliases, claims, change history)
       |
       v
unified PubMed queries + shared article XML parser
       |
       v
publications.sqlite3 (one PMID catalog, per-person decisions, completed queries)
       |
       v
neuro_stats.json + CSV exports -> Streamlit
```

| File | Responsibility |
|------|----------------|
| `data/researchers.json` | Persistent `pi_...` IDs; separate given/family aliases; ORCID, affiliation history, career, HHMI, and award claims |
| `data/publications.sqlite3` | Normalized PMID evidence, included/excluded/unresolved decisions, source queries, retrieval dates, and method versions |
| `neuro_stats.json` | Published app snapshot; contains explicit coverage and source statuses |
| `pipeline/profiles.py` | Safe legacy migration, claim validation, immutable-ID curation, and change history |
| `pipeline/person_cns.py` | Shared PubMed transport/XML parsing; older tier-only counter retained for compatibility |
| `pipeline/unified_recount.py` | All-journal identity matching and resumable evidence refresh |
| `pipeline/snapshot.py` | Registry linkage, evidence-derived counts, and shared publication-window calculations |
| `pipeline/taxonomy.py` | Conservative, transparent title/MeSH/keyword discovery rules |
| `pipeline/award_sources.py` | Conservative source corroboration of existing McKnight Scholar claims |
| `pipeline/data_quality.py` | Read-only arithmetic, identity, coverage, and provenance review flags |
| `refresh_data.py` | Refresh orchestration; unified pipeline is the default when the registry exists |
| `exports/` | Source/status-aware CSV exports with stable IDs |

## What is and is not established

Each profile claim has a **value, status, and sources**. Sources record an HTTP(S)
URL, access date, and the specific fact supported.

| Status or measure | Interpretation |
|-------------------|----------------|
| `source-backed` | An explicit claim linked to supporting evidence; not a guarantee that the source will remain current |
| `unreviewed` | A reported value preserved for review, including imported roster labels |
| `unknown` | No established value; not false, zero, or evidence of absence |
| Stable researcher ID | A persistent record key, not proof that an imported identity is correct |
| Current institution | Only displayed as source-backed/current when the profile explicitly records that claim |
| Independent lab start | Only a source-backed statement of independence is used for active-lab-year rates |
| Career proxy | ORCID employment or first last-author paper; neither proves when an independent lab began |
| HHMI / award cohort | Historical discovery labels; do not infer current status from the cohort alone |
| Count of zero | Zero included matches under the recorded query and matching policy, not proof of no publications |
| Missing count | Unavailable coverage, not zero |
| Snapshot build date | Assembly date, not the date every underlying claim or paper was refreshed |

ORCID links imported from the old pipeline remain unreviewed until a source
establishes the link. Name-only ORCID search results are not promoted to identity
evidence. Legacy employment years are retained as proxies, not migrated into
verified lab-start fields.

See [ICMJE's author-role definitions](https://www.icmje.org/recommendations/browse/roles-and-responsibilities/defining-the-role-of-authors-and-contributors.html)
and [DORA's research-assessment recommendations](https://sfdora.org/read/).

## One counting model for every journal

The unified engine uses the same identity, publication-type, and date rules for
CNS and non-CNS. Its mutually exclusive paper buckets are:

- **CNS:** Cell, Nature, and Science, including Science's full XML journal title.
- **Field:** Neuron and Nature Neuroscience.
- **eLife.**
- **Other journals.**

**non-CNS = Field + eLife + Other**, derived from the same included PMID list.
These subsets must not be added to non-CNS again.

Queries use PubMed's last-author index, with explicit initial-prefix expansion so
`D` does not accidentally omit `DJ`. Name queries are bounded by known institutional
keywords; source-backed ORCID queries are also supported. The same institutional
terms are used when examining the last author's own affiliations, not merely a
co-author's address. Institution moves must be recorded in the registry for recall.

An included identity match requires a full given-name/family-name alias plus a
known affiliation, a source-backed ORCID matching the last author, or a documented
paper override. Different full given names are excluded rather than merged.
Given-name components must be compatible and share at least one full component:
`H. Robert` can match `Howard Robert`, but `H R` alone is insufficient.
Initial-only or unconfirmed matches stay unresolved. Researchers without a usable
given-name alias or sourced ORCID are explicitly reported for identity curation,
not silently assigned zero counts.

The engine prefers electronic publication years, then print/Medline years.
The Journal Article publication type is required; listed news/editorial,
correction, retraction, and preprint categories are excluded. **Reviews may be
included when PubMed also indexes them as Journal Article**; this is not a
primary-research-only classifier. A paper about biological axon retraction is not
mistaken for a retraction notice.

Each completed query retains its window, policy, method version, profile-input
fingerprint, and retrieval date. Every parsed article has an inclusion, exclusion,
or unresolved decision with a reason. Publication metadata includes PMID, DOI,
title, journal, dates, last-author evidence, MeSH/keywords, and source URL.
Contact email addresses are removed from newly parsed affiliation text.

Oversized PubMed searches are split by year range, and boundary PMIDs are
deduplicated. Incomplete searches/XML fail rather than being saved as complete
zero results. Each researcher update is transactional; a failed run keeps that
person's previous result. The published JSON is replaced atomically only after
assembly succeeds.

## Discovery, windows, and comparisons

Topic, method, and organism tags are **rule-inferred mentions from included paper
titles, MeSH headings, and keywords**. They are not manually validated descriptions
of a lab, nor proof that an organism was the study subject. Each paper retains
matched-term evidence. Untagged legacy records are unknown, not irrelevant.

Selected publication windows recompute totals, gap years, paper lists, tags, and
downloads consistently. Missing years remain null. Current partial calendar years
are labeled; the app does not extrapolate them to a full year's output.
Full-window averages use the selected number of calendar years. Active-lab-year
rates are available only for source-backed independence dates and use publications
within those active years, not all pre-lab papers.

Comparison views retain identity/source status and distinguish legacy aggregates
from unified evidence. Mixed-method or unreviewed comparisons require caution.
The app's coverage indicators show how much of the roster has unified evidence
and source-backed profile claims; a new schema does not make old facts verified.

## Curate profiles without losing identity

Migration is idempotent and does not merge people by surname/initials:

```bash
python -m pipeline.profiles migrate
python -m pipeline.profiles show --name 'Xiaowei Zhuang'
```

For a separate migration preview:

```bash
python -m pipeline.profiles --registry /tmp/neuro-registry-preview.json migrate --limit 3
```

Apply a JSON list of reviewed changes:

```bash
python -m pipeline.profiles apply /path/to/profile-updates.json
```

Each update needs `researcher_id`, `reason`, and `changes`. Use an ID from `show`,
not a display-name guess. Editable top-level fields include `name`, `identity`,
`aliases`, `orcid`, `affiliations`, `career`, `hhmi`, `awards`, and `paper_overrides`.
Provided fields/lists replace those fields; include the complete claim/list,
including its statuses and sources. IDs and legacy links cannot be changed by
this command. Before/after values are retained in the registry's change history.

Source-backed claims require citations; linked ORCIDs must pass their checksum.
An affiliation's observation date is not an invented start date. A faculty
appointment is not automatically a lab-independence date. Paper overrides require
a PMID, decision, reason, and sources, and do not bypass publication/date
eligibility rules.

Existing McKnight Scholar claims can be corroborated against the official cohort
page without promoting other awards or current-affiliation claims:

```bash
python -m pipeline.award_sources          # source-matching preview, no edits
python -m pipeline.award_sources --apply  # record uniquely corroborated claims
```

The award year, compatible full name, and a known institutional label must all
match a unique registry identity. Initial-only identities, ambiguous matches, and unmatched claims remain
unreviewed; lack of a match is not treated as proof an award claim is false.

## Review and refresh

Local, read-only review:

```bash
python -m pipeline.data_quality
python -m pipeline.data_quality --strict  # nonzero if counts conflict
```

Inspect a small sample in a separate evidence database before changing a bulk
matching policy:

```bash
python -m pipeline.unified_recount --limit 3 --dry-run
python -m pipeline.unified_recount --name 'Xiaowei Zhuang' --database /tmp/neuro-review.sqlite3
python -m pipeline.snapshot --database /tmp/neuro-review.sqlite3 --output /tmp/neuro-review.json
```

After approval, refresh the registry roster:

```bash
python refresh_data.py
python refresh_data.py --full            # force all identified registry entries
python refresh_data.py --name 'Xiaowei Zhuang'
python refresh_data.py --start-year 2016 --end-year 2026  # includes a labeled partial 2026
```

Recount caches expire after 30 days and invalidate on matching inputs, query
policy, or method changes. A failed subprocess stops snapshot publication.
Unresolved identities and unsourced profile facts remain visibly outstanding.
HHMI and non-HHMI researchers use the same unified counter.

To publish already-fetched evidence, or export a smaller time window, without
new API calls:

```bash
python -m pipeline.snapshot
python pipeline/make_exports.py
python pipeline/make_exports.py --start-year 2020 --end-year 2025 --output-dir /tmp/neuro-exports
```

`python -m pipeline.unified_recount --reclassify-only` reapplies matching decisions
to cached raw evidence without network calls or a fabricated retrieval date.
It refuses changed query scopes, which require a fresh recount instead.

Legacy CSV filenames containing `corresponding` are retained for compatibility;
the `Authorship_measure` column identifies the last-author proxy. Exports carry
IDs, source/status fields, discovery tags, and selected-window values.

The old institution-discovery/enrichment pipeline remains available explicitly:

```bash
python refresh_data.py --legacy-discovery
```

It retains its historical 2016-2025 discovery window and name-keyed caches.
Newly discovered identities require review; legacy enrichments do not overwrite
sourced registry claims. The older `pipeline/recount.py` is a tier-only legacy
utility, not the default all-journal counter.

## Automated coverage and deployment

```bash
python -m unittest discover -s tests
```

The offline suite covers registry identity/provenance invariants, namesakes and
middle initials, shared journal rules, missing coverage, transactional updates,
publication windows, source-backed rates, and Streamlit interactions.

GitHub Actions runs these regressions and a scheduled monthly refresh. The
refresh workflow commits data only after the refresh command succeeds. Review a
sample before enabling a new matching policy on a scheduled deployment.

`NCBI_API_KEY` is an optional repository secret for a higher request allowance.
`NCBI_EMAIL` is optional for the primary PubMed client. Requests are paced and
secrets are not printed in URLs. Streamlit Community Cloud can deploy
`streamlit_app.py` directly from the repo.

The optional `com.neuro.cns.refresh.plist` is a local macOS template. Update its
Python executable, repository path, working directory, and log paths before use.

## Remaining curation is explicit

The original 2026-09-01 snapshot had 13 total-level journal-subset conflicts,
50 annual subset conflicts, 63 unavailable non-CNS entries, and 49 unverified
ORCID-derived career dates. These categories overlap. Current counts and review
coverage are reported by the app and audit command rather than hard-coded here.

Further improvement now means reviewing identities and aliases, citing historical
appointments and awards, resolving ambiguous papers, and expanding coverage with
measured attribution precision/recall. Do not replace that work with a larger
prestige score or pretend that automated source matching establishes every fact.
