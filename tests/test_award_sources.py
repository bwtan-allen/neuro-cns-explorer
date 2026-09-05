import copy
import unittest

from fixtures import record, snapshot
from pipeline.award_sources import corroborate, parse_recipients
from pipeline.profiles import claim, migrate


HTML = """
<h3>2017-2019</h3>
<p><strong><a href="https://example.org/lab">Alice Example, Ph.D.,</a></strong>
Assistant Professor, Harvard University</p>
<p>A project description mentioning Alice Example is not a second recipient.</p>
<h3>2018-2020</h3>
<p><strong>Alex Example, Ph.D.</strong> Professor, Stanford University</p>
"""


class AwardSourceTests(unittest.TestCase):
    def setUp(self):
        self.registry = migrate(snapshot(record("Alice Example", "Harvard University")))
        self.profile = next(iter(self.registry["profiles"].values()))
        self.profile["awards"] = [{**claim("McKnight Scholar"), "year": 2017}]

    def test_cohort_year_and_recipient_line_are_extracted(self):
        recipients = parse_recipients(HTML)
        self.assertEqual(len(recipients), 2)
        self.assertEqual(recipients[0]["name"], "Alice Example")
        self.assertEqual(recipients[0]["year"], 2017)
        self.assertEqual(recipients[0]["period"], "2017-2019")

    def test_name_year_and_institution_must_all_match(self):
        recipients = parse_recipients(HTML)
        updates, report = corroborate(self.registry, recipients, "2026-09-04")
        self.assertEqual(len(updates), 1)
        self.assertTrue(report[0]["corroborated"])
        self.assertEqual(updates[0]["changes"]["awards"][0]["status"], "source-backed")
        self.assertEqual(self.profile["awards"][0]["status"], "unreviewed")
        for field, value in (("year", 2018), ("context", "Alice Example at Stanford University"), ("name", "Alex Example")):
            altered = copy.deepcopy(recipients)
            altered[0][field] = value
            self.assertEqual(corroborate(self.registry, altered, "2026-09-04")[0], [])

    def test_layout_failure_does_not_produce_empty_success(self):
        with self.assertRaisesRegex(ValueError, "layout"):
            parse_recipients("<h1>Access denied</h1>")

    def test_one_source_recipient_cannot_confirm_multiple_identities(self):
        registry = migrate(snapshot(record("Alice B. Example", "Harvard University")), self.registry)
        updates, report = corroborate(registry, parse_recipients(HTML), "2026-09-04")
        self.assertEqual(updates, [])
        self.assertFalse(report[0]["corroborated"])

    def test_unrelated_sections_are_not_treated_as_award_recipients(self):
        html = HTML + "<h2>Selection committee</h2><p><strong>Bob Committee, Ph.D.</strong> Harvard University</p>"
        self.assertEqual(len(parse_recipients(html)), 2)


if __name__ == "__main__":
    unittest.main()
