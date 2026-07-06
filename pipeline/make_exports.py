"""Regenerate exports/*.csv from neuro_stats.json, including explicit CNS gap years."""
import json, csv, os

ROOT = os.path.dirname(os.path.abspath(__file__)).replace('/pipeline', '')
d = json.load(open(os.path.join(ROOT, 'neuro_stats.json')))
recs = d['records']; YEARS = [str(y) for y in d['years']]
os.makedirs(os.path.join(ROOT, 'exports'), exist_ok=True)


def write(path, rows_filter, sort_key):
    rows = sorted([r for r in recs if rows_filter(r)], key=sort_key, reverse=True)
    with open(os.path.join(ROOT, 'exports', path), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['Name', 'Group', 'Institution', 'Field', 'Awards',
                    'CNS_total', 'CNS_avg_per_yr', 'CNS_years_covered', 'CNS_gap_years',
                    'NeuronNatNeuro_total', 'eLife_total', 'nonCNS_total',
                    'Lab_start_year', 'First_senior_paper', 'Career_stage', 'Count_source'] + [f'CNS_{y}' for y in YEARS])
        for r in rows:
            cby = r['cns_by_year']
            gaps = ';'.join(r.get('cns_gap_years', [])) or ('none' if r.get('cns_total') else 'all 10')
            w.writerow([r['name'], r['group'], r['institution'], r.get('field', ''), r.get('award_names', ''),
                        r.get('cns_total', 0), round((r.get('cns_total', 0) or 0) / 10, 2),
                        r.get('cns_years_covered', ''), gaps,
                        r.get('fieldtier_total'), r.get('elife_total'), r.get('noncns_total'),
                        r.get('lab_start_year'), r.get('first_senior_paper_yr'),
                        r.get('career_stage', ''), r.get('count_source', '')]
                       + [cby.get(y, 0) for y in YEARS])
    return len(rows)


n1 = write('hhmi_neuro_corresponding_tally.csv', lambda r: r['group'] == 'HHMI', lambda r: r.get('cns_total', 0))
n2 = write('non_hhmi_neuro_CNS_corresponding.csv',
           lambda r: r['group'] in ('non-HHMI', 'rising-star', 'non-HHMI (low-CNS)'),
           lambda r: r.get('cns_total', 0))
n3 = write('all_researchers.csv', lambda r: True, lambda r: r.get('cns_total', 0))
n4 = write('early_career_awardees.csv', lambda r: r.get('n_awards', 0) > 0,
           lambda r: (r.get('lab_start_year') or 0))
print(f"exports written: hhmi={n1} non_hhmi={n2} all={n3} awardees={n4}")
