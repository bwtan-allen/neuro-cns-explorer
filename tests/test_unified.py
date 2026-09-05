import copy
import datetime
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fixtures import record, snapshot
from pipeline.data_quality import audit_dataset
from pipeline.evidence import EvidenceStore
from pipeline.profiles import claim, matching_fingerprint, migrate
from pipeline.inst_keywords import keywords_for
from pipeline.snapshot import build_snapshot, project_snapshot
from pipeline.taxonomy import classify
from pipeline import unified_recount as unified


SOURCE = {"url": "https://example.org/fixture", "accessed": "2026-09-04", "supports": "Synthetic fixture claim"}


def paper(pmid="1", tier="cns", year=2019, **overrides):
    value = {
        "pmid": pmid, "title": "Mouse neural circuits imaged with calcium imaging",
        "journal": "Science", "journal_abbreviation": "Science", "doi": "",
        "tier": tier, "year": year, "electronic_year": year, "print_year": year,
        "publication_types": ["Journal Article"], "retracted": False,
        "last_author": "Xiaowei Zhuang", "last_author_given": "Xiaowei",
        "last_author_family": "Zhuang", "last_author_initials": "X",
        "last_author_affiliations": ["Harvard University, Cambridge, MA"],
        "last_author_orcids": [], "mesh": ["Mice", "Neurons"], "keywords": [],
        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", "retrieved_at": "2026-09-04T00:00:00+00:00",
    }
    value.update(overrides)
    value.update(classify(value["title"], value["mesh"], value["keywords"]))
    return value


def result(profile, papers):
    decisions = []
    for item in papers:
        decision, reason = unified.decide(profile, item, 2019, 2020)
        decisions.append({**item, "decision": decision, "reason": reason})
    return {
        "researcher_id": profile["id"], "query": unified.query_for(profile, 2019, 2020),
        "start_year": 2019, "end_year": 2020,
        "method_version": unified.METHOD_VERSION, "profile_fingerprint": matching_fingerprint(profile),
        "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "papers": decisions, "count_policy": "Synthetic all-journal fixture",
    }


class UnifiedTests(unittest.TestCase):
    def setUp(self):
        self.source = snapshot(record("Xiaowei Zhuang", "Harvard University"))
        self.registry = migrate(self.source)
        self.profile = next(iter(self.registry["profiles"].values()))

    def test_full_given_name_collision_is_excluded(self):
        self.assertEqual(unified.decide(self.profile, paper(last_author_given="Xiaoxi"), 2019, 2020),
                         ("excluded", "different_full_given_name"))

    def test_all_journal_tiers_use_the_same_matching_policy(self):
        for tier in ("cns", "field", "elife", "other"):
            with self.subTest(tier=tier):
                self.assertEqual(unified.decide(self.profile, paper(tier=tier), 2019, 2020)[0], "included")
                self.assertEqual(unified.decide(self.profile, paper(tier=tier, last_author_given="Xiaoxi"),
                                                2019, 2020)[0], "excluded")

    def test_missing_full_name_or_affiliation_remains_unresolved(self):
        self.assertEqual(unified.decide(self.profile, paper(last_author_given="X"), 2019, 2020)[0], "unresolved")
        self.assertEqual(unified.decide(self.profile, paper(last_author_affiliations=[]), 2019, 2020)[0], "unresolved")

    def test_explicit_aliases_can_resolve_a_name_variant(self):
        variant = paper(last_author_given="Wei")
        self.assertEqual(unified.decide(self.profile, variant, 2019, 2020)[0], "excluded")
        self.profile["aliases"].append({**claim("Wei Zhuang"), "given": "Wei", "family": "Zhuang"})
        self.assertEqual(unified.decide(self.profile, variant, 2019, 2020)[0], "included")

    def test_leading_initials_need_a_shared_full_given_component(self):
        for expected, observed, matched in (
            ("H. Robert", "H Robert", True), ("H. Robert", "Howard Robert", True),
            ("S. Lawrence", "S Lawrence", True), ("E. Josephine", "E Josephine", True),
            ("H. Robert", "H R", False), ("David J", "D John", False),
            ("David J", "David X", False), ("Li-Huei", "Li Huei", True),
        ):
            with self.subTest(expected=expected, observed=observed):
                self.assertEqual(unified.given_matches(expected, observed), matched)

    def test_only_source_backed_orcid_bypasses_name_and_affiliation(self):
        self.profile["orcid"] = claim("0000-0002-1825-0097")
        candidate = paper(last_author_given="W", last_author_affiliations=[],
                          last_author_orcids=["0000-0002-1825-0097"])
        self.assertEqual(unified.decide(self.profile, candidate, 2019, 2020)[0], "excluded")
        self.profile["orcid"] = claim("0000-0002-1825-0097", "source-backed", [SOURCE])
        self.assertEqual(unified.decide(self.profile, candidate, 2019, 2020),
                         ("included", "last_author_orcid"))

    def test_conflicting_orcid_cannot_fall_back_to_a_weaker_name_match(self):
        self.profile["orcid"] = claim("0000-0002-1825-0097", "source-backed", [SOURCE])
        candidate = paper(last_author_orcids=["0000-0001-6175-3872"])
        self.assertEqual(unified.decide(self.profile, candidate, 2019, 2020),
                         ("unresolved", "conflicting_last_author_orcid"))

    def test_universal_eligibility_cannot_be_overridden(self):
        self.profile["paper_overrides"] = [{"pmid": "1", "decision": "include", "reason": "Fixture", "sources": [SOURCE]}]
        for candidate in (paper(year=2021), paper(retracted=True), paper(publication_types=["News"])):
            with self.subTest(candidate=candidate):
                self.assertEqual(unified.decide(self.profile, candidate, 2019, 2020)[0], "excluded")

    def test_biological_retraction_is_not_a_retraction_notice(self):
        self.assertEqual(unified.decide(self.profile, paper(title="Axon retraction in developing neurons"), 2019, 2020)[0],
                         "included")

    def test_query_uses_last_author_index_without_journal_restrictions(self):
        query = unified.query_for(self.profile, 2019, 2020)
        self.assertIn("[LAUT]", query)
        self.assertIn('"Zhuang X*"[LAUT]', query)
        self.assertIn('"Harvard University"[ad]', query)
        self.assertIn('"2019"[dp]:"2020"[dp]', query)
        self.assertNotIn("Science", query)

    def test_large_search_splits_and_deduplicates_boundary_papers(self):
        with mock.patch.object(unified.pubmed, "esearch_all", side_effect=[
            unified.pubmed.SearchTooLarge("fixture"), ["1"], ["1", "2"],
        ]):
            self.assertEqual(unified.search(self.profile, 2019, 2020), ["1", "2"])

    def test_retrieval_failure_does_not_return_successful_empty_result(self):
        with mock.patch.object(unified.pubmed, "esearch_all", return_value=["1"]), \
                mock.patch.object(unified.pubmed, "call", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "previous evidence"):
                unified.recount(self.profile, 2019, 2020)

    def test_window_and_profile_changes_invalidate_cache(self):
        metadata = result(self.profile, [])
        self.assertTrue(unified.cache_current(metadata, self.profile, 2019, 2020))
        self.assertFalse(unified.cache_current(metadata, self.profile, 2019, 2021))
        updated = copy.deepcopy(self.profile)
        updated["affiliations"] = []
        self.assertFalse(unified.cache_current(metadata, updated, 2019, 2020))

    def test_offline_reclassification_preserves_retrieval_date(self):
        original = result(self.profile, [paper()])
        updated = unified.reclassify(self.profile, original)
        self.assertEqual(updated["fetched_at"], original["fetched_at"])
        self.assertIn("reclassified_at", updated)
        self.profile["affiliations"].append({**claim("MIT"), "institution": "Massachusetts Institute of Technology"})
        with self.assertRaisesRegex(ValueError, "fresh recount"):
            unified.reclassify(self.profile, original)

    def test_new_override_ids_require_retrieval_not_offline_relabeling(self):
        original = result(self.profile, [paper()])
        self.profile["paper_overrides"] = [{"pmid": "2", "decision": "exclude", "reason": "Fixture", "sources": [SOURCE]}]
        with self.assertRaisesRegex(ValueError, "fresh recount"):
            unified.reclassify(self.profile, original)

    def test_institution_aliases_do_not_guess_other_institutions(self):
        self.assertEqual(keywords_for("Smith College", fallback=False), [])
        self.assertIn("University of British Columbia", keywords_for("University of British Columbia", fallback=False))
        self.assertNotIn("Columbia University", keywords_for("University of British Columbia", fallback=False))
        self.assertNotIn("Massachusetts", keywords_for("University of Massachusetts Medical School", fallback=False))

    def test_taxonomy_does_not_infer_rat_from_rates(self):
        tags = classify("Firing rates in neural circuits")
        self.assertNotIn("Rat", tags["organisms"])
        self.assertIn("Mouse", classify("Mouse neuronal imaging")["organisms"])
        self.assertIn("Calcium imaging", classify("Calcium imaging of neurons")["methods"])


class EvidenceAndWindowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = Path(self.directory.name) / "evidence.sqlite3"
        self.source = snapshot(record("Xiaowei Zhuang", "Harvard University"))
        self.registry = migrate(self.source)
        self.profile = next(iter(self.registry["profiles"].values()))
        self.papers = [paper("1", "cns", 2019), paper("2", "field", 2019),
                       paper("3", "elife", 2020), paper("4", "other", 2020)]

    def publish(self):
        with EvidenceStore(self.database) as store:
            store.save(self.profile["id"], result(self.profile, self.papers))
            return build_snapshot(self.source, self.registry, store)

    def test_one_ledger_derives_consistent_all_journal_counts(self):
        snapshot_data = self.publish()
        row = snapshot_data["records"][0]
        self.assertEqual(row["cns_total"], 1)
        self.assertEqual(row["noncns_total"], 3)
        self.assertEqual(row["fieldtier_total"], 1)
        self.assertEqual(row["elife_total"], 1)
        self.assertEqual(row["publication_model"], "unified-papers")
        self.assertFalse(any(issue["Severity"] == "Conflict" for issue in audit_dataset(snapshot_data)))

    def test_publications_are_normalized_across_researcher_runs(self):
        second = copy.deepcopy(self.profile)
        second["id"] = "pi_" + "a" * 32
        with EvidenceStore(self.database) as store:
            store.save(self.profile["id"], result(self.profile, [self.papers[0]]))
            store.save(second["id"], result(second, [self.papers[0]]))
            self.assertEqual(store.coverage(), {"researchers": 2, "publications": 1})

    def test_failed_update_rolls_back_metadata_and_matches(self):
        original = result(self.profile, [self.papers[0]])
        with EvidenceStore(self.database) as store:
            store.save(self.profile["id"], original)
            broken = result(self.profile, [self.papers[1], self.papers[2]])
            broken["papers"][1]["title"] = object()
            with self.assertRaises(TypeError):
                store.save(self.profile["id"], broken)
            self.assertEqual(store.result(self.profile["id"])["papers"][0]["pmid"], "1")
            self.assertEqual(store.coverage(), {"researchers": 1, "publications": 1})

    def test_selected_years_recompute_counts_and_tags(self):
        data = self.publish()
        selected = project_snapshot(data, 2020, 2020)
        row = selected["records"][0]
        self.assertEqual(selected["years"], [2020])
        self.assertEqual(row["cns_total"], 0)
        self.assertEqual(row["noncns_total"], 2)
        self.assertEqual(row["fieldtier_total"], 0)
        self.assertEqual({item["pmid"] for item in row["publications"]}, {"3", "4"})

    def test_uncounted_years_remain_unknown_and_old_window_remains_usable(self):
        with EvidenceStore(self.database) as store:
            store.save(self.profile["id"], result(self.profile, self.papers))
            expanded = build_snapshot(self.source, self.registry, store, 2019, 2021)
        self.assertIsNone(expanded["records"][0]["cns_total"])
        self.assertIsNone(expanded["records"][0]["cns_by_year"]["2021"])
        self.assertEqual(project_snapshot(expanded, 2019, 2020)["records"][0]["cns_total"], 1)

    def test_active_year_rate_requires_source_backed_independence(self):
        data = self.publish()
        self.assertIsNone(data["records"][0]["cns_per_active_year"])
        self.profile["career"]["lab_start_year"] = claim(2020, "source-backed", [SOURCE])
        with EvidenceStore(self.database, readonly=True) as store:
            updated = build_snapshot(self.source, self.registry, store)
        self.assertTrue(updated["records"][0]["lab_start_verified"])
        self.assertEqual(updated["records"][0]["active_years_in_window"], 1)
        self.assertEqual(updated["records"][0]["cns_per_active_year"], 0.0)

    def test_excluded_namesakes_are_visible_but_not_counted(self):
        self.papers.append(paper("5", "field", 2020, last_author_given="Xiaoxi"))
        data = self.publish()
        row = data["records"][0]
        self.assertEqual(row["fieldtier_total"], 1)
        self.assertEqual(row["excluded_publications"][0]["reason"], "different_full_given_name")
        self.assertIn("excluded_given_names", {item["Code"] for item in audit_dataset(data)})

    def test_unresolved_initial_only_identity_does_not_inherit_legacy_zeros(self):
        source = snapshot(record("Zhang K", cns_total=0, cns_by_year={"2019": 0, "2020": 0}))
        data = build_snapshot(source, migrate(source))
        row = data["records"][0]
        self.assertIsNone(row["cns_total"])
        self.assertIsNone(row["noncns_total"])
        self.assertEqual(row["legacy_counts"]["cns_total"], 0)
        self.assertEqual(row["publication_model"], "unresolved-identity")

    def test_empty_roster_cannot_replace_a_published_snapshot(self):
        with self.assertRaisesRegex(ValueError, "source roster is empty"):
            build_snapshot(snapshot(), self.registry)


if __name__ == "__main__":
    unittest.main()
