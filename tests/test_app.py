import atexit
import datetime
import io
import json
import os
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import streamlit as st

from fixtures import record, snapshot
from pipeline.snapshot import profile_record, project_snapshot


APP = Path(__file__).resolve().parents[1] / "streamlit_app.py"
ARTIFACTS = Path(os.path.relpath(APP.parent / "tests")) / f".app-ui-tests-{uuid.uuid4().hex}"
ARTIFACTS.mkdir()
atexit.register(shutil.rmtree, ARTIFACTS, ignore_errors=True)
previous_tempdir = tempfile.tempdir
try:
    # AppTest creates its own scratch directory on import; keep it inside the project.
    tempfile.tempdir = str(ARTIFACTS.resolve())
    from streamlit.testing.v1 import AppTest
finally:
    tempfile.tempdir = previous_tempdir


def ui_claim(value=None, status=None):
    status = status or ("unknown" if value is None else "source-backed")
    return {
        "value": value, "status": status, "note": "Synthetic UI fixture",
        "sources": [{"url": "https://example.org/fixture-profile", "accessed": "2020-02-03",
                     "supports": "Synthetic source for this fixture claim", "title": "Fixture profile"}]
        if status == "source-backed" else [],
    }


def ui_paper(pmid, year, tier="cns", topics=(), methods=(), organisms=(), **overrides):
    return {
        "pmid": str(pmid), "year": year, "journal": "Fixture journal", "title": f"Fixture paper {pmid}",
        "tier": tier, "doi": f"10.0000/fixture.{pmid}", "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        "last_author": "Fixture Author", "match": "full_name_and_affiliation",
        "publication_types": ["Journal Article"], "topics": list(topics), "methods": list(methods),
        "organisms": list(organisms), "tag_source": "title/MeSH/keywords (rule-inferred)",
        "tag_evidence": {f"topics:{topic}": ["fixture evidence"] for topic in topics},
        **overrides,
    }


def ui_record(number, name=None, institution=None, papers=(), lab_start=2018, source_backed=True):
    name = name or f"Researcher {number}"
    institution = institution or f"Institute {number}"
    profile = {
        "id": f"pi_{number:032x}", "name": name,
        "identity": ui_claim(name, "source-backed" if source_backed else "unreviewed"),
        "aliases": [{"given": "Fixture", "family": "Author", **ui_claim("Fixture Author")}],
        "orcid": ui_claim(), "affiliations": [
            {"institution": institution, "start_year": 2018, "end_year": None, "current": source_backed,
             **ui_claim(institution, "source-backed" if source_backed else "unreviewed")},
            {"institution": "Historical Institute", "start_year": 2009, "end_year": 2017, "current": False,
             **ui_claim("Historical Institute")},
        ],
        "career": {"lab_start_year": ui_claim(lab_start), "faculty_appointment_year": ui_claim(2015)},
        "career_proxies": {"orcid_employment_year": 2010, "first_senior_paper_year": 2012,
                           "legacy_source": "ORCID employment"},
        "hhmi": ui_claim("Fixture HHMI cohort", "unreviewed"),
        "awards": [{"year": 2019, **ui_claim("Fixture Award")}], "paper_overrides": [], "legacy_keys": [],
    }
    annual = {
        prefix: {str(year): sum(paper["year"] == year and paper["tier"] in tiers for paper in papers)
                 for year in (2019, 2020)}
        for prefix, tiers in (("cns", ("cns",)), ("noncns", ("field", "elife", "other")),
                              ("fieldtier", ("field",)), ("elife", ("elife",)))
    }
    row = record(name, institution, **{
        **{f"{prefix}_by_year": values for prefix, values in annual.items()},
        **{f"{prefix}_total": sum(values.values()) for prefix, values in annual.items()},
        "cns_available": True, "publication_model": "unified-papers", "publications": list(papers),
        "excluded_publications": [], "yearly_coverage_explicit": True,
        "count_coverage": {"start_year": 2019, "end_year": 2020},
        "count_fetched_at": "2021-01-02T00:00:00+00:00", "count_method_version": 3,
        "count_policy": {"authorship": "heuristic last-author matches", "dates": "electronic-first"},
        "count_source": "unified_pubmed fixture", "evidence_needs_refresh": False,
    })
    return profile_record(row, profile)


def ui_snapshot(*records):
    return {
        **snapshot(*records), "schema_version": 3,
        "coverage": {
            "registered": len(records),
            "unified_evidence": sum(row.get("publication_model") == "unified-papers" for row in records),
            "source_backed_identities": sum(row["identity_status"] == "source-backed" for row in records),
            "source_backed_lab_starts": sum(
                row["profile"]["career"]["lab_start_year"]["status"] == "source-backed" for row in records),
        },
    }


def discovery_records():
    memory = ("Learning and memory",)
    sensory = ("Sensory systems",)
    imaging = ("Imaging and microscopy",)
    first = ui_record(1, papers=[
        ui_paper(101, 2019, topics=memory, methods=("Optogenetics",), organisms=("Mouse",)),
        *[ui_paper(pmid, 2020, tier, topics=sensory, methods=imaging, organisms=("Human",))
          for pmid, tier in ((102, "cns"), (103, "cns"), (104, "field"), (105, "elife"), (106, "other"))],
    ])
    second = ui_record(2, papers=[
        ui_paper(201, 2019, topics=memory, methods=("Electrophysiology",), organisms=("Mouse",)),
        ui_paper(202, 2020, "other", topics=("Neural circuits and behavior",),
                 methods=("Computational modeling",), organisms=("Rat",)),
    ], lab_start=None, source_backed=False)
    third = ui_record(3, papers=[ui_paper(301, 2020)], lab_start=None)
    return first, second, third


class AppTests(unittest.TestCase):
    def setUp(self):
        self.directory = ARTIFACTS / uuid.uuid4().hex
        self.directory.mkdir()
        self.addCleanup(shutil.rmtree, self.directory)
        self.data_path = self.directory / "snapshot.json"
        self.data_path.write_text(json.dumps(snapshot(
            record("\u00c1lice Fixture", "First Institute"),
            record("Bob Fixture", "Second Institute", cns_total=0, cns_by_year={"2019": 0, "2020": 0}),
        )), encoding="utf-8")
        source = APP.read_text(encoding="utf-8").replace(
            'DATA = Path(__file__).resolve().with_name("neuro_stats.json")',
            f"DATA = Path({str(self.data_path.resolve())!r})",
        )
        source += ("\nst.session_state['_test_published_identity'] = id(published)\n"
                   "st.session_state['_test_projection_identity'] = id(snapshot)\n")
        self.source_path = self.directory / "fixture_app.py"
        self.source_path.write_text(source, encoding="utf-8")
        self.downloads = {}
        download_button = st.download_button

        def capture_download(label, data, *args, **kwargs):
            self.downloads[label] = data
            return download_button(label, data, *args, **kwargs)

        for mocked in (
            patch("streamlit.download_button", side_effect=capture_download),
            patch("requests.sessions.Session.request", side_effect=AssertionError("UI must not make network requests")),
            patch("urllib.request.urlopen", side_effect=AssertionError("UI must not make network requests")),
        ):
            mocked.start()
            self.addCleanup(mocked.stop)
        self.app = AppTest.from_file(str(self.source_path.resolve()), default_timeout=30).run()
        self.assertFalse(self.app.exception)

    def replace_snapshot(self, data):
        self.data_path.write_text(json.dumps(data), encoding="utf-8")
        self.downloads.clear()
        self.app.run()
        self.assertFalse(self.app.exception)

    def download(self, label):
        return pd.read_csv(io.BytesIO(self.downloads[label]))

    def metric(self, label):
        return next(item.value for item in self.app.metric if item.label == label)

    def test_default_view_does_not_render_hidden_charts(self):
        self.assertEqual(len(self.app.get("plotly_chart")), 0)
        self.assertEqual(len(self.app.dataframe[0].value), 2)

    def test_optional_text_handles_pandas_missing_scalars(self):
        source = self.source_path.read_text(encoding="utf-8")
        source += (
            "\nst.session_state['_test_missing_text'] = "
            "[display_text(value) for value in (None, float('nan'), pd.NA, '')]\n"
            "st.session_state['_test_known_text'] = display_text('Harvard University')\n"
            "st.session_state['_test_empty_fallback'] = display_text(float('nan'), '')\n"
        )
        self.source_path.write_text(source, encoding="utf-8")
        self.app.run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.session_state["_test_missing_text"], ["unknown"] * 4)
        self.assertEqual(self.app.session_state["_test_known_text"], "Harvard University")
        self.assertEqual(self.app.session_state["_test_empty_fallback"], "")

    def test_aliases_first_last_forms_and_ids_are_searchable(self):
        person = ui_record(1, name="David J. Anderson")
        person["profile"]["aliases"] = [
            {"given": "David Jeffrey", "family": "Anderson", **ui_claim("David Jeffrey Anderson")}
        ]
        self.replace_snapshot(ui_snapshot(person))
        for query in ("David Jeffrey", "David Anderson", person["researcher_id"]):
            with self.subTest(query=query):
                self.app.sidebar.text_input(key="search").set_value(query).run()
                self.assertFalse(self.app.exception)
                self.assertEqual(self.metric("Researchers"), "1")

    def test_every_view_handles_a_small_snapshot(self):
        for name in ("Rankings", "Researcher detail", "CNS vs non-CNS", "Rising stars", "Data quality", "Compare"):
            with self.subTest(view=name):
                self.app.radio(key="view").set_value(name).run()
                self.assertFalse(self.app.exception)

    def test_sidebar_filters_also_apply_to_rising_stars(self):
        self.app.radio(key="view").set_value("Rising stars").run()
        self.app.sidebar.multiselect[2].set_value(["Second Institute"]).run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.dataframe[0].value["Name"].tolist(), ["Bob Fixture"])

    def test_literal_search_and_empty_state(self):
        self.app.sidebar.text_input[0].set_value(".*").run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.metric[0].value, "0")
        self.assertTrue(any("No researchers match" in message.value for message in self.app.info))
        self.assertEqual(len(self.app.get("plotly_chart")), 0)

    def test_accent_insensitive_search(self):
        self.app.sidebar.text_input[0].set_value("alice").run()
        self.assertEqual(self.app.dataframe[0].value["Name"].tolist(), ["\u00c1lice Fixture"])

    def test_changed_file_invalidates_cached_data(self):
        self.data_path.write_text(json.dumps(snapshot(record("New Fixture"))), encoding="utf-8")
        self.app.run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.dataframe[0].value["Name"].tolist(), ["New Fixture"])

    def test_unknown_cns_is_not_filtered_out_by_default(self):
        unknown = record(cns_available=False, cns_total=None, cns_by_year={"2019": None, "2020": None})
        self.data_path.write_text(json.dumps(snapshot(unknown)), encoding="utf-8")
        self.app.run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.metric[0].value, "1")
        self.app.radio(key="view").set_value("CNS vs non-CNS").run()
        self.assertFalse(self.app.exception)
        self.assertTrue(any("No selected researchers" in message.value for message in self.app.info))

    def test_duplicate_names_remain_individually_selectable(self):
        self.data_path.write_text(json.dumps(snapshot(
            record("Same Name", "First Institute"), record("Same Name", "Second Institute"),
        )), encoding="utf-8")
        self.app.radio(key="view").set_value("Researcher detail").run()
        self.app.selectbox(key="researcher_id").set_value("legacy-row-1").run()
        self.assertFalse(self.app.exception)
        self.assertTrue(any("Same Name" in text.value and "Second Institute" in text.value for text in self.app.markdown))
        self.assertTrue(any("temporary UI key" in item.value for item in self.app.warning))

    def test_fresh_empty_recount_is_not_labeled_missing_evidence(self):
        zero = {"2019": 0, "2020": 0}
        current = record(cns_total=0, cns_by_year=zero, fieldtier_total=0, fieldtier_by_year=zero,
                         elife_total=0, elife_by_year=zero, publications=[],
                         count_method_version=2, count_fetched_at="2026-09-01T00:00:00+00:00")
        self.data_path.write_text(json.dumps(snapshot(current)), encoding="utf-8")
        self.app.radio(key="view").set_value("Researcher detail").run()
        self.assertFalse(self.app.exception)
        self.assertTrue(any("found no qualifying papers" in message.value for message in self.app.info))

    def test_window_updates_metrics_tags_and_actual_download_inputs(self):
        self.replace_snapshot(ui_snapshot(*discovery_records()))
        self.assertEqual(self.download("Download filtered CSV").set_index("Name").loc["Researcher 1", "CNS_total"], 3)
        self.app.sidebar.select_slider(key="publication_window").set_value((2019, 2019)).run()
        self.assertFalse(self.app.exception)
        exported = self.download("Download filtered CSV").set_index("Name")
        self.assertEqual(exported.loc["Researcher 1", "CNS_total"], 1)
        self.assertEqual(exported.loc["Researcher 1", "CNS_avg_per_yr"], 1)
        self.assertEqual(exported.loc["Researcher 1", "nonCNS_total"], 0)
        self.assertEqual(exported.loc["Researcher 1", "CNS_per_active_year"], 1)
        self.assertEqual(exported.loc["Researcher 1", "Window_start"], 2019)
        self.assertEqual(exported.loc["Researcher 1", "Window_end"], 2019)
        self.assertEqual(exported.loc["Researcher 1", "Career_reference_year"], 2019)
        self.assertIn("CNS_2019", exported.columns)
        self.assertNotIn("CNS_2020", exported.columns)
        self.assertEqual(json.loads(exported.loc["Researcher 1", "Topics"]), ["Learning and memory"])
        self.assertEqual(self.app.sidebar.multiselect(key="topics").options, ["Learning and memory"])
        self.assertEqual(self.app.sidebar.multiselect(key="organisms").options, ["Mouse"])
        self.assertNotIn("Imaging and microscopy", self.app.sidebar.multiselect(key="methods").options)
        self.app.radio(key="view").set_value("Researcher detail").run()
        self.assertEqual(self.metric("CNS"), "1")
        self.assertEqual(self.metric("non-CNS (includes subsets)"), "0")
        self.assertEqual(self.download("Download counted-paper CSV")["pmid"].tolist(), [101])
        chart = json.loads(self.app.get("plotly_chart")[0].proto.spec)
        self.assertEqual(chart["data"][0]["x"], ["2019"])
        self.app.sidebar.select_slider(key="publication_window").set_value((2020, 2020)).run()
        self.assertEqual(self.metric("CNS"), "2")
        self.assertEqual(self.metric("non-CNS (includes subsets)"), "3")
        self.assertEqual(set(self.download("Download counted-paper CSV")["year"]), {2020})

    def test_tag_filters_or_within_category_and_across_categories(self):
        self.replace_snapshot(ui_snapshot(*discovery_records()))
        self.assertEqual(self.metric("Researchers"), "3")
        self.app.sidebar.multiselect(key="topics").set_value(["Learning and memory", "Sensory systems"]).run()
        self.assertEqual(self.metric("Researchers"), "2")
        self.app.sidebar.multiselect(key="methods").set_value(["Optogenetics", "Electrophysiology"]).run()
        self.assertEqual(self.metric("Researchers"), "2")
        self.app.sidebar.multiselect(key="organisms").set_value(["Human"]).run()
        self.assertEqual(self.metric("Researchers"), "1")
        self.assertEqual(self.app.dataframe[0].value["Name"].tolist(), ["Researcher 1"])
        self.app.sidebar.multiselect(key="methods").set_value(["Electrophysiology"]).run()
        self.assertEqual(self.metric("Researchers"), "0")
        self.assertFalse(self.app.exception)
        self.assertTrue(any("Limited coverage" in item.value for item in self.app.sidebar.caption))

    def test_disappearing_window_tag_is_cleared_with_a_visible_notice(self):
        self.replace_snapshot(ui_snapshot(*discovery_records()))
        self.app.sidebar.multiselect(key="topics").set_value(["Sensory systems"]).run()
        self.assertEqual(self.metric("Researchers"), "1")
        self.app.sidebar.select_slider(key="publication_window").set_value((2019, 2019)).run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.sidebar.multiselect(key="topics").value, [])
        self.assertNotIn("Sensory systems", self.app.sidebar.multiselect(key="topics").options)
        self.assertTrue(any("selection cleared" in item.value for item in self.app.sidebar.info))

    def test_all_sidebar_filters_apply_across_views_including_compare(self):
        self.replace_snapshot(ui_snapshot(*discovery_records()))
        self.app.sidebar.multiselect(key="groups").set_value(["early-career awardee"])
        self.app.sidebar.multiselect(key="institutions").set_value(["Institute 1"])
        self.app.sidebar.multiselect(key="awards").set_value(["Fixture Award"])
        self.app.sidebar.multiselect(key="topics").set_value(["Sensory systems"])
        self.app.sidebar.multiselect(key="methods").set_value(["Imaging and microscopy"])
        self.app.sidebar.multiselect(key="organisms").set_value(["Human"])
        self.app.sidebar.multiselect(key="count_statuses").set_value(["No arithmetic flags"])
        self.app.sidebar.text_input(key="search").set_value("Researcher 1").run()
        for view in ("Table", "Rankings", "Researcher detail", "CNS vs non-CNS", "Rising stars", "Data quality", "Compare"):
            with self.subTest(view=view):
                self.app.radio(key="view").set_value(view).run()
                self.assertFalse(self.app.exception)
                self.assertEqual(self.metric("Researchers"), "1")
        self.assertEqual(len(self.app.multiselect(key="compare_researcher_ids").options), 1)
        self.assertTrue(any("at least two researchers" in item.value for item in self.app.info))

    def test_stable_ids_survive_duplicate_names_renames_and_row_reordering(self):
        first = ui_record(1, "Same Name", "First Institute")
        second = ui_record(2, "Same Name", "Second Institute")
        self.replace_snapshot(ui_snapshot(first, second))
        self.app.radio(key="view").set_value("Researcher detail").run()
        self.app.selectbox(key="researcher_id").set_value(second["researcher_id"]).run()
        self.assertFalse(self.app.exception)
        second["name"] = second["profile"]["name"] = "Renamed Researcher"
        self.replace_snapshot(ui_snapshot(second, first))
        self.assertEqual(self.app.selectbox(key="researcher_id").value, second["researcher_id"])
        self.assertTrue(any("Renamed Researcher" in item.value and "Second Institute" in item.value
                            for item in self.app.markdown))
        self.app.radio(key="view").set_value("Compare").run()
        self.assertEqual(set(self.app.multiselect(key="compare_researcher_ids").value),
                         {first["researcher_id"], second["researcher_id"]})
        self.assertEqual(set(self.app.dataframe[0].value["Researcher_ID"]),
                         {first["researcher_id"], second["researcher_id"]})

    def test_compare_window_counts_rates_trajectories_and_mixed_source_warnings(self):
        first, second, third = discovery_records()
        second["publication_model"] = "legacy-aggregates"
        self.replace_snapshot(ui_snapshot(first, second, third))
        self.app.radio(key="view").set_value("Compare").run()
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.app.get("plotly_chart")), 1)
        self.assertTrue(any("Mixed legacy/unified" in item.value for item in self.app.warning))
        self.assertTrue(any("Unreviewed identities" in item.value for item in self.app.warning))
        self.assertEqual(self.app.multiselect(key="compare_researcher_ids").proto.max_selections, 4)
        self.app.sidebar.select_slider(key="publication_window").set_value((2020, 2020)).run()
        comparison = self.download("Download researcher comparison CSV").set_index("Researcher_ID")
        self.assertEqual(comparison.loc[first["researcher_id"], "CNS_total"], 2)
        self.assertEqual(comparison.loc[first["researcher_id"], "CNS_avg_per_yr"], 2)
        self.assertTrue(pd.isna(comparison.loc[second["researcher_id"], "CNS_per_active_year"]))
        annual = self.download("Download comparison annual trajectories CSV")
        self.assertEqual(annual["Year"].tolist(), [2020, 2020])
        chart = json.loads(self.app.get("plotly_chart")[0].proto.spec)
        self.assertEqual(len(chart["data"]), 2)
        self.assertTrue(all(trace["x"] == ["2020"] for trace in chart["data"]))
        self.assertTrue(all(trace["connectgaps"] is False for trace in chart["data"]))
        self.app.multiselect(key="compare_researcher_ids").set_value([first["researcher_id"]]).run()
        self.assertEqual(len(self.app.get("plotly_chart")), 0)
        self.assertTrue(any("at least two researchers" in item.value for item in self.app.info))

    def test_comparison_accepts_four_filtered_researchers(self):
        records = [ui_record(number) for number in range(1, 6)]
        self.replace_snapshot(ui_snapshot(*records))
        self.app.radio(key="view").set_value("Compare").run()
        chosen = [row["researcher_id"] for row in records[:4]]
        self.app.multiselect(key="compare_researcher_ids").set_value(chosen).run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.dataframe[0].value["Researcher_ID"].tolist(), chosen)
        self.assertEqual(len(json.loads(self.app.get("plotly_chart")[0].proto.spec)["data"]), 4)
        self.assertEqual(len(self.download("Download researcher comparison CSV")), 4)

    def test_compare_papers_deduplicates_pmids_and_preserves_matching_registry_ids(self):
        shared = ui_paper(501, 2020, title="Shared mouse imaging paper", last_author="Matched Senior Author",
                          topics=("Neural circuits and behavior",), methods=("Imaging and microscopy",),
                          organisms=("Mouse",))
        first = ui_record(1, papers=[shared, ui_paper(502, 2019), ui_paper(504, 2020)])
        second = ui_record(2, papers=[shared, ui_paper(503, 2020)])
        second["excluded_publications"] = [
            {"pmid": "999", "year": 2020, "journal": "Fixture journal", "title": "Rejected candidate",
             "last_author": "Other Author", "decision": "excluded", "reason": "different_full_given_name",
             "url": "https://pubmed.ncbi.nlm.nih.gov/999/", "doi": "", "publication_types": [], "match": ""},
        ]
        outside = ui_record(3, papers=[ui_paper(505, 2020)])
        self.replace_snapshot(ui_snapshot(first, second, outside))
        self.app.radio(key="view").set_value("Compare").run()
        widget = self.app.multiselect(key="compare_papers")
        self.assertEqual(len(widget.options), 4)
        self.assertEqual(sum("PMID 501 " in label for label in widget.options), 1)
        self.assertFalse(any("PMID 999 " in label or "PMID 505 " in label for label in widget.options))
        self.assertEqual(widget.proto.max_selections, 4)
        widget.set_value(["501", "503"]).run()
        self.assertFalse(self.app.exception)
        selected = self.download("Download selected paper comparison CSV").set_index("pmid")
        self.assertEqual(selected.index.tolist(), [501, 503])
        self.assertEqual(set(json.loads(selected.loc[501, "matched_researcher_ids"])),
                         {first["researcher_id"], second["researcher_id"]})
        self.assertEqual(json.loads(selected.loc[503, "matched_researcher_ids"]), [second["researcher_id"]])
        self.assertEqual(json.loads(selected.loc[501, "methods"]), ["Imaging and microscopy"])
        metadata = next(item.value for item in self.app.dataframe if item.value.index.name == "Metadata")
        self.assertEqual(metadata.loc["last_author", "Paper 1 · PMID 501"], "Matched Senior Author")
        self.assertEqual(metadata.loc["publication_types", "Paper 1 · PMID 501"], '["Journal Article"]')
        links = {button.proto.url for button in self.app.get("link_button")}
        self.assertIn("https://pubmed.ncbi.nlm.nih.gov/501/", links)
        self.assertIn("https://doi.org/10.0000/fixture.501", links)
        self.app.multiselect(key="compare_papers").set_value(["501", "502", "503", "504"]).run()
        self.assertEqual(len(self.download("Download selected paper comparison CSV")), 4)
        self.app.multiselect(key="compare_papers").set_value(["501"]).run()
        self.assertFalse(any(item.value.index.name == "Metadata" for item in self.app.dataframe))
        self.assertTrue(any("Select 2–4 distinct included PMIDs" in item.value for item in self.app.info))
        self.app.sidebar.select_slider(key="publication_window").set_value((2019, 2019)).run()
        self.assertEqual(self.app.multiselect(key="compare_papers").value, [])
        self.assertEqual(len(self.app.multiselect(key="compare_papers").options), 1)
        self.assertIn("PMID 502 ", self.app.multiselect(key="compare_papers").options[0])

    def test_profile_distinguishes_sourced_lab_start_from_proxies_and_unreviewed_claims(self):
        first, second, _ = discovery_records()
        second["profile"]["career"]["lab_start_year"] = ui_claim(2011, "unreviewed")
        self.replace_snapshot(ui_snapshot(first, second))
        self.app.radio(key="view").set_value("Researcher detail").run()
        self.assertEqual(self.metric("Independent lab start"), "2018")
        self.assertEqual(self.metric("Active lab years in window"), "2")
        self.assertEqual(self.metric("CNS / active lab year"), "1.50")
        self.assertTrue(any("Independent lab start: 2018 · source-backed" in item.value for item in self.app.caption))
        claims = next(item.value for item in self.app.dataframe if "Claim" in item.value.columns)
        start = claims.loc[claims["Claim"] == "Independent lab start"].iloc[0]
        self.assertEqual(start["Status"], "source-backed")
        self.assertEqual(start["URL"], "https://example.org/fixture-profile")
        self.assertEqual(start["Accessed"], "2020-02-03")
        self.assertEqual(set(self.download("Download profile source claims CSV")["Researcher_ID"]), {first["researcher_id"]})
        history = next(item.value for item in self.app.dataframe if "Current status" in item.value.columns)
        self.assertEqual(history["Current status"].tolist(), ["source-backed current", "historical"])
        self.app.selectbox(key="researcher_id").set_value(second["researcher_id"]).run()
        self.assertEqual(self.metric("Independent lab start"), "n/a")
        self.assertEqual(self.metric("Active lab years in window"), "n/a")
        self.assertEqual(self.metric("CNS / active lab year"), "n/a")
        self.assertTrue(any("not source-backed" in item.value for item in self.app.info))
        self.assertTrue(any("Faculty appointment: 2015 · source-backed" in item.value
                            and "not an independent-lab start" in item.value for item in self.app.caption))
        self.assertTrue(any("ORCID employment 2010" in item.value and "first senior/last-author paper 2012" in item.value
                            for item in self.app.caption))
        self.assertTrue(any("Current institution:** unknown" in item.value for item in self.app.markdown))
        claims = next(item.value for item in self.app.dataframe if "Claim" in item.value.columns)
        self.assertEqual(claims.loc[claims["Claim"] == "Independent lab start", "Value"].tolist(), ["2011"])
        self.assertEqual(claims.loc[claims["Claim"] == "HHMI status", "Status"].tolist(), ["unreviewed"])
        self.assertEqual(claims.loc[claims["Claim"] == "Award (2019)", "Status"].tolist(), ["source-backed"])
        self.app.radio(key="view").set_value("Compare").run()
        comparison = self.download("Download researcher comparison CSV").set_index("Researcher_ID")
        self.assertEqual(comparison.loc[second["researcher_id"], "Faculty_appointment_year"], 2015)
        self.assertEqual(comparison.loc[second["researcher_id"], "Faculty_appointment_status"], "source-backed")
        self.assertTrue(pd.isna(comparison.loc[second["researcher_id"], "CNS_per_active_year"]))

    def test_activity_adjusted_rate_excludes_pre_independence_papers(self):
        first, _, _ = discovery_records()
        first["profile"]["career"]["lab_start_year"] = ui_claim(2020)
        self.replace_snapshot(ui_snapshot(first))
        exported = self.download("Download filtered CSV").iloc[0]
        self.assertEqual(exported["CNS_total"], 3)
        self.assertEqual(exported["CNS_avg_per_yr"], 1.5)
        self.assertEqual(exported["Active_years_in_window"], 1)
        self.assertEqual(exported["CNS_per_active_year"], 2)
        self.app.radio(key="view").set_value("Researcher detail").run()
        self.assertEqual(self.metric("CNS"), "3")
        self.assertEqual(self.metric("Independent lab start"), "2020")
        self.assertEqual(self.metric("Active lab years in window"), "1")
        self.assertEqual(self.metric("CNS / active lab year"), "2.00")
        self.app.sidebar.select_slider(key="publication_window").set_value((2019, 2019)).run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.metric("CNS"), "1")
        self.assertEqual(self.metric("Active lab years in window"), "0")
        self.assertEqual(self.metric("CNS / active lab year"), "n/a")

    def test_evidence_separates_decisions_and_compares_selected_papers(self):
        first, second, _ = discovery_records()
        candidates = [
            ui_paper(901, 2019, decision="excluded", reason="different_full_given_name"),
            ui_paper(902, 2020, decision="excluded", reason="different_full_given_name"),
            ui_paper(903, 2020, decision="unresolved", reason="initials_only"),
            ui_paper(904, None, decision="unresolved", reason="publication_year_unknown"),
        ]
        compact_fields = ("pmid", "year", "journal", "title", "last_author", "decision", "reason",
                          "url", "doi", "publication_types", "match")
        first["excluded_publications"] = [
            {field: paper[field] for field in compact_fields} for paper in candidates
        ]
        self.replace_snapshot(ui_snapshot(first, second))
        self.app.sidebar.select_slider(key="publication_window").set_value((2020, 2020)).run()
        self.app.radio(key="view").set_value("Researcher detail").run()
        included = self.download("Download counted-paper CSV")
        excluded = self.download("Download excluded / unresolved CSV")
        self.assertEqual(set(included["pmid"]), {102, 103, 104, 105, 106})
        self.assertEqual(set(included["decision"]), {"included"})
        self.assertEqual(set(excluded["pmid"]), {902, 903, 904})
        self.assertEqual(set(excluded["decision"]), {"excluded", "unresolved"})
        self.assertIn("different_full_given_name", excluded["reason"].tolist())
        self.assertTrue(any("Undated review candidates" in item.value for item in self.app.caption))
        widget = self.app.multiselect(key="detail_papers")
        keys = [f"{first['researcher_id']}:102:included:0", f"{first['researcher_id']}:902:excluded:5"]
        widget.set_value(keys).run()
        self.assertFalse(self.app.exception)
        selected = self.download("Download selected paper comparison CSV")
        self.assertEqual(selected["pmid"].tolist(), [102, 902])
        self.assertEqual(selected["decision"].tolist(), ["included", "excluded"])
        self.assertTrue(selected["Window_start"].eq(2020).all())
        self.assertTrue(pd.isna(selected.loc[selected["pmid"] == 902, "topics"].iloc[0]))
        metadata = next(item.value for item in self.app.dataframe if item.value.index.name == "Metadata")
        self.assertEqual(metadata.loc["topics", "Paper 2 · PMID 902"], "n/a")
        self.app.radio(key="view").set_value("Compare").run()
        self.assertTrue(any("PMID 202" in label for label in self.app.multiselect(key="compare_papers").options))

    def test_missing_coverage_preserves_known_annual_points_without_zero_fill(self):
        first, second, _ = discovery_records()
        first["publications"] = [paper for paper in first["publications"] if paper["year"] == 2019]
        for prefix in ("cns", "noncns", "fieldtier", "elife"):
            first[f"{prefix}_by_year"]["2020"] = None
            first[f"{prefix}_total"] = None
        first.update(cns_available=False, noncns_available=False, fieldjournals_available=False,
                     count_coverage={"start_year": 2019, "end_year": 2019})
        self.replace_snapshot(ui_snapshot(first, second))
        exported = self.download("Download filtered CSV").set_index("Name")
        self.assertTrue(pd.isna(exported.loc["Researcher 1", "CNS_total"]))
        self.assertTrue(pd.isna(exported.loc["Researcher 1", "CNS_avg_per_yr"]))
        self.assertEqual(exported.loc["Researcher 1", "CNS_2019"], 1)
        self.assertTrue(pd.isna(exported.loc["Researcher 1", "CNS_2020"]))
        self.assertTrue(any("lack complete count coverage" in item.value for item in self.app.info))
        self.app.radio(key="view").set_value("Compare").run()
        chart = json.loads(self.app.get("plotly_chart")[0].proto.spec)
        self.assertEqual(chart["data"][0]["y"], [1, None])
        self.assertFalse(chart["data"][0]["connectgaps"])
        self.assertTrue(any("coverage is incomplete" in item.value for item in self.app.warning))
        self.app.radio(key="view").set_value("Researcher detail").run()
        self.assertEqual(self.metric("CNS"), "n/a")
        chart = json.loads(self.app.get("plotly_chart")[0].proto.spec)
        self.assertEqual(chart["data"][0]["y"], [1, None])
        self.app.sidebar.select_slider(key="publication_window").set_value((2019, 2019)).run()
        self.assertEqual(self.metric("CNS"), "1")
        self.assertEqual(self.metric("CNS / active lab year"), "1.00")

    def test_single_year_and_partial_calendar_year_snapshots(self):
        only_year = project_snapshot(snapshot(record()), 2020, 2020)
        self.replace_snapshot(only_year)
        self.assertEqual(len(self.app.sidebar.select_slider), 0)
        self.assertEqual(self.download("Download filtered CSV")["Window_start"].tolist(), [2020])
        for view in ("Researcher detail", "Rising stars", "Compare", "Data quality"):
            self.app.radio(key="view").set_value(view).run()
            self.assertFalse(self.app.exception)
        current = datetime.date.today().year
        current_row = record()
        for prefix in ("cns", "noncns", "fieldtier", "elife"):
            current_row[f"{prefix}_by_year"] = {str(current): current_row[f"{prefix}_total"]}
        self.replace_snapshot({"years": [current], "records": [current_row],
                               "generated": f"{current}-02-01", "partial_calendar_year": True})
        self.assertTrue(any("partial calendar year" in item.value and "not annualized" in item.value
                            for item in self.app.warning))

    def test_unpublished_calendar_years_are_disclosed_and_never_zero_filled(self):
        row = record()
        for prefix in ("cns", "noncns", "fieldtier", "elife"):
            row[f"{prefix}_by_year"]["2021"] = row[f"{prefix}_by_year"].pop("2020")
        self.replace_snapshot({"years": [2019, 2021], "records": [row], "generated": "2022-01-01"})
        self.assertEqual(self.app.sidebar.select_slider(key="publication_window").options, ["2019", "2021"])
        self.assertTrue(any("Some calendar years are not published" in item.value for item in self.app.warning))
        exported = self.download("Download filtered CSV")
        self.assertEqual(exported["Selected_years"].tolist(), ["2019, 2021"])
        self.assertEqual(exported["CNS_avg_per_yr"].tolist(), [1])
        self.assertNotIn("CNS_2020", exported.columns)

    def test_data_quality_exposes_review_gaps_and_remains_accessible_with_empty_filters(self):
        first, second, third = discovery_records()
        second["evidence_needs_refresh"] = True
        self.replace_snapshot(ui_snapshot(first, second, third))
        self.app.radio(key="view").set_value("Data quality").run()
        self.assertEqual(self.metric("Selected registered IDs"), "3")
        self.assertEqual(self.metric("Selected unified evidence"), "3")
        self.assertEqual(self.metric("Source-backed identities"), "2")
        self.assertEqual(self.metric("Source-backed lab starts"), "1")
        self.assertIn("Review", self.app.multiselect(key="issue_severity").value)
        exported = self.download("Download selected review flags")
        self.assertIn("unreviewed_identity", exported["Code"].tolist())
        self.assertIn("changed_identity_inputs", exported["Code"].tolist())
        self.assertIn("Researcher_ID", exported.columns)
        self.assertTrue(any("3 registered" in item.value for item in self.app.caption))
        self.app.sidebar.text_input(key="search").set_value("no such investigator").run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.metric("Researchers"), "0")
        self.assertEqual(self.metric("Selected registered IDs"), "0")
        self.assertTrue(self.download("Download selected review flags").empty)

    def test_shared_projection_is_used_and_window_cache_invalidates_on_file_revision(self):
        self.replace_snapshot(ui_snapshot(*discovery_records()))
        with patch("pipeline.snapshot.project_snapshot", wraps=project_snapshot) as projected:
            self.app.sidebar.select_slider(key="publication_window").set_value((2019, 2019)).run()
            self.assertGreaterEqual(projected.call_count, 1)
            self.assertEqual(projected.call_args.args[1:], (2019, 2019))
            calls = projected.call_count
            self.app.run()
            self.assertEqual(projected.call_count, calls)
        updated = ui_snapshot(*discovery_records())
        updated["records"][0]["publications"].append(
            ui_paper(107, 2019, topics=("Sleep and circadian rhythms",)))
        updated["records"][0]["cns_by_year"]["2019"] += 1
        updated["records"][0]["cns_total"] += 1
        self.replace_snapshot(updated)
        exported = self.download("Download filtered CSV").set_index("Name")
        self.assertEqual(exported.loc["Researcher 1", "CNS_total"], 2)
        self.assertIn("Sleep and circadian rhythms", self.app.sidebar.multiselect(key="topics").options)

    def test_filter_reruns_reuse_read_only_evidence_without_copying(self):
        self.replace_snapshot(ui_snapshot(*discovery_records()))
        published_identity = self.app.session_state["_test_published_identity"]
        projection_identity = self.app.session_state["_test_projection_identity"]
        self.app.sidebar.text_input(key="search").set_value("Researcher 1").run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.session_state["_test_published_identity"], published_identity)
        self.assertEqual(self.app.session_state["_test_projection_identity"], projection_identity)
        self.app.radio(key="view").set_value("Researcher detail").run()
        self.assertEqual(self.app.session_state["_test_projection_identity"], projection_identity)
        self.app.sidebar.select_slider(key="publication_window").set_value((2019, 2019)).run()
        self.assertEqual(self.app.session_state["_test_published_identity"], published_identity)
        self.assertNotEqual(self.app.session_state["_test_projection_identity"], projection_identity)
        self.app.sidebar.select_slider(key="publication_window").set_value((2019, 2020)).run()
        self.assertEqual(self.app.session_state["_test_projection_identity"], projection_identity)


if __name__ == "__main__":
    unittest.main()
