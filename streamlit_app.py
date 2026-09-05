"""Neuroscience last-author publication explorer. Run: streamlit run streamlit_app.py"""
import json
import unicodedata
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from pipeline.data_quality import audit_dataset, record_issues, validate_snapshot
from pipeline.profiles import normalize, profile_evidence
from pipeline.snapshot import project_snapshot


st.set_page_config(page_title="Neuro CNS Publication Explorer", layout="wide")
DATA = Path(__file__).resolve().with_name("neuro_stats.json")


def search_text(value):
    return ''.join(c for c in unicodedata.normalize("NFKD", value)
                   if not unicodedata.combining(c)).casefold()


# Cached snapshots and frames are shared read-only; views transform copies.
@st.cache_resource(show_spinner=False, max_entries=2)
def read_snapshot(path, file_version):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    validate_snapshot(data)
    return data


def selection_key(record, index):
    return record.get("researcher_id") or f"legacy-row-{index}"


@st.cache_resource(show_spinner=False, max_entries=4)
def load(path, file_version, start_year=None, end_year=None):
    data = project_snapshot(read_snapshot(path, file_version), start_year, end_year)
    issues = audit_dataset(data)
    years = [str(y) for y in data["years"]]
    rows = []
    for index, record in enumerate(data["records"]):
        totals = {key: record.get(f"{key}_total") for key in ("cns", "noncns", "fieldtier", "elife")}
        cby = record.get("cns_by_year", {})
        nby = record.get("noncns_by_year", {})
        flags = record_issues(record, years)
        conflicts = any(flag["Severity"] == "Conflict" for flag in flags)
        missing = any(value is None for value in totals.values())
        identity_review = any(flag["Code"] in ("given_name_mismatch", "identity_match", "unreviewed_identity")
                              for flag in flags)
        profile = record.get("profile") or {}
        names = [record["name"], record.get("pubmed_name") or ""]
        for alias in profile.get("aliases", []):
            names.extend([alias.get("value") or "", f"{alias['given']} {alias['family']}"])
            if alias["given"].split():
                names.append(f"{alias['given'].split()[0]} {alias['family']}")
        searchable = [*names, *(normalize(name) for name in names), record["institution"],
                      record.get("field") or "", record.get("researcher_id") or ""]
        faculty = profile.get("career", {}).get("faculty_appointment_year", {})
        proxies = record.get("career_proxies") or profile.get("career_proxies") or {}
        coverage = record.get("count_coverage") or {}
        annual_coverage = "; ".join(
            f"{label}: {sum(record.get(f'{prefix}_by_year', {}).get(year) is not None for year in years)}/{len(years)}"
            for prefix, label in (("cns", "CNS"), ("noncns", "non-CNS"), ("fieldtier", "field"), ("elife", "eLife")))
        rows.append({
            "Search_text": search_text(" ".join(searchable)),
            "UI_key": selection_key(record, index), "Researcher_ID": record.get("researcher_id"),
            "Name": record["name"], "Group": record["group"], "Institution": record["institution"],
            "Current_institution": record.get("current_institution"),
            "Institution_status": record.get("institution_status", "unreviewed legacy roster label"),
            "Identity_status": record.get("identity_status", profile.get("identity", {}).get("status", "legacy/unreviewed")),
            "Profile_status": "registry-linked" if record.get("researcher_id") and profile else "legacy / no sourced profile",
            "Field": record.get("field", ""), "Neuro_confidence": record.get("neuro_confidence", ""),
            "Career_stage": record.get("career_stage", ""), "Lab_start_year": record.get("lab_start_year"),
            "Lab_start_status": profile.get("career", {}).get("lab_start_year", {}).get("status", "unknown"),
            "Lab_start_verified": record.get("lab_start_verified", False),
            "Faculty_appointment_year": record.get("faculty_appointment_year", faculty.get("value")),
            "Faculty_appointment_status": record.get("faculty_appointment_status", faculty.get("status", "unknown")),
            "First_senior_paper": proxies.get("first_senior_paper_year", record.get("first_senior_paper_yr")),
            "ORCID_employment_year": proxies.get("orcid_employment_year"),
            "Lab_age": record.get("lab_age"), "Lab_age_source": record.get("lab_age_source") or "",
            "Active_years_in_window": record.get("active_years_in_window"),
            "CNS_per_active_year": record.get("cns_per_active_year"),
            "Awards": record.get("award_names", ""),
            "N_awards": record.get("n_awards", 0), "CNS_total": totals["cns"],
            "HHMI_status": record.get("hhmi_status") or "unknown",
            "HHMI_source_status": record.get("hhmi_source_status", "unknown"),
            "CNS_years_covered": record.get("cns_years_covered"),
            "CNS_avg_per_yr": round(totals["cns"] / len(years), 2) if totals["cns"] is not None else None,
            "CNS_gap_years": (", ".join(record["cns_gap_years"]) or "none")
            if record.get("cns_gap_years") is not None else "unknown",
            "nonCNS_total": totals["noncns"],
            "nonCNS_years_covered": sum(nby[y] > 0 for y in years) if totals["noncns"] is not None else None,
            "nonCNS_avg_per_yr": round(totals["noncns"] / len(years), 2) if totals["noncns"] is not None else None,
            "NeuronNatNeuro_total": totals["fieldtier"], "eLife_total": totals["elife"],
            "Topics": record.get("topics", []), "Methods": record.get("methods", []),
            "Organisms": record.get("organisms", []),
            "Publication_model": record.get("publication_model", "legacy-aggregates"),
            "Window_start": data["years"][0], "Window_end": data["years"][-1],
            "Selected_years": ", ".join(years), "Career_reference_year": data["career_reference_year"],
            "Annual_coverage": annual_coverage,
            "Coverage_status": "Incomplete selected window" if missing else "Complete selected window",
            "Source_coverage": (f"{coverage.get('start_year', 'unknown')}–{coverage.get('end_year', 'unknown')}"
                                if coverage else "unrecorded (legacy)"),
            "Count_source": record.get("count_source", "unrecorded"),
            "Count_fetched_at": record.get("count_fetched_at"),
            "Count_method_version": record.get("count_method_version"),
            "Count_policy": record.get("count_policy") or "unrecorded (legacy)",
            "Evidence_needs_refresh": record.get("evidence_needs_refresh", False),
            "Unresolved_papers": record.get("unresolved_papers", 0),
            "Count_status": ("Conflicting counts" if conflicts else "Incomplete counts" if missing
                             else "Identity review" if identity_review else "Evidence review"
                             if record.get("evidence_needs_refresh") or record.get("unresolved_papers")
                             else "No arithmetic flags"),
            "Review_notes": " | ".join(flag["Issue"] for flag in flags),
            **{f"CNS_{y}": cby.get(y) for y in years},
            **{f"nonCNS_{y}": nby.get(y) for y in years},
            **{f"field_{y}": record.get("fieldtier_by_year", {}).get(y) for y in years},
            **{f"elife_{y}": record.get("elife_by_year", {}).get(y) for y in years},
        })
    frame = pd.DataFrame(rows)
    return frame, years, data, issues


def csv_bytes(frame):
    exported = frame.drop(columns=["Search_text", "UI_key"], errors="ignore").copy()
    for column in exported.select_dtypes(include="object"):
        exported[column] = exported[column].map(
            lambda value: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value)
    return exported.to_csv(index=False).encode("utf-8")


def filter_awards(frame, selected):
    wanted = set(selected)
    return frame[frame["Awards"].str.split(", ").map(lambda awards: bool(wanted.intersection(awards)))]


def display_count(value):
    return "n/a" if pd.isna(value) else int(value)


def filter_tags(frame, selected, column):
    wanted = set(selected)
    return frame[frame[column].map(lambda tags: bool(wanted.intersection(tags)))] if selected else frame


def researcher_label(key):
    row = df.loc[df["UI_key"] == key].iloc[0]
    identity = row["Researcher_ID"] or f"{key} (temporary legacy key)"
    return f"{row['Name']} — {row['Institution']} · {identity}"


def retain_choices(key, options, default=()):
    current = st.session_state.get(key, list(default))
    st.session_state[key] = [value for value in current if value in options]
    return [value for value in current if value not in options]


def window_columns(frame):
    return frame.assign(Window_start=int(YEARS[0]), Window_end=int(YEARS[-1]), Selected_years=", ".join(YEARS))


def paper_frame(records):
    rows = []
    for record in records:
        for field, default in (("publications", "included"), ("excluded_publications", "unresolved")):
            for paper in record.get(field, []):
                rows.append({
                    **paper, "researcher_id": record.get("researcher_id"), "researcher": record["name"],
                    "decision": paper.get("decision", default),
                    "reason": paper.get("reason") or paper.get("match") or "Unrecorded legacy decision reason",
                })
    return window_columns(pd.DataFrame(rows))


def included_comparison_frame(records):
    by_pmid = {}
    metadata_fields = ("year", "journal", "title", "last_author", "doi", "publication_types",
                       "topics", "methods", "organisms", "tag_source", "tag_evidence")
    for index, record in enumerate(records):
        researcher_id = record.get("researcher_id")
        match_key = researcher_id or f"temporary-legacy-row-{index}"
        label = f"{record['name']} · {match_key}"
        for paper in record.get("publications", []):
            pmid = str(paper["pmid"])
            if pmid not in by_pmid:
                by_pmid[pmid] = {
                    **paper, "pmid": pmid, "matched_researcher_ids": [], "matched_researchers": [],
                    "match_reasons": {}, "metadata_conflicts": [],
                }
            included = by_pmid[pmid]
            if researcher_id and researcher_id not in included["matched_researcher_ids"]:
                included["matched_researcher_ids"].append(researcher_id)
            if label not in included["matched_researchers"]:
                included["matched_researchers"].append(label)
            included["match_reasons"][match_key] = paper.get("reason") or paper.get("match") or "unrecorded"
            for field in metadata_fields:
                if included.get(field) != paper.get(field) and field not in included["metadata_conflicts"]:
                    included["metadata_conflicts"].append(field)
    return window_columns(pd.DataFrame(by_pmid.values()))


def doi_link(value):
    if pd.isna(value) or not str(value).strip():
        return None
    doi = str(value).strip()
    return doi if doi.startswith(("https://doi.org/", "http://doi.org/")) else "https://doi.org/" + doi


def render_paper_comparison(records, key, included_only=False):
    papers = included_comparison_frame(records) if included_only else paper_frame(records)
    if papers.empty:
        st.info("No saved included-paper evidence is available for comparison in this window." if included_only
                else "No saved paper evidence is available for paper-level comparison in this window.")
        return
    papers = papers.reset_index(drop=True)
    if included_only:
        options = papers["pmid"].tolist()
        labels = {paper["pmid"]: f"PMID {paper['pmid']} · {paper['year']} · {paper['title']}"
                  for _, paper in papers.iterrows()}
    else:
        options = [
            f"{paper.get('researcher_id') or paper['researcher']}:{paper['pmid']}:{paper['decision']}:{index}"
            for index, paper in papers.iterrows()
        ]
        labels = {
            option: f"{papers.iloc[index]['researcher']} · {papers.iloc[index]['researcher_id'] or 'legacy paper row ' + str(index + 1)} · "
                    f"PMID {papers.iloc[index]['pmid']} · "
                    f"{papers.iloc[index]['decision']} · {papers.iloc[index]['title']}"
            for index, option in enumerate(options)
        }
    retain_choices(key, options)
    chosen = st.multiselect("Included papers to compare (2–4 distinct PMIDs)" if included_only
                            else "Papers to compare (up to 4)", options, format_func=labels.get, max_selections=4, key=key)
    if included_only and len(chosen) < 2:
        st.info("Select 2–4 distinct included PMIDs from these researchers. Excluded/unresolved candidates are not "
                "offered here; inspect them in Researcher detail.")
        return
    if not chosen:
        st.caption("Select saved included or excluded/unresolved papers to inspect their metadata and decision reasons.")
        return
    selected = papers.iloc[[options.index(option) for option in chosen]].copy()
    selected["doi_url"] = selected["doi"].map(doi_link) if "doi" in selected else None
    identity_fields = (["matched_researcher_ids", "matched_researchers", "match_reasons", "metadata_conflicts"]
                       if included_only else ["researcher", "researcher_id", "decision", "reason"])
    fields = ["pmid", "title", "journal", "year", "last_author", "publication_types", "tier",
              "topics", "methods", "organisms", "tag_source", "tag_evidence", *identity_fields, "doi", "url", "doi_url"]
    comparison = selected.reindex(columns=fields).copy()
    for column in comparison:
        comparison[column] = comparison[column].map(
            lambda value: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list))
            else "n/a" if pd.isna(value) else str(value))
    comparison = comparison.T
    comparison.columns = [f"Paper {index + 1} · PMID {pmid}" for index, pmid in enumerate(selected["pmid"])]
    st.dataframe(comparison.rename_axis("Metadata"), use_container_width=True)
    if included_only and selected["metadata_conflicts"].map(bool).any():
        st.warning("Some saved records disagree on metadata for a selected PMID. The first saved metadata is shown; "
                   "metadata_conflicts lists differing fields. Verify against the linked article.")
    for _, paper in selected.iterrows():
        context = "" if included_only else f" · {paper['researcher']} · {paper['decision']}"
        st.link_button(f"PubMed · PMID {paper['pmid']}{context}", paper["url"])
        if pd.notna(paper["doi_url"]):
            st.link_button(f"DOI · PMID {paper['pmid']}{context}", paper["doi_url"])
    st.caption("Last author is the saved matched name, not a full byline or verified corresponding author. "
               "Metadata comparison is not an assessment of paper quality. Tags are rule-inferred, not curated expertise.")
    st.download_button("Download selected paper comparison CSV", csv_bytes(selected),
                       f"paper_comparison_{PERIOD}.csv", "text/csv", key=f"{key}_download")


def render_profile(record, row):
    profile = record.get("profile") or {}
    st.subheader("Researcher profile and sources")
    st.caption("Profile claims retain their source status and access dates; changing publication years does not "
               "turn current profile facts into a historical appointment census.")
    if not profile:
        st.warning("Legacy record: no source-backed profile is attached. The row-based selector is a temporary UI key, "
                   "not a persistent researcher identity. Institution, cohort and award labels are unreviewed.")
    else:
        st.caption(f"Stable researcher ID: {row['Researcher_ID']} · Identity: {row['Identity_status']}")
    st.markdown(f"**Current institution:** {row['Current_institution'] or 'unknown'} · "
                f"**Roster / institution label:** {row['Institution']} · {row['Institution_status']}")
    hhmi = profile.get("hhmi", {})
    st.markdown(f"**HHMI status:** {hhmi.get('value') or 'unknown'} · {hhmi.get('status', 'unknown')}. "
                "A legacy HHMI group label does not establish current membership.")
    career_columns = st.columns(3)
    career_columns[0].metric("Independent lab start", display_count(row["Lab_start_year"]))
    career_columns[1].metric("Active lab years in window", display_count(row["Active_years_in_window"]))
    career_columns[2].metric("CNS / active lab year",
                             "n/a" if pd.isna(row["CNS_per_active_year"]) else f"{row['CNS_per_active_year']:.2f}")
    if row["Lab_start_verified"]:
        st.caption(f"Independent lab start: {display_count(row['Lab_start_year'])} · source-backed. "
                   f"Lab age as of {CAREER_YEAR}: {display_count(row['Lab_age'])}. "
                   "The activity-adjusted rate includes only selected years at or after this sourced start.")
    else:
        st.info("Independent lab start: unknown / not source-backed. No activity-adjusted publication rate is calculated. "
                "ORCID employment, faculty appointments and first-paper dates do not establish lab independence.")
    st.caption(f"Faculty appointment: {display_count(row['Faculty_appointment_year'])} · "
               f"{row['Faculty_appointment_status']}. This is a separate claim, not an independent-lab start.")
    st.caption(
        f"Career proxies (not verified independent-lab starts): ORCID employment "
        f"{display_count(row['ORCID_employment_year'])}; first senior/last-author paper "
        f"{display_count(row['First_senior_paper'])}. Career age / proxy as of {CAREER_YEAR}: "
        f"{display_count(row['Lab_age'])}; basis: {row['Lab_age_source'] or 'unknown'}. "
        f"Legacy career-stage label: {row['Career_stage'] or 'unknown'} (not reverified)."
    )
    if profile:
        st.markdown("**Affiliation history**")
        affiliations = []
        for item in profile.get("affiliations", []):
            current = (item.get("current") is True and item.get("status") == "source-backed"
                       and item["institution"] in (row["Current_institution"] or "").split("; "))
            current_status = ("source-backed current" if current else "historical" if item.get("current") is False
                              else "reported current (not established)" if item.get("current") else "unknown")
            for source in item.get("sources") or [{}]:
                affiliations.append({
                    "Institution": item["institution"], "Start": str(display_count(item.get("start_year"))),
                    "End": str(display_count(item.get("end_year"))), "Current status": current_status,
                    "Claim status": item["status"], "URL": source.get("url", ""),
                    "Accessed": source.get("accessed", ""), "Note": item.get("note", ""),
                })
        if affiliations:
            st.dataframe(pd.DataFrame(affiliations), column_config={"URL": st.column_config.LinkColumn("Source")},
                         use_container_width=True, hide_index=True)
        else:
            st.info("Affiliation history is unknown; no current institution is inferred.")
        evidence = pd.DataFrame(profile_evidence(profile))
        evidence["Value"] = evidence["Value"].map(lambda value: "unknown" if pd.isna(value) else str(value))
        st.markdown("**Claim provenance — identity, aliases, ORCID, career, HHMI and awards**")
        st.dataframe(evidence, column_config={"URL": st.column_config.LinkColumn("Source URL")},
                     use_container_width=True, hide_index=True)
        exported = window_columns(evidence.assign(Researcher_ID=row["Researcher_ID"], Name=row["Name"]))
        st.download_button("Download profile source claims CSV", csv_bytes(exported),
                           f"profile_sources_{row['Researcher_ID']}_{PERIOD}.csv", "text/csv")
    elif row["Awards"]:
        st.caption(f"Legacy award/cohort labels (unreviewed; sources unrecorded): {row['Awards']}")


def render_evidence(record, row):
    st.subheader("Counted-paper evidence")
    st.caption(f"Model: {row['Publication_model']} · Count source: {row['Count_source']} · "
               f"Retrieved: {record.get('count_fetched_at') or 'unrecorded'} · "
               f"Method: {record.get('count_method_version') or 'legacy/unversioned'} · "
               f"Source coverage: {row['Source_coverage']} · Selected-window coverage: {row['Annual_coverage']}")
    st.caption("Included papers represent heuristic last-author matches, not verified corresponding authorships. "
               "Excluded and unresolved candidates do not contribute to any total.")
    if row["Publication_model"] == "unresolved-identity":
        st.info("This identity cannot yet be resolved from full given names or a sourced ORCID. "
                "Legacy aggregates are archived and are not used as established publication counts.")
    elif row["Publication_model"] != "unified-papers":
        st.warning("Legacy aggregate counts: any attached CNS/field/eLife evidence may not explain the separately "
                   "collected non-CNS totals. It is not a unified all-journal paper inventory.")
    if record.get("evidence_needs_refresh"):
        st.warning("Evidence needs refresh: identity/alias matching inputs changed after this saved query. "
                   "No refresh is performed by this read-only app.")
    if record.get("count_policy"):
        with st.expander("Saved count policy"):
            if isinstance(record["count_policy"], (dict, list)):
                st.json(record["count_policy"])
            else:
                st.write(record["count_policy"])
    papers = paper_frame([record])
    for decision, title in (("included", "Included papers"), ("excluded", "Excluded / unresolved candidates")):
        st.markdown(f"**{title} — {PERIOD}**")
        if papers.empty:
            selected = papers
        else:
            selected = papers[papers["decision"].eq("included") if decision == "included"
                              else ~papers["decision"].eq("included")]
        if not selected.empty:
            columns = ["year", "pmid", "journal", "tier", "title", "publication_types", "last_author", "decision", "reason",
                       "given_name_warning", "topics", "methods", "organisms", "tag_source", "tag_evidence", "doi", "url"]
            st.dataframe(selected.reindex(columns=columns),
                         column_config={"url": st.column_config.LinkColumn("PubMed / source")},
                         use_container_width=True, hide_index=True)
            if selected["year"].isna().any():
                st.caption("Undated review candidates remain visible because they cannot be assigned to a publication "
                           "window. They are not counted as publications in this or any year.")
            label = "Download counted-paper CSV" if decision == "included" else "Download excluded / unresolved CSV"
            st.download_button(label, csv_bytes(selected), f"{decision}_papers_{PERIOD}.csv", "text/csv")
        elif decision == "excluded":
            st.info("No saved excluded or unresolved candidates in this window; absence is not proof of exhaustive review.")
        elif (record.get("count_method_version") and record.get("count_fetched_at")
              and all(record.get(f"{key}_total") == 0 for key in
                      (("cns", "noncns", "fieldtier", "elife") if row["Publication_model"] == "unified-papers"
                       else ("cns", "fieldtier", "elife")))):
            st.info("This recount found no qualifying papers under its recorded matching rules in the selected window; "
                    "that does not prove the researcher had no publications.")
        else:
            st.info("This record has no saved counted-paper list in this window. Unavailable evidence is not zero publications.")
    st.markdown("**Paper-level comparison**")
    render_paper_comparison([record], "detail_papers")
    if record.get("count_query"):
        with st.expander("Exact recount query"):
            st.caption("This is the saved source query and its original coverage, not a fresh query for the selected window.")
            st.code(record["count_query"])
        st.link_button("Open recount query in PubMed",
                       "https://pubmed.ncbi.nlm.nih.gov/?" + urlencode({"term": record["count_query"]}))


try:
    stat = DATA.stat()
    revision = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
    published = read_snapshot(str(DATA), revision)
except (OSError, ValueError) as error:
    st.error(f"Cannot load the publication snapshot: {error}")
    st.stop()

st.sidebar.header("Publication window")
published_years = published["years"]
if len(published_years) == 1:
    start_year = end_year = published_years[0]
    st.sidebar.caption(f"Only {start_year} is published; this is a single-year snapshot.")
else:
    saved_window = st.session_state.get("publication_window", (published_years[0], published_years[-1]))
    if (not isinstance(saved_window, (tuple, list)) or len(saved_window) != 2
            or any(year not in published_years for year in saved_window) or saved_window[0] > saved_window[1]):
        st.session_state["publication_window"] = (published_years[0], published_years[-1])
    start_year, end_year = st.sidebar.select_slider(
        "Publication window", options=published_years, value=(published_years[0], published_years[-1]),
        key="publication_window")
try:
    df, YEARS, snapshot, issue_rows = load(str(DATA), revision, start_year, end_year)
except (OSError, ValueError) as error:
    st.error(f"Cannot load the publication snapshot: {error}")
    st.stop()

N_YEARS = len(YEARS)
PERIOD = YEARS[0] if N_YEARS == 1 else f"{YEARS[0]}–{YEARS[-1]}"
CAREER_YEAR = snapshot.get("career_reference_year", int(YEARS[-1]))
records_by_key = {selection_key(record, index): record for index, record in enumerate(snapshot["records"])}
st.title("🧠 Neuroscience CNS Publication Explorer")
st.caption(
    f"PubMed last-author matches in Cell / Nature / Science and other journals, {PERIOD}. "
    "These are heuristic publication counts, not verified corresponding-author counts or a measure of researcher quality."
)
st.caption(
    f"Snapshot built: {snapshot.get('generated', 'unrecorded')} · Selected publication years: {', '.join(YEARS)} "
    f"({N_YEARS} {'year' if N_YEARS == 1 else 'years'}) · Career reference year: {CAREER_YEAR}. "
    "A build date is not a source-retrieval date. All counts, trajectories and exports use this selected window."
)
if snapshot.get("partial_calendar_year") or (published.get("partial_calendar_year")
                                            and published_years[-1] in snapshot["years"]):
    st.warning(f"{YEARS[-1]} is a partial calendar year in this snapshot. Counts stop at each source's retrieval date "
               "and are not annualized; do not compare them as if the year were complete.")
if N_YEARS != int(YEARS[-1]) - int(YEARS[0]) + 1:
    st.warning("Some calendar years are not published in the snapshot. Only the listed years are selectable and "
               "included in window averages; unpublished years are not zero-filled.")
with st.expander("Methodology and limitations"):
    st.markdown(
        "**Identity:** registry IDs remain stable after display-name changes; source-backed profile claims are "
        "distinguished from unknown or unreviewed imports. Full-name, ORCID and affiliation matching can still "
        "confuse namesakes or miss movers. Legacy rows have only temporary UI keys. Institutions, Group, career-stage "
        "and award labels are not a complete or necessarily current census.\n\n"
        "**Authorship:** last position does not establish corresponding authorship. "
        "[ICMJE distinguishes authorship order from the corresponding author's role]"
        "(https://www.icmje.org/recommendations/browse/roles-and-responsibilities/defining-the-role-of-authors-and-contributors.html).\n\n"
        "**Career dates:** only a source-backed independent-lab start supports an activity-adjusted rate. "
        "ORCID employment, a faculty appointment and first senior/last-author papers are distinct claims, not verified "
        "lab starts. First papers can precede or follow independence; they are not guaranteed bounds.\n\n"
        "**Counts:** n/a or empty numeric cells mean unavailable, not zero. Known annual values remain visible even "
        "when the complete-window total is unavailable. Neuron/Nature Neuroscience and eLife are subsets of non-CNS. "
        "Unified counts derive every tier, including other non-CNS journals, from the same included-paper list. "
        "Legacy aggregate sources can differ in date and author-matching policies. Window averages divide by selected "
        "publication years, not lab activity, and incomplete calendar years are not annualized.\n\n"
        "**Discovery tags:** topics, methods and organisms are rule-inferred from saved included-paper titles, MeSH "
        "headings and keywords. Coverage is limited and false positives/negatives are possible. Untagged researchers "
        "are not assumed to lack that expertise. Tags are recomputed from papers inside the selected window.\n\n"
        "**Interpretation:** use this for discovery, not journal-based judgments about scientists. "
        "[DORA's research-assessment recommendations](https://sfdora.org/read/)."
    )
if df.empty:
    st.info("The snapshot contains no researcher records.")
    st.stop()

st.sidebar.header("Filters")
groups = st.sidebar.multiselect("Group", sorted(df["Group"].unique()), default=sorted(df["Group"].unique()), key="groups")
stages = st.sidebar.multiselect("Career stage", sorted(df["Career_stage"].dropna().unique()), key="stages")
insts = st.sidebar.multiselect("Institution", sorted(df["Institution"].unique()), key="institutions")
st.sidebar.caption("Institution includes sourced current appointments and unreviewed/historical roster labels; "
                   "see Institution_status. Group and career stage can be legacy cohort labels.")
award_opts = sorted({a for value in df["Awards"] for a in value.split(", ") if a})
awards_sel = st.sidebar.multiselect("Award", award_opts, key="awards")
name_q = st.sidebar.text_input("Search name / institution / field", key="search",
                               help="Also matches recorded name aliases, bibliographic forms, and stable researcher IDs.")
tag_selections = {}
for column, label in (("Topics", "Topic"), ("Methods", "Method"), ("Organisms", "Organism")):
    options = sorted({tag for tags in df[column] for tag in tags})
    key = column.lower()
    removed = retain_choices(key, options)
    if removed:
        st.sidebar.info(f"{label} selection cleared because no included papers in this window carry: {', '.join(removed)}.")
    tag_selections[column] = st.sidebar.multiselect(label, options, key=key)
st.sidebar.caption("Tags are rule-inferred from included papers in this window, not verified expertise. "
                   "Limited coverage: untagged people stay visible unless a tag is selected. "
                   "OR within each category; AND across topic, method and organism.")
maximum = int(df["CNS_total"].max()) if df["CNS_total"].notna().any() else 0
min_cns = st.sidebar.slider("Min CNS total", 0, max(1, maximum), 0, key="min_cns")
min_cns_years = st.sidebar.slider("Min CNS years covered", 0, N_YEARS, 0, key="min_cns_years")
max_lab_age = st.sidebar.slider(f"Max career age / proxy as of {CAREER_YEAR} (0 = ignore)", 0, 25, 0, key="max_lab_age")
statuses = st.sidebar.multiselect("Count status", sorted(df["Count_status"].unique()), key="count_statuses")
core_only = st.sidebar.checkbox("Only 'core' neuroscience labels", value=False, key="core_only")

f = df[df["Group"].isin(groups)].copy()
if stages:
    f = f[f["Career_stage"].isin(stages)]
if insts:
    f = f[f["Institution"].isin(insts)]
if awards_sel:
    f = filter_awards(f, awards_sel)
for column, selected in tag_selections.items():
    f = filter_tags(f, selected, column)
if name_q.strip():
    f = f[f["Search_text"].str.contains(search_text(name_q.strip()), regex=False, na=False)]
if min_cns:
    f = f[f["CNS_total"] >= min_cns]
if min_cns_years:
    f = f[f["CNS_years_covered"] >= min_cns_years]
if max_lab_age:
    f = f[f["Lab_age"].notna() & f["Lab_age"].between(0, max_lab_age)]
if statuses:
    f = f[f["Count_status"].isin(statuses)]
if core_only:
    f = f[f["Neuro_confidence"].str.startswith("core", na=False)]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Researchers", len(f))
c2.metric("Award/cohort labels", int((f["N_awards"] > 0).sum()))
c3.metric("Conflicting counts", int((f["Count_status"] == "Conflicting counts").sum()))
c4.metric("Missing non-CNS", int(f["nonCNS_total"].isna().sum()))
if f["Coverage_status"].eq("Incomplete selected window").any():
    st.info(f"{int(f['Coverage_status'].eq('Incomplete selected window').sum())} selected researchers lack complete "
            f"count coverage for {PERIOD}. Window totals and rates with missing years are n/a, not zero; "
            "available annual values are retained with gaps.")
if f["Publication_model"].eq("legacy-aggregates").any():
    st.caption(f"{int(f['Publication_model'].eq('legacy-aggregates').sum())} selected records use legacy aggregates, "
               "not unified all-journal paper evidence. Source and identity review status remain visible.")
tagged = int(f[["Topics", "Methods", "Organisms"]].apply(
    lambda row: any(bool(tags) for tags in row), axis=1).sum())
st.caption(f"Discovery tag coverage in this window: {tagged}/{len(f)} selected researchers have at least one "
           "rule-inferred included-paper tag. Missing tags mean unclassified, not absence of a topic or method.")
view = st.radio("View", ["Table", "Rankings", "Researcher detail", "CNS vs non-CNS", "Rising stars", "Data quality", "Compare"],
                horizontal=True, key="view")
if f.empty:
    st.info("No researchers match the current filters. Clear or relax a sidebar filter.")
    if view != "Data quality":
        st.stop()

if view == "Table":
    sort_col = st.selectbox("Sort by", ["CNS_total", "nonCNS_total", "CNS_years_covered", "Name"])
    show = f.sort_values(sort_col, ascending=(sort_col == "Name"), na_position="last")
    columns = ["Name", "Researcher_ID", "Group", "Institution", "Institution_status", "Identity_status",
               "Field", "Topics", "Methods", "Organisms", "Awards", "CNS_total", "NeuronNatNeuro_total",
               "eLife_total", "nonCNS_total", "Count_status", "CNS_gap_years", "Career_stage",
               "Lab_start_year", "Lab_start_status", "Faculty_appointment_year", "Faculty_appointment_status",
               "Lab_age", "Lab_age_source", "Publication_model",
               "Annual_coverage", "Count_source"]
    st.dataframe(show[columns], use_container_width=True, height=560)
    st.caption("No arithmetic flags does not mean verified. Open Data quality for review notes and missing provenance.")
    st.download_button("Download filtered CSV", csv_bytes(show), f"filtered_neuro_stats_{PERIOD}.csv", "text/csv")

elif view == "Rankings":
    st.caption("Descriptive counts within this selected cohort; not rankings of research quality.")
    metric = st.radio("Metric", ["CNS_total", "NeuronNatNeuro_total", "eLife_total", "nonCNS_total", "CNS_avg_per_yr"],
                      horizontal=True)
    topn = st.slider("Show top N", 5, 60, 25)
    ranked = f.dropna(subset=[metric]).sort_values(metric, ascending=False).head(topn)
    if ranked.empty:
        st.info("This metric is unavailable for the current selection.")
    else:
        ranked = ranked.assign(Researcher=ranked["UI_key"].map(researcher_label))
        fig = px.bar(ranked, x=metric, y="Researcher", color="Group", orientation="h",
                     hover_data=["Institution", "Field", "Count_status", "Publication_model", "Annual_coverage"],
                     height=max(400, 22 * len(ranked)))
        fig.update_layout(yaxis={"categoryorder": "total ascending"}, legend_title="")
        st.plotly_chart(fig, use_container_width=True)
    st.subheader("Affiliation-label summary")
    st.caption("Labels may be historical, combined, or aliases; these are not complete institutional publication totals. "
               "Records without a complete CNS count are omitted, not zero-filled.")
    inst_sum = (f.dropna(subset=["CNS_total"]).groupby("Institution")
                .agg(researchers=("Name", "count"), CNS_total=("CNS_total", "sum"))
                .reset_index().sort_values("CNS_total", ascending=False))
    if not inst_sum.empty:
        st.plotly_chart(px.bar(inst_sum, x="Institution", y="CNS_total", hover_data=["researchers"], height=420),
                        use_container_width=True)

elif view == "Researcher detail":
    options = f.sort_values(["Name", "UI_key"])["UI_key"].tolist()
    previous = st.session_state.get("researcher_id")
    if previous not in options:
        st.session_state.pop("researcher_id", None)
    chosen = st.selectbox("Researcher", options, key="researcher_id", format_func=researcher_label,
                          index=options.index(previous) if previous in options else 0)
    row = f.loc[f["UI_key"] == chosen].iloc[0]
    record = records_by_key[chosen]
    st.markdown(f"**{row['Name']}** — {row['Institution']} · _{row['Field']}_ · **{row['Group']}**")
    if row["Awards"]:
        st.markdown(f"🏅 **Award/cohort labels:** {row['Awards']} (claim sources below)")
    for column, label, key in zip(st.columns(4),
                                  ["CNS", "Neuron + Nat Neurosci", "eLife", "non-CNS (includes subsets)"],
                                  ["CNS_total", "NeuronNatNeuro_total", "eLife_total", "nonCNS_total"]):
        column.metric(label, display_count(row[key]))
    fig = go.Figure()
    for prefix, label, color in (("CNS", "CNS", "#d62728"), ("field", "Neuron + Nat Neurosci", "#9467bd"),
                                 ("elife", "eLife", "#2ca02c"), ("nonCNS", "non-CNS (includes subsets)", "#c7c7c7")):
        values = [None if pd.isna(row[f"{prefix}_{y}"]) else int(row[f"{prefix}_{y}"]) for y in YEARS]
        fig.add_bar(x=YEARS, y=values, name=label, marker_color=color)
    fig.update_layout(barmode="group", height=440, xaxis_title="Year", yaxis_title="Matched last-author papers")
    st.plotly_chart(fig, use_container_width=True)
    st.caption(f"Years without a matched CNS paper: {row['CNS_gap_years']}. "
               "Non-CNS includes the two specialist-journal series and other journals; do not add all four series. "
               "Empty bars represent n/a, not zero.")
    render_profile(record, row)
    flags = record_issues(record, YEARS)
    if flags:
        st.dataframe(pd.DataFrame(flags), use_container_width=True, hide_index=True)
    render_evidence(record, row)

elif view == "Compare":
    st.subheader("Compare researchers")
    st.caption("Choose 2–4 filtered researchers by stable ID. Compare publication metadata and coverage, "
               "not research quality. All sidebar filters and the selected publication window apply.")
    options = f.sort_values(["Name", "UI_key"])["UI_key"].tolist()
    retain_choices("compare_researcher_ids", options, options[:2])
    chosen = st.multiselect("Researchers to compare (2–4)", options, key="compare_researcher_ids",
                            format_func=researcher_label, max_selections=4)
    if len(chosen) < 2:
        st.info("Select at least two researchers from the filtered cohort to compare; relax filters if needed.")
    else:
        comparison = f.set_index("UI_key", drop=False).loc[chosen]
        if comparison["Publication_model"].nunique() > 1:
            st.warning("Mixed legacy/unified counts: these records do not share a single paper-counting model. "
                       "Legacy non-CNS aggregates may use different matching and date policies.")
        elif comparison["Publication_model"].eq("legacy-aggregates").any():
            st.warning("These are legacy aggregate counts, not a shared unified paper inventory.")
        if comparison["Identity_status"].ne("source-backed").any():
            st.warning("Unreviewed identities are included. A stable registry ID or a name match is not independent "
                       "identity verification; review profile sources before interpreting differences.")
        if comparison["Coverage_status"].eq("Incomplete selected window").any():
            st.warning("Selected-window coverage is incomplete for at least one comparison record. Missing totals "
                       "and rates are n/a; known annual points are preserved without connecting across missing years.")
        if comparison["Evidence_needs_refresh"].any():
            st.warning("Some saved evidence predates profile matching changes and needs refresh; the app does not fetch updates.")
        columns = ["Name", "Researcher_ID", "Institution", "Institution_status", "Identity_status", "Publication_model",
                   "CNS_total", "nonCNS_total", "NeuronNatNeuro_total", "eLife_total",
                   "CNS_avg_per_yr", "nonCNS_avg_per_yr", "CNS_per_active_year", "Active_years_in_window",
                   "Lab_start_year", "Lab_start_status", "Faculty_appointment_year", "Faculty_appointment_status",
                   "Annual_coverage", "Source_coverage",
                   "Count_fetched_at", "Count_status", "Evidence_needs_refresh", "Unresolved_papers"]
        st.dataframe(comparison[columns], use_container_width=True, hide_index=True)
        st.caption(f"Window rates divide by {N_YEARS} selected publication years; partial years are not annualized. "
                   "CNS_per_active_year is n/a without a source-backed independent-lab start. "
                   "Neuron/Nature Neuroscience and eLife are already included in non-CNS.")
        st.download_button("Download researcher comparison CSV", csv_bytes(comparison),
                           f"researcher_comparison_{PERIOD}.csv", "text/csv")
        metric = st.radio("Annual trajectory", ["CNS", "non-CNS", "Neuron + Nat Neurosci", "eLife"],
                          horizontal=True, key="compare_metric")
        prefixes = {"CNS": "CNS", "non-CNS": "nonCNS", "Neuron + Nat Neurosci": "field", "eLife": "elife"}
        annual_rows = []
        fig = go.Figure()
        for key, row in comparison.iterrows():
            values = [None if pd.isna(row[f"{prefixes[metric]}_{year}"]) else int(row[f"{prefixes[metric]}_{year}"])
                      for year in YEARS]
            fig.add_scatter(x=YEARS, y=values, mode="lines+markers", name=researcher_label(key), connectgaps=False)
            for year in YEARS:
                annual_rows.append({
                    "Researcher_ID": row["Researcher_ID"], "Name": row["Name"], "Year": int(year),
                    **{label: row[f"{prefix}_{year}"] for label, prefix in prefixes.items()},
                    "Publication_model": row["Publication_model"], "Identity_status": row["Identity_status"],
                })
        fig.update_layout(height=430, xaxis_title="Selected publication year",
                          yaxis_title=f"{metric} last-author matches", xaxis={"type": "category"})
        st.plotly_chart(fig, use_container_width=True)
        st.download_button("Download comparison annual trajectories CSV", csv_bytes(window_columns(pd.DataFrame(annual_rows))),
                           f"comparison_annual_{PERIOD}.csv", "text/csv")
        st.markdown("**Paper-level comparison**")
        st.caption("Compare 2–4 distinct included PMIDs from the selected, filtered researchers in this publication window. "
                   "Shared PMIDs appear once and retain every matching registry ID; this does not resolve identity conflicts. "
                   "Legacy matches without a registry ID retain explicitly temporary row labels.")
        render_paper_comparison([records_by_key[key] for key in chosen], "compare_papers", included_only=True)

elif view == "CNS vs non-CNS":
    scatter = f.dropna(subset=["CNS_total", "nonCNS_total"]).copy()
    if scatter.empty:
        st.info("No selected researchers have both CNS and non-CNS counts.")
    else:
        scatter["Marker_size"] = scatter["CNS_total"].clip(lower=1)
        fig = px.scatter(scatter, x="nonCNS_total", y="CNS_total", color="Group", hover_name="Name",
                         hover_data=["Researcher_ID", "Institution", "Field", "Count_status", "Publication_model",
                                     "Annual_coverage"], size="Marker_size", size_max=22, height=560)
        fig.add_hline(y=N_YEARS / 2, line_dash="dot", annotation_text="0.5 CNS/yr")
        fig.add_hline(y=N_YEARS, line_dash="dot", annotation_text="1 CNS/yr")
        fig.update_layout(xaxis_title=f"non-CNS last-author matches ({PERIOD})",
                          yaxis_title=f"CNS last-author matches ({PERIOD})")
        st.plotly_chart(fig, use_container_width=True)
    st.caption(f"Excluded {len(f) - len(scatter)} records with missing counts. Zero-CNS records remain visible. "
               "Conflicting records are labeled in the hover; exclude them using Count status.")

elif view == "Rising stars":
    st.subheader("🌟 Early-career candidates and award cohorts")
    st.caption(f"All sidebar filters apply here too. Award/cohort labels can be historical or unreviewed. "
               f"Only source-backed lab starts establish independence; other career dates are proxies as of {CAREER_YEAR}.")
    rs = f[f["Group"].isin(["rising-star", "early-career awardee"]) | (f["N_awards"] > 0)].copy()
    ca, cb = st.columns(2)
    max_age = ca.slider("Max career age / proxy (yrs)", 3, 20, 12, key="rs_age")
    include_unknown = cb.checkbox("Include unknown career ages", value=True)
    age_mask = rs["Lab_age"].between(0, max_age)
    if include_unknown:
        age_mask |= rs["Lab_age"].isna()
    rs = rs[age_mask].sort_values(["Lab_age", "CNS_total"], ascending=[True, False], na_position="last")
    st.metric("Candidates / awardees shown", len(rs))
    columns = ["Name", "Researcher_ID", "Institution", "Institution_status", "Awards", "Lab_start_year", "Lab_start_status",
               "Faculty_appointment_year", "Faculty_appointment_status",
               "ORCID_employment_year", "First_senior_paper", "Lab_age", "Lab_age_source", "CNS_total", "nonCNS_total",
               "Career_stage", "Count_status", "Identity_status", "Publication_model", "Annual_coverage",
               "Topics", "Methods", "Organisms"]
    st.dataframe(rs[columns], use_container_width=True, height=460)
    plot = rs.copy()
    plot["Start"] = CAREER_YEAR - pd.to_numeric(plot["Lab_age"])
    plot["Date_basis"] = plot["Lab_start_verified"].map({True: "Source-backed lab start", False: "Unverified career proxy"})
    plot = plot.dropna(subset=["Start", "CNS_total"])
    if not plot.empty:
        fig = px.scatter(plot, x="Start", y="CNS_total", color="Institution", symbol="Date_basis",
                         hover_name="Name", height=460,
                         hover_data=["Researcher_ID", "Awards", "Career_stage", "Count_status", "Lab_age_source"],
                         labels={"Start": "Sourced independent-lab start / unverified career proxy",
                                 "CNS_total": f"CNS matches ({PERIOD})"})
        st.plotly_chart(fig, use_container_width=True)
    st.caption(f"{len(rs) - len(plot)} candidates lack a dated career claim/proxy or a complete CNS count and are "
               "not plotted; they remain in the table.")
    st.download_button("Download rising stars / awardees CSV", csv_bytes(rs), f"rising_stars_awardees_{PERIOD}.csv", "text/csv")

elif view == "Data quality":
    st.subheader("Data-quality review queue")
    st.caption("Flags identify missing provenance and internal conflicts, not which source is correct. "
               "No flag is an endorsement of an author's identity, career stage, or count.")
    coverage = published.get("coverage")
    if coverage:
        st.caption("Snapshot-wide registry metadata (before sidebar filters): "
                   f"{coverage.get('registered', 'unknown')} registered; "
                   f"{coverage.get('unified_evidence', 'unknown')} with unified evidence; "
                   f"{coverage.get('source_backed_identities', 'unknown')} source-backed identities; "
                   f"{coverage.get('source_backed_lab_starts', 'unknown')} source-backed independent-lab starts; "
                   f"{coverage.get('source_backed_award_claims', 'unknown')} source-backed award claims.")
    else:
        st.caption("Legacy snapshot: registry-wide source-coverage metadata is unavailable.")
    coverage_columns = st.columns(4)
    coverage_columns[0].metric("Selected registered IDs", int(f["Researcher_ID"].notna().sum()))
    coverage_columns[1].metric("Selected unified evidence", int(f["Publication_model"].eq("unified-papers").sum()))
    coverage_columns[2].metric("Source-backed identities", int(f["Identity_status"].eq("source-backed").sum()))
    coverage_columns[3].metric("Source-backed lab starts", int(f["Lab_start_verified"].sum()))
    st.markdown("**Selected cohort coverage and source-review gaps**")
    gaps = pd.DataFrame([
        {"Review area": "Incomplete publication-window coverage", "Researchers": int(f["Coverage_status"].eq("Incomplete selected window").sum())},
        {"Review area": "Identity not source-backed", "Researchers": int(f["Identity_status"].ne("source-backed").sum())},
        {"Review area": "Independent-lab start unknown / unreviewed", "Researchers": int((~f["Lab_start_verified"]).sum())},
        {"Review area": "Current institution not source-backed", "Researchers": int(f["Current_institution"].isna().sum())},
        {"Review area": "Legacy, not unified paper evidence", "Researchers": int(f["Publication_model"].ne("unified-papers").sum())},
        {"Review area": "Evidence needs refresh after profile edits", "Researchers": int(f["Evidence_needs_refresh"].sum())},
        {"Review area": "Unresolved candidate papers", "Researchers": int(f["Unresolved_papers"].gt(0).sum())},
    ])
    st.dataframe(gaps, use_container_width=True, hide_index=True)
    issues = pd.DataFrame(issue_rows, columns=["Record", "Name", "Institution", "Severity", "Code", "Issue"])
    issues = issues[issues["Record"].isin(f.index)]
    issues.insert(1, "Researcher_ID", issues["Record"].map(df["Researcher_ID"]))
    c1, c2, c3 = st.columns(3)
    c1.metric("Subset-total conflicts", int((issues["Code"] == "noncns_subset_total").sum()))
    c2.metric("Legacy / undated counts", int((issues["Code"] == "legacy_count").sum()))
    c3.metric("Unverified ORCID dates", int((issues["Code"] == "unverified_lab_start").sum()))
    severities = st.multiselect("Issue severity", ["Conflict", "Missing", "Review"],
                               default=["Conflict", "Missing", "Review"], key="issue_severity")
    show = issues[issues["Severity"].isin(severities)].drop(columns=["Record"])
    st.dataframe(show, use_container_width=True, hide_index=True, height=480)
    st.download_button("Download selected review flags", csv_bytes(window_columns(show)),
                       f"data_quality_review_{PERIOD}.csv", "text/csv")
