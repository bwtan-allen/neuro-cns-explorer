import csv
import datetime
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from xml.sax.saxutils import escape

from fixtures import record, snapshot


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import person_cns
import recount
import refresh_data
from data_quality import audit_dataset, validate_snapshot
from storage import write_json


def article(pmid="1", year=2025, epub=None, surname="Lee", initial="T",
            affiliation="Janelia Research Campus", pubtype="Journal Article",
            journal="Science (New York, N.Y.)", iso="Science"):
    electronic = (f'<ArticleDate DateType="Electronic"><Year>{epub}</Year></ArticleDate>'
                  if epub is not None else "")
    return (
        f'<PubmedArticle><MedlineCitation><PMID>{pmid}</PMID><Article>'
        f'<Journal><Title>{escape(journal)}</Title><ISOAbbreviation>{escape(iso)}</ISOAbbreviation>'
        f'<JournalIssue><PubDate><Year>{year}</Year></PubDate></JournalIssue></Journal>'
        f'<ArticleTitle>Synthetic parser fixture</ArticleTitle>{electronic}'
        f'<AuthorList><Author><LastName>{surname}</LastName><Initials>{initial}</Initials>'
        f'<ForeName>Test</ForeName><AffiliationInfo><Affiliation>{escape(affiliation)}</Affiliation>'
        f'</AffiliationInfo></Author></AuthorList><PublicationTypeList>'
        f'<PublicationType>{pubtype}</PublicationType></PublicationTypeList></Article></MedlineCitation>'
        f'<PubmedData><ArticleIdList><ArticleId IdType="doi">10.0000/fixture</ArticleId>'
        f'</ArticleIdList></PubmedData></PubmedArticle>'
    )


class PublicationTests(unittest.TestCase):
    def count(self, articles, common=True, expected_given_name=None):
        ids = [str(index + 1) for index in range(len(articles))]
        xml = "<PubmedArticleSet>" + "".join(articles) + "</PubmedArticleSet>"
        with mock.patch.object(person_cns, "esearch_all", return_value=ids), \
                mock.patch.object(person_cns, "call", return_value=xml):
            return person_cns.counts("Lee", "T", ["Janelia"], common=common,
                                     expected_given_name=expected_given_name)

    def test_science_full_title_in_both_matching_modes(self):
        self.assertEqual(person_cns._tier("Science (New York, N.Y.)"), "cns")
        for common in (True, False):
            with self.subTest(common=common):
                result = self.count([article(iso="")], common)
                self.assertEqual(result["cns"], {2025: 1})
                self.assertEqual(result["papers"][0]["pmid"], "1")
                self.assertEqual(result["papers"][0]["doi"], "10.0000/fixture")
                self.assertEqual(result["method_version"], person_cns.METHOD_VERSION)
                self.assertTrue(result["fetched_at"])

    def test_electronic_year_precedes_print_year(self):
        result = self.count([article(year=2026, epub=2025)])
        self.assertEqual(result["cns"], {2025: 1})
        self.assertEqual(result["papers"][0]["year"], 2025)

    def test_affiliation_must_belong_to_last_author(self):
        result = self.count([article(affiliation="Different Institute")])
        self.assertEqual(result["cns"], {})
        self.assertEqual(result["papers"], [])

    def test_last_author_initial_must_match(self):
        self.assertEqual(self.count([article(initial="X")])["cns"], {})

    def test_different_full_given_names_are_flagged_not_silently_removed(self):
        result = self.count([article()], expected_given_name="Tzumin")
        self.assertEqual(result["cns"], {2025: 1})
        self.assertIn("PubMed lists Test", result["papers"][0]["given_name_warning"])

    def test_news_does_not_define_first_qualifying_year(self):
        result = self.count([article(pmid="1", year=2005, pubtype="News"), article(pmid="2", year=2019)])
        self.assertEqual(result["first_pi_year"], 2019)
        self.assertEqual(result["cns"], {2019: 1})

    def test_incomplete_xml_is_not_saved_as_zero(self):
        with mock.patch.object(person_cns, "esearch_all", return_value=["1"]), \
                mock.patch.object(person_cns, "call", return_value="<PubmedArticleSet/>"):
            with self.assertRaisesRegex(RuntimeError, "incomplete article XML"):
                person_cns.counts("Lee", "T", ["Janelia"])

    def test_incomplete_search_is_not_truncated_silently(self):
        responses = [
            {"esearchresult": {"count": "2", "idlist": ["1"]}},
            {"esearchresult": {"count": "2", "idlist": []}},
        ]
        with mock.patch.object(person_cns, "call", side_effect=responses):
            with self.assertRaisesRegex(RuntimeError, "incomplete result page"):
                person_cns.esearch_all("synthetic query")

    def test_search_beyond_pubmed_limit_fails(self):
        with mock.patch.object(person_cns, "call", return_value={"esearchresult": {"count": "10000", "idlist": ["1"]}}):
            with self.assertRaisesRegex(RuntimeError, "9,999"):
                person_cns.esearch_all("synthetic query")

    def test_successful_empty_search_is_a_real_zero(self):
        with mock.patch.object(person_cns, "esearch_all", return_value=[]), \
                mock.patch.object(person_cns, "call") as call:
            result = person_cns.counts("Lee", "T", ["Janelia"])
        call.assert_not_called()
        self.assertEqual(result["cns"], {})
        self.assertEqual(result["papers"], [])
        self.assertEqual(result["method_version"], person_cns.METHOD_VERSION)


class CacheAndRefreshTests(unittest.TestCase):
    def test_cache_requires_current_method_inputs_and_timestamp(self):
        person = ("Lee", "T", "Janelia")
        cached = {
            "ln": "Lee", "ini": "T", "institution": "Janelia", "inst_keywords": ["Janelia"],
            "mode": "affil", "method_version": person_cns.METHOD_VERSION,
            "cns": {}, "field": {}, "elife": {}, "papers": [], "query": "synthetic",
            "expected_given_name": "Fixture",
            "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        self.assertTrue(recount.cache_current(cached, "Fixture Investigator", person))
        self.assertFalse(recount.cache_current({**cached, "method_version": 0}, "Fixture Investigator", person))
        self.assertFalse(recount.cache_current({**cached, "fetched_at": "2000-01-01T00:00:00+00:00"},
                                              "Fixture Investigator", person))
        self.assertFalse(recount.cache_current(cached, "Fixture Investigator", ("Lee", "T", "Stanford")))
        self.assertFalse(recount.cache_current(cached, "Fixture Investigator", person, max_age_days=0))

    def test_failed_recount_preserves_previous_result(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "sample.json"
            previous = {"Fixture Investigator": {"cns": {"2020": 2}}}
            write_json(output, previous)
            with mock.patch.object(recount, "roster", {"Fixture Investigator": ("Lee", "T", "Janelia")}), \
                    mock.patch.object(recount.P, "counts", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "previous results"):
                    recount.main(["--force", "--output", str(output)])
            self.assertEqual(json.loads(output.read_text()), previous)

    def test_dry_run_does_not_query_or_create_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "sample.json"
            with mock.patch.object(recount, "roster", {"Fixture Investigator": ("Lee", "T", "Janelia")}), \
                    mock.patch.object(recount.P, "counts") as counts:
                self.assertEqual(recount.main(["--limit", "1", "--dry-run", "--output", str(output)]), 0)
            counts.assert_not_called()
            self.assertFalse(output.exists())

    def test_pubmed_initial_names_do_not_become_given_names(self):
        self.assertIsNone(recount.given_name_for("Lee T"))
        self.assertIsNone(recount.given_name_for("J. Nicholas Betley"))
        self.assertEqual(recount.given_name_for("Xiaowei Zhuang"), "Xiaowei")

    def test_atomic_write_preserves_old_file_on_serialization_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            write_json(path, {"old": True})
            with self.assertRaises(TypeError):
                write_json(path, {"invalid": object()})
            self.assertEqual(json.loads(path.read_text()), {"old": True})
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_refresh_checks_subprocess_exit_status(self):
        with mock.patch.object(refresh_data.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "fixture")) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                refresh_data.run("fixture.py")
            self.assertTrue(run.call_args.kwargs["check"])

    def test_failed_discovery_leaves_previous_cache_intact(self):
        import discover
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "disc_Fixture.json"
            write_json(cache, [{"previous": True}])
            with mock.patch.object(refresh_data, "DATA", directory), \
                    mock.patch.object(discover, "INST", {"Fixture": None}), \
                    mock.patch.object(refresh_data, "run", side_effect=subprocess.CalledProcessError(1, "fixture")):
                with self.assertRaises(subprocess.CalledProcessError):
                    refresh_data.main([])
            self.assertEqual(json.loads(cache.read_text()), [{"previous": True}])


class SnapshotTests(unittest.TestCase):
    def test_subset_conflicts_are_flagged_without_rewriting_counts(self):
        data = snapshot(record(noncns_total=0, noncns_by_year={"2019": 0, "2020": 0}))
        codes = {issue["Code"] for issue in audit_dataset(data)}
        self.assertIn("noncns_subset_total", codes)
        self.assertIn("noncns_subset_years", codes)
        self.assertEqual(data["records"][0]["noncns_total"], 0)

    def test_unavailable_is_not_zero(self):
        data = snapshot(record(noncns_available=False, noncns_total=None,
                               noncns_by_year={"2019": None, "2020": None}))
        codes = {issue["Code"] for issue in audit_dataset(data)}
        self.assertIn("missing_noncns", codes)
        self.assertNotIn("noncns_subset_total", codes)

    def test_invalid_years_and_counts_are_rejected(self):
        for data in ({"years": [], "records": []}, {"years": [2020, 2020], "records": []},
                     snapshot(record(cns_total=-1)), snapshot(record(cns_by_year={"2019": 2}))):
            with self.subTest(data=data):
                with self.assertRaises(ValueError):
                    validate_snapshot(data)

    def test_evidence_must_reconcile_with_annual_counts(self):
        data = snapshot(record(count_method_version=2, count_fetched_at="2026-09-01T00:00:00+00:00",
                               publications=[]))
        self.assertIn("paper_evidence_mismatch", {issue["Code"] for issue in audit_dataset(data)})

    def test_malformed_paper_evidence_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "publication evidence"):
            validate_snapshot(snapshot(record(publications=[{"pmid": "123"}])))

    def build(self, directory, extra=None):
        data_dir = Path(directory) / "data"
        data_dir.mkdir()
        files = {
            "candidates2.json": [{"ln": "sample", "ini": "A", "name": "Sample A", "cns": 2, "insts": ["Janelia"]}],
            "ident.json": {"Sample A": ["Alice Sample", "Janelia", "neuroscience", "core"]},
            "disc_Janelia.json": [
                {"pmid": str(year), "yr": year, "ln": "sample", "ini": "A", "neuro": True}
                for year in (2019, 2020)
            ],
        }
        files.update(extra or {})
        for filename, data in files.items():
            write_json(data_dir / filename, data)
        output = Path(directory) / "preview.json"
        subprocess.run([sys.executable, str(ROOT / "pipeline/build_dataset.py"), str(data_dir), str(output)],
                       check=True, capture_output=True, text=True)
        return json.loads(output.read_text())

    def test_builder_does_not_turn_missing_non_cns_into_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.build(directory)["records"][0]
        self.assertFalse(result["noncns_available"])
        self.assertIsNone(result["noncns_total"])
        self.assertTrue(all(value is None for value in result["noncns_by_year"].values()))

    def test_builder_keeps_successful_empty_cache_as_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.build(directory, {"cand_noncns.json": {"Sample A": {}}})["records"][0]
        self.assertTrue(result["noncns_available"])
        self.assertEqual(result["noncns_total"], 0)

    def test_builder_skipped_common_name_is_unavailable(self):
        extra = {
            "awards.json": [{"name": "Bob Example", "institution": "Janelia", "award": "Fixture Award", "year": 2020}],
            "awards_enrich.json": {"Bob Example": {"common_name": True, "cns_by_year": {}, "noncns_by_year": {}}},
        }
        with tempfile.TemporaryDirectory() as directory:
            result = next(r for r in self.build(directory, extra)["records"] if r["name"] == "Bob Example")
        self.assertFalse(result["cns_available"])
        self.assertFalse(result["noncns_available"])
        self.assertIsNone(result["cns_total"])
        self.assertIsNone(result["cns_gap_years"])

    def test_builder_does_not_pick_an_ambiguous_initial_match(self):
        cached = {"cns": {"2019": 100}, "field": {}, "elife": {}, "mode": "name", "ln": "sample", "ini": "A"}
        with tempfile.TemporaryDirectory() as directory:
            data = self.build(directory, {"recount.json": {"Ann Sample": cached, "Alex Sample": cached}})
        result = data["records"][0]
        self.assertEqual(result["cns_total"], 2)
        self.assertIn("Ambiguous", result["identity_warning"])

    def test_builder_propagates_evidence_and_limits_totals_to_window(self):
        cached = {
            "cns": {"2010": 9, "2019": 1}, "field": {}, "elife": {}, "mode": "name",
            "method_version": 2, "fetched_at": "2026-09-01T00:00:00+00:00", "query": "synthetic",
            "papers": [{"pmid": "123", "year": 2019, "tier": "cns", "journal": "Science",
                        "title": "Synthetic fixture", "last_author": "Alice Sample", "match": "fixture",
                        "url": "https://pubmed.ncbi.nlm.nih.gov/123/"}],
        }
        with tempfile.TemporaryDirectory() as directory:
            result = self.build(directory, {"recount.json": {"Alice Sample": cached}})["records"][0]
        self.assertEqual(result["cns_total"], 1)
        self.assertEqual(result["count_method_version"], 2)
        self.assertEqual(result["publications"], cached["papers"])

    def test_builder_refuses_inconsistent_versioned_evidence(self):
        cached = {"cns": {"2019": 1}, "field": {}, "elife": {}, "mode": "name",
                  "method_version": 2, "fetched_at": "2026-09-01T00:00:00+00:00", "papers": []}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "preview.json"
            write_json(output, {"previous": True})
            with self.assertRaises(subprocess.CalledProcessError):
                self.build(directory, {"recount.json": {"Alice Sample": cached}})
            self.assertEqual(json.loads(output.read_text()), {"previous": True})

    def test_csv_uses_actual_window_and_preserves_unknowns(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "preview.json"
            output = Path(directory) / "exports"
            write_json(source, snapshot(record(noncns_available=False, noncns_total=None)))
            subprocess.run([sys.executable, str(ROOT / "pipeline/make_exports.py"), "--input", str(source),
                            "--output-dir", str(output)], check=True, capture_output=True, text=True)
            self.assertNotIn(b"\r\n", (output / "all_researchers.csv").read_bytes())
            with (output / "all_researchers.csv").open() as handle:
                row = next(csv.DictReader(handle))
        self.assertEqual(row["CNS_avg_per_yr"], "1.0")
        self.assertEqual(row["nonCNS_total"], "")
        self.assertEqual(row["Authorship_measure"], "last-author proxy")


if __name__ == "__main__":
    unittest.main()
