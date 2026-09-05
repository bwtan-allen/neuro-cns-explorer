"""Export last-author counts, preserving unknown values and source metadata."""
import argparse
import csv
import json
import sys
from pathlib import Path

from data_quality import count_available, validate_snapshot


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.profiles import profile_evidence
from pipeline.snapshot import project_snapshot
from pipeline.data_quality import record_issues


def write(path, records, years, rows_filter, sort_key, career_year):
    rows = sorted([record for record in records if rows_filter(record)], key=sort_key, reverse=True)
    with path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow([
            'Name', 'Group', 'Institution', 'Field', 'Awards', 'CNS_total', 'CNS_avg_per_yr',
            'CNS_years_covered', 'CNS_gap_years', 'NeuronNatNeuro_total', 'eLife_total', 'nonCNS_total',
            'Lab_start_year', 'First_senior_paper', 'Career_stage', 'Count_source',
            'Authorship_measure', 'Career_reference_year', 'Lab_age_source', 'Count_fetched_at', 'Count_method_version',
            'Researcher_ID', 'Publication_model', 'Identity_status', 'Current_institution', 'Institution_status',
            'HHMI_status', 'HHMI_source_status', 'Topics', 'Methods', 'Organisms',
            'Active_years_in_window', 'CNS_per_active_year', 'Unresolved_papers', 'Source_URLs', 'Review_notes',
            'Faculty_appointment_year', 'Faculty_appointment_status',
        ] + [f'CNS_{year}' for year in years])
        for record in rows:
            known = count_available(record, 'cns')
            cby = record.get('cns_by_year', {})
            total = record['cns_total'] if known else None
            gaps = (';'.join(year for year in years if cby[year] == 0) or 'none') if known else 'unknown'
            writer.writerow([
                record['name'], record['group'], record['institution'], record.get('field', ''),
                record.get('award_names', ''), total, round(total / len(years), 2) if known else None,
                sum(cby[year] > 0 for year in years) if known else None, gaps,
                record.get('fieldtier_total') if count_available(record, 'fieldtier') else None,
                record.get('elife_total') if count_available(record, 'elife') else None,
                record.get('noncns_total') if count_available(record, 'noncns') else None,
                record.get('lab_start_year'), record.get('first_senior_paper_yr'),
                record.get('career_stage', ''), record.get('count_source', ''),
                'last-author proxy', career_year, record.get('lab_age_source', ''),
                record.get('count_fetched_at'), record.get('count_method_version'),
                record.get('researcher_id', ''), record.get('publication_model', 'legacy-aggregates'),
                record.get('identity_status', 'unreviewed'), record.get('current_institution'),
                record.get('institution_status', 'unreviewed roster label'),
                record.get('hhmi_status'), record.get('hhmi_source_status', 'unknown'),
                '; '.join(record.get('topics', [])), '; '.join(record.get('methods', [])),
                '; '.join(record.get('organisms', [])), record.get('active_years_in_window'),
                record.get('cns_per_active_year'), record.get('unresolved_papers', 0),
                '; '.join(sorted({row['URL'] for row in profile_evidence(record.get('profile', {})) if row['URL']})),
                ' | '.join(issue['Issue'] for issue in record_issues(record, years)),
                record.get('faculty_appointment_year'), record.get('faculty_appointment_status', 'unknown'),
            ] + [cby[year] if known else None for year in years])
    return len(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT / 'neuro_stats.json')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'exports')
    parser.add_argument('--start-year', type=int, help='Export a subset of the published window.')
    parser.add_argument('--end-year', type=int)
    args = parser.parse_args(argv)
    with args.input.open(encoding='utf-8') as handle:
        data = json.load(handle)
    validate_snapshot(data)
    data = project_snapshot(data, args.start_year, args.end_year)
    years = [str(year) for year in data['years']]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for filename, predicate, sort_key in (
        ('hhmi_neuro_corresponding_tally.csv', lambda r: r['group'] == 'HHMI', lambda r: r.get('cns_total') or 0),
        ('non_hhmi_neuro_CNS_corresponding.csv',
         lambda r: r['group'] in ('non-HHMI', 'rising-star', 'non-HHMI (low-CNS)'), lambda r: r.get('cns_total') or 0),
        ('all_researchers.csv', lambda r: True, lambda r: r.get('cns_total') or 0),
        ('early_career_awardees.csv', lambda r: r.get('n_awards', 0) > 0, lambda r: r.get('lab_start_year') or 0),
    ):
        count = write(args.output_dir / filename, data['records'], years, predicate, sort_key,
                      data.get('career_reference_year', max(data['years'])))
        print(f"{filename}: {count}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
