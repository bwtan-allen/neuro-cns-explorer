"""Small synthetic records for offline regression coverage."""


def record(name="Fixture Investigator", institution="Fixture Institute", **overrides):
    result = {
        "name": name, "institution": institution, "group": "early-career awardee",
        "field": "neuroscience", "neuro_confidence": "core", "career_stage": "rising (<=6y)",
        "lab_age": 3, "lab_age_source": "first-paper~", "first_senior_paper_yr": 2017,
        "lab_start_year": None, "award_names": "Fixture Award", "n_awards": 1,
        "cns_total": 2, "cns_by_year": {"2019": 1, "2020": 1},
        "noncns_total": 4, "noncns_by_year": {"2019": 2, "2020": 2}, "noncns_available": True,
        "fieldtier_total": 1, "fieldtier_by_year": {"2019": 1, "2020": 0},
        "elife_total": 1, "elife_by_year": {"2019": 0, "2020": 1}, "fieldjournals_available": True,
        "count_source": "person_cns(name)",
    }
    result.update(overrides)
    return result


def snapshot(*records):
    return {"years": [2019, 2020], "records": list(records), "generated": "2021-01-01"}
