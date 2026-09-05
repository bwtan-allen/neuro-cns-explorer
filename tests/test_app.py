import atexit
import datetime
import io
import json
import os
import shutil
import tempfile
import unittest
import uuid
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import streamlit as st

from fixtures import record, snapshot
from pipeline.snapshot import profile_record, project_snapshot
from app_runtime import load_backend


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


def ui_contribution(key, title, year, keywords, category="tool", status="source-backed", **overrides):
    return {
        **ui_claim(title, status), "id": key, "category": category, "year": year,
        "summary": f"Synthetic source-bounded summary for {title}.",
        "attribution": "Fixture Author contributed with the first author and collaborating team; not sole-inventor credit.",
        "keywords": list(keywords), "scope": "career-wide", **overrides,
    }


def ui_model(value, scope="lab research", status="source-backed"):
    return {**ui_claim(value, status), "scope": scope}


def ui_paper(pmid, year, tier="cns", topics=(), methods=(), species_mentions=(), **overrides):
    return {
        "pmid": str(pmid), "year": year, "journal": "Fixture journal", "title": f"Fixture paper {pmid}",
        "tier": tier, "doi": f"10.0000/fixture.{pmid}", "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        "last_author": "Fixture Author", "match": "full_name_and_affiliation",
        "publication_types": ["Journal Article"], "topics": list(topics), "methods": list(methods),
        "mesh": [], "keywords": list(species_mentions), "species_mentions": list(species_mentions),
        "species_evidence": {
            label: [{"source": "keyword", "text": label, "matched_terms": [label.casefold()]}]
            for label in species_mentions
        },
        "species_notes": [], "tag_method_version": 2,
        "tag_source": "title/MeSH/keywords; species mentions are not lab models or proof of study participants",
        "tag_evidence": {f"topics:{topic}": ["fixture evidence"] for topic in topics},
        **overrides,
    }


def ui_record(number, name=None, institution=None, papers=(), lab_start=2018, source_backed=True,
              contributions=None, model_organisms=None):
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
    if contributions is not None:
        profile["contributions"] = contributions
    if model_organisms is not None:
        profile["model_organisms"] = model_organisms
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
    return project_snapshot({
        **snapshot(*records), "schema_version": 4, "tag_method_version": 2,
        "coverage": {
            "registered": len(records),
            "unified_evidence": sum(row.get("publication_model") == "unified-papers" for row in records),
            "source_backed_identities": sum(row["identity_status"] == "source-backed" for row in records),
            "source_backed_lab_starts": sum(
                row["profile"]["career"]["lab_start_year"]["status"] == "source-backed" for row in records),
            "source_backed_contribution_profiles": sum(
                any(item["status"] == "source-backed" for item in row["profile"].get("contributions", []))
                for row in records),
            "source_backed_model_profiles": sum(
                any(item["status"] == "source-backed" for item in row["profile"].get("model_organisms", []))
                for row in records),
        },
    })


def discovery_records():
    memory = ("Learning and memory",)
    sensory = ("Sensory systems",)
    imaging = ("Imaging and microscopy",)
    first = ui_record(1, papers=[
        ui_paper(101, 2019, topics=memory, methods=("Optogenetics",), species_mentions=("Mouse",)),
        *[ui_paper(pmid, 2020, tier, topics=sensory, methods=imaging, species_mentions=("Human",))
          for pmid, tier in ((102, "cns"), (103, "cns"), (104, "field"), (105, "elife"), (106, "other"))],
    ], model_organisms=[ui_model("Mouse")], contributions=[
        ui_contribution("scanimage", "ScanImage acquisition software", 2003, ("ScanImage",)),
        ui_contribution("alm", "ALM preparatory activity", 2016, ("ALM",), category="discovery"),
    ])
    second = ui_record(2, papers=[
        ui_paper(201, 2019, topics=memory, methods=("Electrophysiology",), species_mentions=("Mouse",)),
        ui_paper(202, 2020, "other", topics=("Neural circuits and behavior",),
                 methods=("Computational modeling",), species_mentions=("Rat",)),
    ], lab_start=None, source_backed=False, model_organisms=[ui_model("Drosophila", scope="historical research")],
        contributions=[
            ui_contribution("marcm", "MARCM clonal labeling", 1999, ("MARCM",)),
            ui_contribution("trap2", "TRAP2 activity-dependent labeling", 2019, ("TRAP2",)),
            ui_contribution("teneurins", "Teneurin partner matching", 2012, ("teneurins",), category="discovery"),
        ])
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

    def test_stale_contribution_status_does_not_prevent_loading(self):
        person = ui_record(1, name="Jieli Li", lab_start=None, source_backed=False)
        person["profile"]["contribution_review"] = {
            "status": "needs-review", "reason": "Duplicate legacy row; use the canonical researcher.",
            "reviewed_at": "2026-09-05T00:00:00+00:00",
        }
        data = ui_snapshot(person)
        data["records"][0]["contribution_status"] = "not yet curated"
        self.replace_snapshot(data)
        self.assertEqual(self.download("Download filtered CSV").iloc[0]["Contribution_status"], "source review needed")
        self.app.radio(key="view").set_value("Researcher detail").run()
        self.assertFalse(self.app.exception)
        self.assertTrue(any("Duplicate legacy row" in item.value for item in self.app.info))

    def test_backend_revision_invalidates_data_and_projection_caches(self):
        old_published = self.app.session_state["_test_published_identity"]
        old_projection = self.app.session_state["_test_projection_identity"]
        changed = replace(load_backend(), revision="test-different-backend-revision")
        with patch("app_runtime.load_backend", return_value=changed):
            self.app.run()
        self.assertFalse(self.app.exception)
        self.assertNotEqual(self.app.session_state["_test_published_identity"], old_published)
        self.assertNotEqual(self.app.session_state["_test_projection_identity"], old_projection)

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
        self.assertEqual(self.app.sidebar.multiselect(key="paper_species_mentions").options, ["Mouse"])
        self.assertEqual(self.app.sidebar.multiselect(key="model_organisms").options, ["Drosophila", "Mouse"])
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
        self.app.sidebar.multiselect(key="paper_species_mentions").set_value(["Human"]).run()
        self.assertEqual(self.metric("Researchers"), "1")
        self.assertEqual(self.app.dataframe[0].value["Name"].tolist(), ["Researcher 1"])
        self.app.sidebar.multiselect(key="methods").set_value(["Electrophysiology"]).run()
        self.assertEqual(self.metric("Researchers"), "0")
        self.assertFalse(self.app.exception)
        self.assertTrue(any("Limited coverage" in item.value for item in self.app.sidebar.caption))

    def test_legacy_mesh_humans_and_mouse_disease_paper_do_not_define_human_lab_models(self):
        paper = ui_paper(701, 2020, title="Memory deficits in a mouse model of Alzheimer's disease",
                         mesh=["Humans", "Mice", "Alzheimer Disease"])
        for field in ("tag_method_version", "species_mentions", "species_evidence", "species_notes"):
            paper.pop(field)
        paper["organisms"] = ["Human", "Mouse"]
        sourced = ui_record(1, papers=[paper], model_organisms=[ui_model("Mouse")])
        unknown = ui_record(2, papers=[paper])
        for row in (sourced, unknown):
            row["organisms"] = ["Human", "Mouse"]
        self.replace_snapshot({**snapshot(sourced, unknown), "schema_version": 3})
        self.assertEqual(self.app.sidebar.multiselect(key="model_organisms").label, "Lab model (source-backed)")
        self.assertEqual(self.app.sidebar.multiselect(key="model_organisms").options, ["Mouse"])
        self.assertEqual(self.app.sidebar.multiselect(key="paper_species_mentions").options, ["Mouse"])
        exported = self.download("Download filtered CSV").set_index("Researcher_ID")
        self.assertEqual(json.loads(exported.loc[sourced["researcher_id"], "Model_organisms"]), ["Mouse"])
        self.assertEqual(json.loads(exported.loc[unknown["researcher_id"], "Model_organisms"]), [])
        self.assertEqual(exported.loc[unknown["researcher_id"], "Model_organism_status"], "unknown")
        self.assertNotIn("Organisms", exported.columns)
        self.app.radio(key="view").set_value("Researcher detail").run()
        counted = self.download("Download counted-paper CSV").iloc[0]
        self.assertEqual(json.loads(counted["species_mentions"]), ["Mouse"])
        self.assertNotIn("Human", json.loads(counted["species_evidence"]))
        self.assertTrue(any("MeSH 'Humans'" in note for note in json.loads(counted["species_notes"])))
        self.assertEqual(counted["tag_method_version"], 2)
        self.assertNotIn("organisms", counted.index)

    def test_lab_models_and_paper_mentions_are_distinct_filters(self):
        human_cells = ui_record(4, model_organisms=[ui_model("Human-derived cells/tissue")])
        self.replace_snapshot(ui_snapshot(*discovery_records(), human_cells))
        self.assertEqual(self.metric("Researchers"), "4")
        self.assertEqual(self.app.sidebar.multiselect(key="paper_species_mentions").label,
                         "Paper species mention (not lab model)")
        self.assertIn("Human", self.app.sidebar.multiselect(key="paper_species_mentions").options)
        self.assertNotIn("Human", self.app.sidebar.multiselect(key="model_organisms").options)
        self.assertNotIn("Drosophila", self.app.sidebar.multiselect(key="paper_species_mentions").options)
        self.app.sidebar.multiselect(key="paper_species_mentions").set_value(["Human"]).run()
        self.assertEqual(self.app.dataframe[0].value["Name"].tolist(), ["Researcher 1"])
        self.app.sidebar.multiselect(key="model_organisms").set_value(["Drosophila"]).run()
        self.assertEqual(self.metric("Researchers"), "0")
        self.app.sidebar.multiselect(key="paper_species_mentions").set_value([]).run()
        self.assertEqual(self.app.dataframe[0].value["Name"].tolist(), ["Researcher 2"])
        self.app.sidebar.multiselect(key="model_organisms").set_value(["Mouse", "Drosophila"]).run()
        self.assertEqual(self.metric("Researchers"), "2")
        self.app.sidebar.multiselect(key="paper_species_mentions").set_value(["Mouse"]).run()
        self.assertEqual(self.metric("Researchers"), "2")
        self.app.sidebar.multiselect(key="paper_species_mentions").set_value([])
        self.app.sidebar.multiselect(key="model_organisms").set_value(["Human-derived cells/tissue"]).run()
        self.assertEqual(self.app.dataframe[0].value["Name"].tolist(), ["Researcher 4"])
        self.assertEqual(self.app.dataframe[0].value["CNS_total"].tolist(), [0])

    def test_only_source_backed_research_claims_enter_search_and_filters(self):
        first, _, unknown = discovery_records()
        first["profile"]["contributions"].append(
            ui_contribution("unverified-mixed", "Unverified mixed claim", 2010, ("UnverifiedKeyword",),
                            status="unreviewed"))
        first["profile"]["model_organisms"].append(ui_model("Zebrafish", status="unreviewed"))
        unreviewed = ui_record(4, contributions=[
            ui_contribution("unconfirmed", "Unconfirmed discovery", None, ("UnconfirmedKeyword",), status="unreviewed")
        ], model_organisms=[ui_model("C. elegans", status="unreviewed")])
        self.replace_snapshot(ui_snapshot(first, unknown, unreviewed))
        self.assertEqual(self.app.sidebar.multiselect(key="contribution_keywords").options, ["ALM", "ScanImage"])
        self.assertEqual(self.app.sidebar.multiselect(key="model_organisms").options, ["Mouse"])
        exported = self.download("Download filtered CSV").set_index("Researcher_ID")
        self.assertEqual(json.loads(exported.loc[first["researcher_id"], "Contribution_keywords"]), ["ALM", "ScanImage"])
        self.assertEqual(json.loads(exported.loc[first["researcher_id"], "Model_organisms"]), ["Mouse"])
        self.assertEqual(exported.loc[unreviewed["researcher_id"], "Contribution_status"], "unreviewed")
        self.assertEqual(exported.loc[unreviewed["researcher_id"], "Model_organism_status"], "unreviewed")
        for query, matches in (
            ("ScanImage acquisition software", "1"), ("ScanImage", "1"), ("Mouse", "1"),
            ("Unverified mixed claim", "0"), ("UnverifiedKeyword", "0"), ("Zebrafish", "0"),
            ("Unconfirmed discovery", "0"), ("UnconfirmedKeyword", "0"), ("C. elegans", "0"),
        ):
            with self.subTest(query=query):
                self.app.sidebar.text_input(key="search").set_value(query).run()
                self.assertFalse(self.app.exception)
                self.assertEqual(self.metric("Researchers"), matches)
        self.app.sidebar.text_input(key="search").set_value("")
        self.app.radio(key="view").set_value("Researcher detail").run()
        self.assertTrue(any(item.label == "Unreviewed contribution claims (not established)" for item in self.app.expander))
        self.assertTrue(any("unreviewed, not established contributions" in item.value for item in self.app.warning))
        contributions = self.download("Download contribution claims CSV").set_index("Contribution")
        self.assertEqual(contributions.loc["Unverified mixed claim", "Status"], "unreviewed")
        self.assertIn("Fixture Author contributed", contributions.loc["Unverified mixed claim", "Attribution"])
        self.app.selectbox(key="researcher_id").set_value(unreviewed["researcher_id"]).run()
        self.assertTrue(any("Contribution profile: unreviewed" in item.value for item in self.app.info))
        self.assertTrue(any("Lab model metadata: unreviewed" in item.value for item in self.app.info))
        self.app.radio(key="view").set_value("Data quality").run()
        gaps = self.app.dataframe[0].value.set_index("Review area")
        self.assertEqual(gaps.loc["Contribution profiles with only unreviewed claims", "Researchers"], 1)
        self.assertEqual(gaps.loc["Lab model profiles with only unreviewed claims", "Researchers"], 1)

    def test_career_wide_contributions_and_model_filters_survive_count_windows(self):
        first, second, third = discovery_records()
        data = ui_snapshot(first, second, third)
        self.replace_snapshot(data)
        baseline = self.download("Download filtered CSV").set_index("Researcher_ID").sort_index()
        model_options = self.app.sidebar.multiselect(key="model_organisms").options
        keyword_options = self.app.sidebar.multiselect(key="contribution_keywords").options
        self.app.sidebar.select_slider(key="publication_window").set_value((2020, 2020)).run()
        exported = self.download("Download filtered CSV").set_index("Researcher_ID").sort_index()
        context_columns = ["Contribution_titles", "Contribution_keywords", "Contribution_status",
                           "Model_organisms", "Model_organism_status"]
        pd.testing.assert_frame_equal(exported[context_columns], baseline[context_columns])
        self.assertEqual(exported["CNS_total"].tolist(), [2, 0, 1])
        self.assertEqual(exported["nonCNS_total"].tolist(), [3, 1, 0])
        self.assertEqual(self.app.sidebar.multiselect(key="model_organisms").options, model_options)
        self.assertEqual(self.app.sidebar.multiselect(key="contribution_keywords").options, keyword_options)
        self.app.sidebar.multiselect(key="contribution_keywords").set_value(["ScanImage", "MARCM"]).run()
        self.assertEqual(self.metric("Researchers"), "2")
        self.app.sidebar.multiselect(key="model_organisms").set_value(["Drosophila"]).run()
        for year, cns_count in ((2019, 1), (2020, 0)):
            with self.subTest(year=year):
                self.app.sidebar.select_slider(key="publication_window").set_value((year, year)).run()
                self.assertFalse(self.app.exception)
                self.assertEqual(self.app.sidebar.multiselect(key="model_organisms").value, ["Drosophila"])
                self.assertEqual(self.app.sidebar.multiselect(key="contribution_keywords").value, ["ScanImage", "MARCM"])
                self.assertEqual(self.app.sidebar.multiselect(key="model_organisms").options, model_options)
                selected = self.download("Download filtered CSV").iloc[0]
                self.assertEqual(selected["Researcher_ID"], second["researcher_id"])
                self.assertEqual(selected["CNS_total"], cns_count)
        self.app.sidebar.multiselect(key="model_organisms").set_value([])
        self.app.sidebar.multiselect(key="contribution_keywords").set_value([])
        for keyword, person, cns_count in (
            ("ScanImage", first, 2), ("ALM", first, 2), ("MARCM", second, 0),
            ("TRAP2", second, 0), ("teneurins", second, 0),
        ):
            with self.subTest(keyword=keyword):
                self.app.sidebar.text_input(key="search").set_value(keyword).run()
                self.assertFalse(self.app.exception)
                self.assertEqual(self.metric("Researchers"), "1")
                selected = self.download("Download filtered CSV").iloc[0]
                self.assertEqual(selected["Researcher_ID"], person["researcher_id"])
                self.assertEqual(selected["CNS_total"], cns_count)
                self.assertEqual(selected["Window_start"], 2020)
        self.assertEqual(json.loads(self.data_path.read_text(encoding="utf-8")), data)

    def test_rich_contribution_and_model_sources_export_career_and_selected_scope(self):
        first, second, unknown = discovery_records()
        empty = ui_record(4, contributions=[], model_organisms=[])
        scanimage = first["profile"]["contributions"][0]
        scanimage["sources"].append({
            "url": "https://example.org/fixture-scanimage-team", "accessed": "2026-09-04",
            "title": "Fixture ScanImage team publication", "supports": "Synthetic support for the stated team roles.",
            "pmid": "777", "doi": "10.0000/fixture.source",
        })
        self.replace_snapshot(ui_snapshot(first, second, unknown, empty))
        self.app.sidebar.select_slider(key="publication_window").set_value((2020, 2020)).run()
        self.app.radio(key="view").set_value("Researcher detail").run()
        headings = [item.value for item in self.app.get("subheader")]
        self.assertLess(headings.index("Selected discoveries & contributions"), headings.index("Researcher profile and sources"))
        self.assertLess(headings.index("Selected discoveries & contributions"), headings.index("Counted-paper evidence"))
        text = "\n".join(item.value for item in self.app.markdown)
        self.assertIn(scanimage["summary"], text)
        self.assertIn(scanimage["attribution"], text)
        self.assertIn("https://example.org/fixture-scanimage-team", text)
        self.assertIn("2026-09-04", text)
        self.assertTrue(any("Keywords: ScanImage" in item.value and "Scope: career-wide" in item.value
                            for item in self.app.caption))
        self.assertTrue(any("not a complete contribution list" in item.value and "sole-inventor credit" in item.value
                            for item in self.app.caption))
        contributions = self.download("Download contribution claims CSV")
        scanimage_rows = contributions[contributions["Contribution"].eq(scanimage["value"])]
        self.assertEqual(len(scanimage_rows), 2)
        self.assertEqual(scanimage_rows["Year"].tolist(), [2003, 2003])
        self.assertTrue(scanimage_rows["Summary"].eq(scanimage["summary"]).all())
        self.assertTrue(scanimage_rows["Attribution"].eq(scanimage["attribution"]).all())
        self.assertEqual(set(scanimage_rows["Accessed"]), {"2020-02-03", "2026-09-04"})
        self.assertEqual(scanimage_rows.iloc[1]["Source"], "https://example.org/fixture-scanimage-team")
        self.assertEqual(scanimage_rows.iloc[1]["Supports"], "Synthetic support for the stated team roles.")
        self.assertTrue(contributions["Scope"].eq("career-wide").all())
        self.assertTrue(contributions["Status"].eq("source-backed").all())
        self.assertTrue(contributions["Researcher_ID"].eq(first["researcher_id"]).all())
        self.assertTrue(contributions["Window_start"].eq(2020).all())
        self.assertTrue(contributions["Window_end"].eq(2020).all())
        self.assertTrue(contributions["Selected_years"].astype(str).eq("2020").all())
        models = self.download("Download lab-model claims CSV")
        self.assertEqual(models["Model_organism"].tolist(), ["Mouse"])
        self.assertEqual(models["Scope"].tolist(), ["lab research"])
        self.assertEqual(models["Accessed"].tolist(), ["2020-02-03"])
        self.assertEqual(models["Source"].tolist(), ["https://example.org/fixture-profile"])
        self.assertTrue(models["Window_start"].eq(2020).all())
        model_table = next(item.value for item in self.app.dataframe if "Model_organism" in item.value.columns)
        self.assertEqual(model_table["Supports"].tolist(), ["Synthetic source for this fixture claim"])
        claims = self.download("Download profile source claims CSV")
        self.assertIn("Contribution (tool, career-wide)", claims["Claim"].tolist())
        self.assertIn("Model organism (lab research)", claims["Claim"].tolist())
        self.assertEqual(set(self.download("Download counted-paper CSV")["year"]), {2020})
        self.app.selectbox(key="researcher_id").set_value(second["researcher_id"]).run()
        contributions = self.download("Download contribution claims CSV")
        self.assertEqual(contributions.loc[contributions["Contribution"].eq("MARCM clonal labeling"), "Year"].tolist(), [1999])
        self.assertTrue(contributions["Window_start"].eq(2020).all())
        self.assertEqual(self.download("Download lab-model claims CSV")["Scope"].tolist(), ["historical research"])
        self.assertEqual(self.metric("CNS"), "0")
        for person in (unknown, empty):
            with self.subTest(profile=person["researcher_id"]):
                self.app.selectbox(key="researcher_id").set_value(person["researcher_id"]).run()
                self.assertTrue(any("Selected contributions: not yet curated" in item.value for item in self.app.info))
                self.assertTrue(any("Lab model metadata: unknown / not yet curated" in item.value for item in self.app.info))
                self.assertFalse(any(scanimage["summary"] in item.value for item in self.app.markdown))

    def test_research_context_columns_are_distinct_in_tables_comparisons_and_downloads(self):
        first, second, unknown = discovery_records()
        self.replace_snapshot(ui_snapshot(first, second, unknown))
        self.app.sidebar.select_slider(key="publication_window").set_value((2020, 2020)).run()
        fields = {"Contribution_titles", "Contribution_keywords", "Contribution_status",
                  "Model_organisms", "Model_organism_status", "Paper_species_mentions"}
        for view, download in (("Table", "Download filtered CSV"), ("Compare", "Download researcher comparison CSV"),
                               ("Rising stars", "Download rising stars / awardees CSV")):
            with self.subTest(view=view):
                self.app.radio(key="view").set_value(view).run()
                if view == "Compare":
                    self.app.multiselect(key="compare_researcher_ids").set_value(
                        [person["researcher_id"] for person in (first, second, unknown)]).run()
                self.assertFalse(self.app.exception)
                self.assertTrue(fields <= set(self.app.dataframe[0].value.columns))
                self.assertNotIn("Organisms", self.app.dataframe[0].value.columns)
                exported = self.download(download).set_index("Researcher_ID")
                self.assertTrue(fields <= set(exported.columns))
                self.assertNotIn("Organisms", exported.columns)
                self.assertEqual(json.loads(exported.loc[first["researcher_id"], "Model_organisms"]), ["Mouse"])
                self.assertEqual(json.loads(exported.loc[first["researcher_id"], "Paper_species_mentions"]), ["Human"])
                self.assertEqual(json.loads(exported.loc[first["researcher_id"], "Contribution_keywords"]), ["ALM", "ScanImage"])
                self.assertEqual(exported.loc[first["researcher_id"], "Contribution_status"], "source-backed examples")
                self.assertEqual(exported.loc[unknown["researcher_id"], "Contribution_status"], "not yet curated")
                self.assertEqual(exported.loc[unknown["researcher_id"], "Model_organism_status"], "unknown")

    def test_pilot_team_notes_and_model_scopes_are_visible_not_just_tags(self):
        historical_note = "Historical Janelia-lab research, not current Allen-era personal-lab scope."
        trap2_note = "2019 is detailed characterization, not invention; prior TRAP2 development was cited in 2017."
        svoboda = ui_record(1, name="Karel Svoboda", institution="Allen fixture affiliation",
                            papers=[ui_paper(101, 2020, species_mentions=("Mouse",))],
                            model_organisms=[{
                                **ui_model("Mouse", scope="historical research"), "note": historical_note,
                            }], contributions=[
                                ui_contribution("scanimage", "ScanImage", 2003, ("ScanImage",),
                                                attribution="Thomas A. Pologruto, Bernardo L. Sabatini, and Karel Svoboda."),
                            ])
        luo = ui_record(2, name="Liqun Luo", papers=[ui_paper(201, 2020, species_mentions=("Drosophila",))],
                       model_organisms=[ui_model("Fruit fly"), ui_model("Mouse")], contributions=[
                           ui_contribution("trap2", "TRAP2 characterization", 2019, ("TRAP2",), note=trap2_note,
                                           attribution="DeNardo characterized TRAP2; Luo collaborated on study design and writing."),
                           ui_contribution("marcm", "MARCM", 1999, ("MARCM",),
                                           attribution="Tzumin Lee and Liqun Luo jointly developed MARCM."),
                           ui_contribution("teneurins", "Teneurin partner matching", 2012, ("teneurins",),
                                           category="discovery",
                                           attribution="Weizhe Hong, Timothy J. Mosca, and Liqun Luo."),
                       ])
        self.replace_snapshot(ui_snapshot(svoboda, luo))
        self.assertEqual(self.app.sidebar.multiselect(key="model_organisms").options, ["Fruit fly", "Mouse"])
        self.assertNotIn("Human", self.app.sidebar.multiselect(key="paper_species_mentions").options)
        self.app.sidebar.select_slider(key="publication_window").set_value((2020, 2020)).run()
        self.app.radio(key="view").set_value("Researcher detail").run()
        self.assertTrue(any("**Mouse**" in item.value and "**Scope:** historical research" in item.value
                            for item in self.app.markdown))
        self.assertTrue(any(historical_note == item.value for item in self.app.caption))
        self.assertTrue(any("Pologruto" in item.value and "Sabatini" in item.value for item in self.app.markdown))
        self.assertEqual(self.metric("CNS"), "1")
        self.app.selectbox(key="researcher_id").set_value(luo["researcher_id"]).run()
        self.assertTrue(any("**Fruit fly**" in item.value and "**Scope:** lab research" in item.value
                            for item in self.app.markdown))
        self.assertTrue(any(trap2_note == item.value for item in self.app.caption))
        text = "\n".join(item.value for item in self.app.markdown)
        for credited in ("DeNardo", "Tzumin Lee", "Liqun Luo", "Weizhe Hong", "Timothy J. Mosca"):
            self.assertIn(credited, text)
        exported = self.download("Download contribution claims CSV").set_index("Contribution")
        self.assertEqual(exported.loc["TRAP2 characterization", "Year"], 2019)
        self.assertEqual(exported.loc["TRAP2 characterization", "Note"], trap2_note)
        self.assertTrue(exported["Scope"].eq("career-wide").all())
        self.assertTrue(exported["Window_start"].eq(2020).all())
        self.assertEqual(self.metric("CNS"), "1")

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
        self.app.sidebar.multiselect(key="paper_species_mentions").set_value(["Human"])
        self.app.sidebar.multiselect(key="model_organisms").set_value(["Mouse"])
        self.app.sidebar.multiselect(key="contribution_keywords").set_value(["ScanImage"])
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
                          species_mentions=("Mouse",), species_notes=["Synthetic mention, not a lab-model claim."])
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
        self.assertEqual(json.loads(selected.loc[501, "species_mentions"]), ["Mouse"])
        self.assertEqual(json.loads(selected.loc[501, "species_evidence"]), shared["species_evidence"])
        self.assertEqual(json.loads(selected.loc[501, "species_notes"]), shared["species_notes"])
        self.assertNotIn("organisms", selected.columns)
        metadata = next(item.value for item in self.app.dataframe if item.value.index.name == "Metadata")
        self.assertEqual(metadata.loc["last_author", "Paper 1 · PMID 501"], "Matched Senior Author")
        self.assertEqual(metadata.loc["publication_types", "Paper 1 · PMID 501"], '["Journal Article"]')
        self.assertEqual(metadata.loc["species_mentions", "Paper 1 · PMID 501"], '["Mouse"]')
        self.assertEqual(json.loads(metadata.loc["species_evidence", "Paper 1 · PMID 501"]), shared["species_evidence"])
        self.assertEqual(json.loads(metadata.loc["species_notes", "Paper 1 · PMID 501"]), shared["species_notes"])
        self.assertNotIn("organisms", metadata.index)
        self.assertTrue(any("do not define a lab's models" in item.value for item in self.app.caption))
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
        self.assertEqual(metadata.loc["species_mentions", "Paper 2 · PMID 902"], "n/a")
        self.assertNotIn("organisms", metadata.index)
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
        self.assertEqual(self.metric("Source-backed contribution profiles"), "2")
        self.assertEqual(self.metric("Contributions not yet curated"), "1")
        self.assertEqual(self.metric("Source-backed model profiles"), "2")
        self.assertEqual(self.metric("Model metadata unknown"), "1")
        gaps = self.app.dataframe[0].value.set_index("Review area")
        self.assertEqual(gaps.loc["Contribution profiles not yet curated", "Researchers"], 1)
        self.assertEqual(gaps.loc["Lab model metadata unknown", "Researchers"], 1)
        self.assertIn("Review", self.app.multiselect(key="issue_severity").value)
        exported = self.download("Download selected review flags")
        self.assertIn("unreviewed_identity", exported["Code"].tolist())
        self.assertIn("changed_identity_inputs", exported["Code"].tolist())
        self.assertIn("Researcher_ID", exported.columns)
        self.assertTrue(any("3 registered" in item.value for item in self.app.caption))
        self.assertTrue(any("2 source-backed contribution profiles" in item.value
                            and "2 source-backed model profiles" in item.value for item in self.app.caption))
        self.assertTrue(any("Unknown model metadata is not proof" in item.value for item in self.app.caption))
        self.app.sidebar.text_input(key="search").set_value("no such investigator").run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.metric("Researchers"), "0")
        self.assertEqual(self.metric("Selected registered IDs"), "0")
        self.assertEqual(self.metric("Source-backed contribution profiles"), "0")
        self.assertEqual(self.metric("Source-backed model profiles"), "0")
        self.assertTrue(self.download("Download selected review flags").empty)

    def test_shared_projection_is_used_and_window_cache_invalidates_on_file_revision(self):
        self.replace_snapshot(ui_snapshot(*discovery_records()))
        backend_snapshot = load_backend().snapshot
        with patch.object(backend_snapshot, "project_snapshot", wraps=backend_snapshot.project_snapshot) as projected:
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
