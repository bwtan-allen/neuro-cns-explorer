import copy
import unittest

from fixtures import record, snapshot
from pipeline.profiles import (
    apply_updates, claim, matching_fingerprint, migrate, name_parts, normalize_orcid,
    profile_for, validate_registry,
)


SOURCE = {"url": "https://example.org/fixture", "accessed": "2026-09-04", "supports": "Synthetic fixture claim"}


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.source = snapshot(record("Alice Lee", lab_start_year=2010))
        self.registry = migrate(self.source)
        self.profile = next(iter(self.registry["profiles"].values()))

    def test_migration_is_idempotent_and_does_not_promote_proxies(self):
        self.assertEqual(migrate(self.source, self.registry), self.registry)
        self.assertIsNone(self.profile["career"]["lab_start_year"]["value"])
        self.assertEqual(self.profile["career_proxies"]["orcid_employment_year"], 2010)
        self.assertEqual(self.profile["identity"]["status"], "unreviewed")

    def test_initial_collisions_do_not_merge_people(self):
        registry = migrate(snapshot(record("Alice Lee"), record("Alan Lee")))
        self.assertEqual(len(registry["profiles"]), 2)
        self.assertEqual(len(set(registry["profiles"])), 2)

    def test_surname_particles_and_explicit_compound_surnames(self):
        self.assertEqual(name_parts("Josefina del Marmol"), ("Josefina", "del Marmol"))
        self.assertEqual(name_parts("Bianca Jones Marlin", "Jones Marlin B"), ("Bianca", "Jones Marlin"))
        self.assertEqual(name_parts("Lee A"), ("", "Lee"))

    def test_renaming_preserves_id_and_audit_history(self):
        updated = apply_updates(self.registry, [{
            "researcher_id": self.profile["id"], "reason": "Correct display form",
            "changes": {"name": "Alice B. Lee"},
        }])
        self.assertEqual(updated["profiles"][self.profile["id"]]["id"], self.profile["id"])
        self.assertEqual(profile_for(self.source["records"][0], updated)["name"], "Alice B. Lee")
        self.assertEqual(updated["changes"][0]["before"]["name"], "Alice Lee")
        self.assertEqual(self.profile["name"], "Alice Lee")

    def test_source_backed_claims_require_evidence(self):
        broken = copy.deepcopy(self.registry)
        broken["profiles"][self.profile["id"]]["identity"] = claim("Alice Lee", "source-backed")
        with self.assertRaisesRegex(ValueError, "cite its evidence"):
            validate_registry(broken)

    def test_unknown_relationships_cannot_enter_identity_matching(self):
        broken = copy.deepcopy(self.registry)
        profile = broken["profiles"][self.profile["id"]]
        profile["affiliations"][0].update(claim())
        with self.assertRaisesRegex(ValueError, "unknown affiliation"):
            validate_registry(broken)

    def test_citation_does_not_turn_a_missing_date_into_an_established_fact(self):
        broken = copy.deepcopy(self.registry)
        broken["profiles"][self.profile["id"]]["career"]["lab_start_year"] = claim(None, "source-backed", [SOURCE])
        with self.assertRaisesRegex(ValueError, "established value"):
            validate_registry(broken)
    def test_ids_cannot_be_changed_by_curation(self):
        with self.assertRaisesRegex(ValueError, "IDs cannot change"):
            apply_updates(self.registry, [{
                "researcher_id": self.profile["id"], "reason": "Unsafe mutation", "changes": {"id": "new"},
            }])

    def test_matching_fingerprint_ignores_unrelated_career_changes(self):
        profile = copy.deepcopy(self.profile)
        original = matching_fingerprint(profile)
        profile["career"]["lab_start_year"] = claim(2017, "source-backed", [SOURCE])
        self.assertEqual(original, matching_fingerprint(profile))
        profile["aliases"].append({**claim("A. Lee"), "given": "Anne", "family": "Lee"})
        self.assertNotEqual(original, matching_fingerprint(profile))

    def test_orcid_checksum_is_checked(self):
        self.assertEqual(normalize_orcid("https://orcid.org/0000-0002-1825-0097"), "0000-0002-1825-0097")
        with self.assertRaises(ValueError):
            normalize_orcid("0000-0002-1825-0098")


if __name__ == "__main__":
    unittest.main()
