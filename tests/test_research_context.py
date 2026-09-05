import copy
import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fixtures import record, snapshot
from pipeline.data_quality import validate_snapshot
from pipeline.profiles import (
    apply_updates, claim, contribution_evidence, matching_fingerprint, migrate, profile_evidence,
    research_context, validate_registry,
)
from pipeline.snapshot import build_snapshot, project_snapshot
from pipeline.storage import write_json
from pipeline.taxonomy import TAG_METHOD_VERSION, classify, retag_paper


SOURCE = {
    "url": "https://example.org/primary-paper", "accessed": "2026-09-05",
    "supports": "Synthetic fixture evidence for a collaborative method.",
}
ROOT = Path(__file__).resolve().parents[1]


def contribution(**overrides):
    return {
        **claim("Example mosaic method", "source-backed", [SOURCE]),
        "id": "example-mosaic", "category": "method", "year": 1999,
        "keywords": ["mosaic analysis", "example label"], "scope": "career-wide",
        "summary": "A selected historical method contribution.",
        "attribution": "Co-developed by the named team; not a sole-inventor claim.",
        **overrides,
    }


def model(value="Mouse", status="source-backed"):
    return {**claim(value, status, [SOURCE] if status == "source-backed" else []), "scope": "lab research"}


class TaxonomyTests(unittest.TestCase):
    def test_mesh_humans_does_not_infer_human_experiments(self):
        tags = classify(
            "Early adolescent Rai1 reactivation reverses deficits in a mouse model of Smith-Magenis syndrome.",
            ["Humans", "Mice", "Disease Models, Animal", "Smith-Magenis Syndrome"],
        )
        self.assertEqual(tags["species_mentions"], ["Mouse"])
        self.assertNotIn("organisms", tags)
        self.assertTrue(any("indexing context" in note for note in tags["species_notes"]))
        self.assertEqual({item["source"] for item in tags["species_evidence"]["Mouse"]}, {"title", "MeSH"})

    def test_review_indexing_is_not_a_human_lab_model(self):
        tags = classify("Genetic strategies to access activated neurons.", ["Humans", "Animals", "Behavior"])
        self.assertEqual(tags["species_mentions"], [])
        self.assertNotIn("model_organisms", tags)

    def test_nonhuman_and_humanized_are_not_human_species_matches(self):
        for title in ("Humanized mice reveal disease mechanisms", "Imaging non-human primates", "Firing rates during latency"):
            with self.subTest(title=title):
                mentions = classify(title)["species_mentions"]
                self.assertNotIn("Human", mentions)
                self.assertNotIn("Rat", mentions)

    def test_human_cell_mentions_are_not_inferred_human_participants(self):
        tags = classify("Human stem-cell derived neurons model disease", ["Humans"])
        self.assertIn("Human", tags["species_mentions"])
        self.assertEqual(tags["species_evidence"]["Human"][0]["source"], "title")
        self.assertNotIn("Human participants", tags["species_mentions"])
        self.assertNotIn("model_organisms", tags)

    def test_patient_relevance_alone_is_not_species_evidence(self):
        self.assertNotIn("Human", classify("Patient-relevant disease models in mice")["species_mentions"])

    def test_retag_removes_old_organism_labels_without_touching_source_or_count_data(self):
        old = {
            "pmid": "30275311", "title": "A mouse model of a human disease",
            "mesh": ["Humans", "Mice"], "keywords": [], "organisms": ["Human", "Mouse"],
            "decision": "included", "year": 2018, "tier": "other", "retrieved_at": "2026-09-04T00:00:00Z",
            "tag_evidence": {"organisms:Human": ["humans"]},
        }
        original = copy.deepcopy(old)
        updated = retag_paper(old)
        self.assertEqual(old, original)
        self.assertNotIn("organisms", updated)
        self.assertNotIn("organisms:Human", updated["tag_evidence"])
        self.assertEqual(updated["tag_method_version"], TAG_METHOD_VERSION)
        for key in ("pmid", "decision", "year", "tier", "retrieved_at"):
            self.assertEqual(updated[key], original[key])
        self.assertIs(retag_paper(updated), updated)


class ResearchProfileTests(unittest.TestCase):
    def setUp(self):
        self.source = snapshot(record("Alice Example", "Example Institute"))
        self.registry = migrate(self.source)
        self.profile = next(iter(self.registry["profiles"].values()))

    def test_missing_research_context_means_uncurated_not_no_contributions(self):
        context = research_context(self.profile)
        self.assertEqual(context["model_organism_status"], "unknown")
        self.assertEqual(context["contribution_status"], "not yet curated")
        self.assertEqual(context["contribution_keywords"], [])

    def test_only_sourced_claims_enter_discovery_filters(self):
        self.profile["contributions"] = [contribution(), contribution(
            id="unreviewed-method", value="Unreviewed claim", keywords=["unconfirmed"], status="unreviewed", sources=[])]
        self.profile["model_organisms"] = [model(), model("Rat", "unreviewed")]
        context = research_context(self.profile)
        self.assertEqual(context["model_organisms"], ["Mouse"])
        self.assertNotIn("unconfirmed", context["contribution_keywords"])
        self.assertEqual(len(contribution_evidence(self.profile)), 2)

    def test_sourced_contributions_require_sources_role_and_scope(self):
        for changes in ({"sources": []}, {"attribution": ""}, {"scope": "2016-2025"},
                        {"keywords": ["ALM", "alm"]}, {"year": "1999"}, {"category": "prestige"}):
            with self.subTest(changes=changes):
                self.profile["contributions"] = [contribution(**changes)]
                with self.assertRaises(ValueError):
                    validate_registry(self.registry)

    def test_ambiguous_human_models_need_explicit_context(self):
        self.profile["model_organisms"] = [model("Human")]
        with self.assertRaisesRegex(ValueError, "Human participants"):
            validate_registry(self.registry)
        self.profile["model_organisms"] = [model("Human-derived cells/tissue")]
        validate_registry(self.registry)

    def test_curation_preserves_identity_fingerprint_and_records_changes(self):
        fingerprint = matching_fingerprint(self.profile)
        registry = apply_updates(self.registry, [{
            "researcher_id": self.profile["id"], "reason": "Add sourced collaborative contribution examples.",
            "changes": {"contributions": [contribution()], "model_organisms": [model()]},
        }])
        profile = registry["profiles"][self.profile["id"]]
        self.assertEqual(matching_fingerprint(profile), fingerprint)
        self.assertEqual(len(registry["changes"]), 1)
        evidence = profile_evidence(profile)
        self.assertTrue(any("Contribution" in item["Claim"] for item in evidence))
        self.assertTrue(any("Model organism" in item["Claim"] for item in evidence))

    def test_old_profiles_accept_new_context_fields_without_a_registry_rewrite(self):
        self.profile.pop("contributions")
        self.profile.pop("model_organisms")
        registry = apply_updates(self.registry, [{
            "researcher_id": self.profile["id"], "reason": "Add an evidenced historical contribution.",
            "changes": {"contributions": [contribution()], "model_organisms": [model()]},
        }])
        self.assertIsNone(registry["changes"][0]["before"]["contributions"])
        self.assertEqual(registry["profiles"][self.profile["id"]]["contributions"][0]["year"], 1999)

    def test_reading_human_articles_does_not_create_sourced_lab_claims(self):
        source = copy.deepcopy(self.source)
        source["records"][0]["organisms"] = ["Human"]
        data = build_snapshot(source, self.registry)
        self.assertEqual(data["records"][0]["model_organisms"], [])
        self.assertEqual(data["records"][0]["model_organism_status"], "unknown")
        self.assertNotIn("organisms", data["records"][0])

    def test_career_contribution_and_lab_model_do_not_follow_count_window(self):
        self.profile["contributions"] = [contribution()]
        self.profile["model_organisms"] = [model()]
        published = build_snapshot(self.source, self.registry)
        selected = project_snapshot(published, 2020, 2020)
        row = selected["records"][0]
        self.assertEqual(row["cns_total"], 1)
        self.assertEqual(row["contribution_titles"], ["Example mosaic method"])
        self.assertEqual(row["profile"]["contributions"][0]["year"], 1999)
        self.assertEqual(row["model_organisms"], ["Mouse"])
        self.assertEqual(row["paper_species_mentions"], [])
        self.assertNotIn("organisms", row)
        validate_snapshot(selected)

    def test_unsourced_human_model_cannot_leak_into_snapshot(self):
        data = build_snapshot(self.source, self.registry)
        data["records"][0]["model_organisms"] = ["Human"]
        with self.assertRaisesRegex(ValueError, "source-backed profile"):
            validate_snapshot(data)

    def test_exports_keep_career_scope_attribution_and_paper_species_separate(self):
        self.profile["contributions"] = [contribution()]
        self.profile["model_organisms"] = [model()]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            source = path / "input.json"
            write_json(source, build_snapshot(self.source, self.registry))
            subprocess.run([sys.executable, str(ROOT / "pipeline/make_exports.py"), "--input", str(source),
                            "--output-dir", str(path / "exports"), "--start-year", "2020", "--end-year", "2020"],
                           check=True, capture_output=True, text=True)
            with (path / "exports" / "all_researchers.csv").open() as handle:
                counts = next(csv.DictReader(handle))
            with (path / "exports" / "researcher_contributions.csv").open() as handle:
                row = next(csv.DictReader(handle))
        self.assertEqual(counts["Model_organisms"], "Mouse")
        self.assertEqual(counts["Paper_species_mentions"], "")
        self.assertNotIn("Organisms", counts)
        self.assertEqual(row["Year"], "1999")
        self.assertEqual(row["Scope"], "career-wide")
        self.assertIn("Co-developed", row["Attribution"])
        self.assertEqual(row["Source"], SOURCE["url"])


if __name__ == "__main__":
    unittest.main()
