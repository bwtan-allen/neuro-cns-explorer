"""Assemble neuro_stats.json from cached pipeline outputs.
Usage: python build_dataset.py <data_dir> <output_json>

Groups: HHMI | non-HHMI (established, CNS>=5) | rising-star / low-CNS (CNS 2-4) |
        early-career awardee (Searle/Pew/McKnight/Klingenstein, may have <2 CNS).

Lab-start handling (honest):
  - first_senior_paper_yr : first year as last/corresponding author (LOWER BOUND; lags real lab start ~2-3 yr)
  - lab_start_year        : real faculty-appointment year from ORCID when available (preferred)
  - lab_age / career_stage: computed from lab_start_year if present, else the paper proxy (flagged '~')
"""
import json, glob, os, sys, unicodedata, datetime
from collections import defaultdict, Counter

D = sys.argv[1] if len(sys.argv) > 1 else "."
OUT = sys.argv[2] if len(sys.argv) > 2 else "neuro_stats.json"
YEARS = list(range(2016, 2026))


def norm(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))


def key(name):
    n = norm(name).strip().replace('.', ' ')
    parts = n.split()
    if len(parts) < 2:
        return (n.lower(), '')
    if parts[-1].isupper() and len(parts[-1]) <= 3:      # "Rajasethupathy P"
        return (parts[0].lower(), parts[-1][0].lower())
    return (parts[-1].lower(), parts[0][0].lower())      # "Priya Rajasethupathy"


def load(name, default):
    p = os.path.join(D, name)
    return json.load(open(p)) if os.path.exists(p) else default


awards_raw = load('awards.json', [])
award_map = defaultdict(list); award_meta = {}
for a in awards_raw:
    k = key(a['name'])
    award_map[k].append({'award': a['award'], 'year': a['year']})
    award_meta.setdefault(k, {'full_name': a['name'], 'institution': a.get('institution', '')})
awards_enrich = load('awards_enrich.json', {})
labstart = load('labstart.json', {})


def awards_for(name):
    return award_map.get(key(name), [])


def stage_from(year, is_appt):
    if year is None:
        return 'unknown', None, ''
    age = 2025 - year
    src = 'ORCID appt' if is_appt else 'first-paper~'
    if age <= 6:
        return 'rising (<=6y)', age, src
    if age <= 10:
        return 'early (<=10y)', age, src
    return 'established', age, src


records = []

inst_map = load('inst_map.json', {})
pm = {norm(k): v for k, v in load('pm_tally2.json', {}).items()}
noncns_h = {norm(k): v for k, v in load('noncns.json', {}).items()}
CNS_COMMON = {'Lee','Ye','Gu','Shen','Dong','Wilson','Frank','Moore','Stevens','Tsao','Rosbash',
              'Bautista','Gradinaru','Jazayeri','Chapman','Card'}
CNS_MOVERS = {'Kay Tye', 'Scott M. Sternson'}
def sur(n): return n.split()[-1]
for name, inst in inst_map.items():
    nn = norm(name); p = pm.get(nn, {})
    use_affil = not (name in CNS_MOVERS or sur(name) not in CNS_COMMON)
    cby = {int(k): v for k, v in p.get('affil' if use_affil else 'noaffil', {}).items()}
    nr = noncns_h.get(nn)
    nby = {int(k): v for k, v in nr['yrs'].items()} if nr else {}
    records.append({'name': name, 'group': 'HHMI', 'institution': inst, 'field': 'Neuroscience (HHMI)',
                    'neuro_confidence': 'core', 'career_stage': 'established',
                    'first_senior_paper_yr': None, 'lab_start_year': None, 'lab_age': None, 'lab_age_source': '',
                    'awards': awards_for(name),
                    'cns_by_year': {str(y): cby.get(y, 0) for y in YEARS}, 'cns_total': sum(cby.values()),
                    'noncns_by_year': {str(y): nby.get(y, 0) for y in YEARS},
                    'noncns_total': (nr['tot'] if nr else None), 'noncns_available': bool(nr)})

hhmi_ex = set(load('hhmi_exclude.json', []))
cby_c = defaultdict(lambda: defaultdict(int)); seen = defaultdict(set)
for fn in glob.glob(os.path.join(D, 'disc_*.json')):
    for x in json.load(open(fn)):
        if not x['neuro']:
            continue
        if f"{x['ln']} {x['ini'].lower()}" in hhmi_ex:
            continue
        k = (x['ln'], x['ini'])
        if x['pmid'] in seen[k]:
            continue
        seen[k].add(x['pmid']); cby_c[k][x['yr']] += 1

ident = load('ident.json', {})
cand_nc = load('cand_noncns.json', {})
for c in load('candidates2.json', []):
    k = (c['ln'], c['ini']); cby = {y: cby_c[k].get(y, 0) for y in YEARS}
    ncd = {int(a): b for a, b in cand_nc.get(c['name'], {}).items()}
    full, inst, field, conf = ident.get(c['name'], (c['name'], ';'.join(c['insts']), 'neuroscience', 'core'))
    records.append({'name': full, 'pubmed_name': c['name'], 'group': 'non-HHMI', 'institution': inst, 'field': field,
                    'neuro_confidence': conf, 'career_stage': 'established',
                    'first_senior_paper_yr': None, 'lab_start_year': None, 'lab_age': None, 'lab_age_source': '',
                    'awards': awards_for(full),
                    'cns_by_year': {str(y): cby.get(y, 0) for y in YEARS}, 'cns_total': c['cns'],
                    'noncns_by_year': {str(y): ncd.get(y, 0) for y in YEARS}, 'noncns_total': sum(ncd.values()),
                    'noncns_available': True})

enrich = load('enrich.json', {})
seen_keys = set()
for c in load('rising_base.json', []):
    k = (c['ln'], c['ini']); cby = {y: cby_c[k].get(y, 0) for y in YEARS}
    e = enrich.get(c['name'])
    fpaper = e['first_pi_year'] if e else None
    ncd = {int(a): b for a, b in (e['noncns'] if e else {}).items()}
    ls = labstart.get(c['name'], {})
    given = ls.get('given')
    proper_last = c['name'].rsplit(' ', 1)[0]  # e.g. "Huberman AD" -> "Huberman"
    full = f"{given} {proper_last}" if given else c['name']
    appt = ls.get('appt_year')
    lab_start = appt if appt else None
    ref_year = lab_start if lab_start else fpaper
    cs, age, src = stage_from(ref_year, bool(lab_start))
    grp = 'rising-star' if cs.startswith(('rising', 'early')) else ('non-HHMI (low-CNS)' if cs == 'established' else 'candidate (career TBD)')
    seen_keys.add(key(full))
    records.append({'name': full, 'pubmed_name': c['name'], 'group': grp,
                    'institution': ';'.join(c['insts']), 'field': 'neuroscience', 'neuro_confidence': 'core',
                    'career_stage': cs, 'first_senior_paper_yr': fpaper, 'lab_start_year': lab_start,
                    'lab_age': age, 'lab_age_source': src, 'orcid': ls.get('orcid'),
                    'awards': awards_for(full),
                    'cns_by_year': {str(y): cby.get(y, 0) for y in YEARS}, 'cns_total': c['cns'],
                    'noncns_by_year': {str(y): ncd.get(y, 0) for y in YEARS},
                    'noncns_total': (sum(ncd.values()) if e else None), 'noncns_available': bool(e)})

existing_keys = {key(r['name']) for r in records}
for k, meta in award_meta.items():
    if k in seen_keys or k in existing_keys:
        continue
    ae = awards_enrich.get(meta['full_name'], {})
    cby = {int(a): b for a, b in ae.get('cns_by_year', {}).items()}
    ncd = {int(a): b for a, b in ae.get('noncns_by_year', {}).items()}
    fpaper = ae.get('first_pi_year')
    cs, age, src = stage_from(fpaper, False)
    records.append({'name': meta['full_name'], 'group': 'early-career awardee',
                    'institution': meta['institution'], 'field': 'neuroscience (awardee)',
                    'neuro_confidence': 'core', 'career_stage': cs,
                    'first_senior_paper_yr': fpaper, 'lab_start_year': None, 'lab_age': age, 'lab_age_source': src,
                    'awards': award_map[k],
                    'cns_by_year': {str(y): cby.get(y, 0) for y in YEARS}, 'cns_total': sum(cby.values()),
                    'noncns_by_year': {str(y): ncd.get(y, 0) for y in YEARS},
                    'noncns_total': (sum(ncd.values()) if ae else None), 'noncns_available': bool(ae)})

for r in records:
    r['award_names'] = ', '.join(sorted({a['award'] for a in r.get('awards', [])}))
    r['n_awards'] = len(r.get('awards', []))

# ---------- merge field-tier journals (Neuron+Nat Neurosci) and eLife ----------
fj = load('field_journals.json', {})
for r in records:
    e = fj.get(r['name'])
    ft = {int(k): v for k, v in (e['field_tier'] if e else {}).items()}
    el = {int(k): v for k, v in (e['elife'] if e else {}).items()}
    r['fieldtier_by_year'] = {str(y): ft.get(y, 0) for y in YEARS}
    r['fieldtier_total'] = (sum(ft.values()) if e else None)
    r['elife_by_year'] = {str(y): el.get(y, 0) for y in YEARS}
    r['elife_total'] = (sum(el.values()) if e else None)
    r['fieldjournals_available'] = bool(e)

json.dump({'years': YEARS, 'records': records, 'generated': datetime.date.today().isoformat()},
          open(OUT, 'w'), indent=1)
print("records:", len(records), dict(Counter(r['group'] for r in records)),
      "| with awards:", sum(1 for r in records if r['n_awards']))
