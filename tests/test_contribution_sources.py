import copy
import tempfile
import unittest
from pathlib import Path

from fixtures import record, snapshot
from pipeline.contribution_backfill import apply_curations, merge_curations, prepare_batches
from pipeline.contribution_sources import author_matches, author_query_name, clean_text, paper_record, query_name
from pipeline.profiles import migrate
from pipeline.storage import write_json
from test_research_context import contribution


class ContributionSourceTests(unittest.TestCase):
    def setUp(self):
        self.registry = migrate(snapshot(record("Alice Example", "Example Institute")))
        self.profile = next(iter(self.registry["profiles"].values()))
        self.source = {
            "source": "MED", "pmid": "123", "doi": "10.0000/fixture", "title": "A bounded scientific finding",
            "pubYear": "2003", "pubTypeList": {"pubType": ["Journal Article"]},
            "authorList": {"author": [
                {"firstName": "Team", "lastName": "Author"},
                {"firstName": "Alice", "lastName": "Example",
                 "authorAffiliationDetailsList": {"authorAffiliation": [{"affiliation": "Example Institute; person@example.org"}]}},
            ]},
            "abstractText": "<h4>Finding</h4>A useful result.",
        }

    def test_candidate_preserves_coauthors_and_explicit_identity_match(self):
        paper = paper_record(self.source, self.profile)
        self.assertEqual(paper["pmid"], "123")
        self.assertEqual(paper["matched_authors"][0]["name"], "Alice Example")
        self.assertEqual(paper["matched_authors"][0]["position"], 2)
        self.assertEqual(paper["matched_authors"][0]["match"], "full-name")
        self.assertNotIn("@", paper["matched_authors"][0]["affiliations"][0])

    def test_reviews_and_namesakes_are_not_contribution_candidates(self):
        review = copy.deepcopy(self.source)
        review["pubTypeList"]["pubType"].append("Review")
        self.assertIsNone(paper_record(review, self.profile))
        namesake = copy.deepcopy(self.source)
        namesake["authorList"]["author"][1]["firstName"] = "Alan"
        self.assertIsNone(paper_record(namesake, self.profile))

    def test_initials_are_not_reported_as_verified_full_name(self):
        self.assertEqual(author_matches(self.profile, {"firstName": "A", "lastName": "Example"}), "initials-only")

    def test_display_annotations_do_not_become_surnames(self):
        barres = {"name": "Ben Barres (d.2017)", "aliases": [{"given": "Ben Barres", "family": "(d.2017)"}]}
        self.assertEqual(query_name(barres), ("Ben", "Barres", "B"))

    def test_queries_remove_diacritics_without_changing_identity(self):
        profile = {"name": "Sergiu Pa\u0219ca", "aliases": [{"given": "Sergiu", "family": "Pa\u0219ca"}]}
        self.assertEqual(author_query_name(profile), "Pasca S")
        self.assertEqual(profile["aliases"][0]["family"], "Pa\u0219ca")
        self.assertEqual(author_query_name(profile, full=True), "Pasca Sergiu")

    def test_inline_and_escaped_title_markup_preserves_molecular_names(self):
        self.assertEqual(clean_text("Vitamin B&lt;sub&gt;12&lt;/sub&gt;"), "Vitamin B12")
        self.assertEqual(clean_text("Ca<sup>2+</sup> and <i>Drosophila</i>"), "Ca2+ and Drosophila")
        self.assertEqual(clean_text("<h4>Background</h4><p>Result</p>"), "Background Result")

    def test_prepared_batches_do_not_duplicate_assignments(self):
        candidates = {self.profile["id"]: {"researcher_id": self.profile["id"], "papers": [paper_record(self.source, self.profile)]}}
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(len(prepare_batches(self.registry, candidates, Path(directory), 1)), 1)
            self.assertEqual(prepare_batches(self.registry, candidates, Path(directory), 1), [])

    def test_curations_preserve_existing_work_and_reject_wrong_doi(self):
        candidate = paper_record(self.source, self.profile)
        candidates = {self.profile["id"]: {"papers": [candidate]}}
        item = copy.deepcopy(contribution())
        item["year"] = 2003
        item["sources"][0].update({"pmid": "123", "doi": "10.0000/fixture"})
        entry = {"researcher_id": self.profile["id"], "status": "complete", "reason": "Source-reviewed example.", "contributions": [item]}
        updated, report = apply_curations(self.registry, [entry], candidates)
        self.assertEqual(report[self.profile["id"]]["contributions"], 1)
        self.assertEqual(self.profile["contributions"], [])
        with self.assertRaisesRegex(ValueError, "preserve existing"):
            apply_curations(updated, [entry], candidates)
        item["sources"][0]["doi"] = "10.0000/wrong"
        with self.assertRaisesRegex(ValueError, "DOI/PMID"):
            apply_curations(self.registry, [entry], candidates)

    def test_unresolved_identity_is_reviewed_without_a_fabricated_contribution(self):
        entry = {"researcher_id": self.profile["id"], "status": "needs-review",
                 "reason": "Two different authors share this initial; no source establishes the correct identity.",
                 "contributions": []}
        updated, report = apply_curations(self.registry, [entry], {})
        profile = updated["profiles"][self.profile["id"]]
        self.assertEqual(profile["contributions"], [])
        self.assertEqual(profile["contribution_review"]["status"], "needs-review")
        self.assertEqual(report[self.profile["id"]]["contributions"], 0)

    def test_full_roster_guard_prevents_publishing_partial_batches(self):
        with self.assertRaisesRegex(ValueError, "Full-roster review is incomplete"):
            apply_curations(self.registry, [], {}, require_all=True)
        entry = {"researcher_id": self.profile["id"], "status": "needs-review",
                 "reason": "Identity cannot be established from available evidence.", "contributions": []}
        updated, _ = apply_curations(self.registry, [entry], {}, require_all=True)
        self.assertEqual(updated["profiles"][self.profile["id"]]["contribution_review"]["status"], "needs-review")

    def test_anchor_year_and_citation_title_must_match_evidence(self):
        candidate = paper_record(self.source, self.profile)
        candidates = {self.profile["id"]: {"papers": [candidate]}}
        for changes in ({"year": 1999}, {"sources": [{
            "url": "https://pubmed.ncbi.nlm.nih.gov/123/", "pmid": "123",
            "title": "A different paper", "accessed": "2026-09-05", "supports": "A fixture claim.",
        }]}):
            with self.subTest(changes=changes):
                item = copy.deepcopy(contribution())
                item["year"] = 2003
                item["sources"][0].update({"pmid": "123", "doi": "10.0000/fixture"})
                item.update(changes)
                entry = {"researcher_id": self.profile["id"], "status": "complete",
                         "reason": "Source-reviewed example.", "contributions": [item]}
                with self.assertRaises(ValueError):
                    apply_curations(self.registry, [entry], candidates)

    def test_initial_only_paper_does_not_establish_identity_by_itself(self):
        candidate = paper_record(self.source, self.profile)
        candidate["matched_authors"][0]["match"] = "initials-only"
        item = copy.deepcopy(contribution())
        item["year"] = 2003
        item["sources"][0]["pmid"] = "123"
        entry = {"researcher_id": self.profile["id"], "status": "complete",
                 "reason": "Only initials match.", "contributions": [item]}
        with self.assertRaisesRegex(ValueError, "initials-only"):
            apply_curations(self.registry, [entry], {self.profile["id"]: {"papers": [candidate]}})

    def test_actual_single_author_credit_is_allowed_without_inventing_collaborators(self):
        source = copy.deepcopy(self.source)
        source["authorList"]["author"] = source["authorList"]["author"][1:]
        candidate = paper_record(source, self.profile)
        item = copy.deepcopy(contribution())
        item["year"] = 2003
        item["attribution"] = "Sole-authored primary paper by Alice Example."
        item["sources"][0]["pmid"] = "123"
        entry = {"researcher_id": self.profile["id"], "status": "complete",
                 "reason": "The primary metadata lists one author.", "contributions": [item]}
        updated, _ = apply_curations(self.registry, [entry], {self.profile["id"]: {"papers": [candidate]}})
        self.assertEqual(updated["profiles"][self.profile["id"]]["contributions"][0]["attribution"], item["attribution"])
        multiple = paper_record(self.source, self.profile)
        with self.assertRaisesRegex(ValueError, "collaborative credit"):
            apply_curations(self.registry, [entry], {self.profile["id"]: {"papers": [multiple]}})

    def test_identity_reviews_require_an_explicit_override_not_silent_batch_order(self):
        original = {"researcher_id": self.profile["id"], "status": "needs-review", "contributions": []}
        reviewed = {**original, "reason": "Original label is a duplicate, established by official sources."}
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / "draft.json", Path(directory) / "reviewed.json"
            write_json(first, [original])
            write_json(second, [reviewed])
            with self.assertRaisesRegex(ValueError, "Overlapping ordinary"):
                merge_curations([first, second])
            self.assertEqual(merge_curations([first], [second]), [reviewed])


if __name__ == "__main__":
    unittest.main()
