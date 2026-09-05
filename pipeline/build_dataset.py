"""Assemble neuro_stats.json from cached pipeline outputs.
Usage: python build_dataset.py <data_dir> <output_json>

Groups: HHMI | non-HHMI (established, CNS>=5) | rising-star / low-CNS (CNS 2-4) |
        early-career awardee (Searle/Pew/McKnight/Klingenstein, may have <2 CNS).

Career dates are proxies, not verified lab starts. Legacy ORCID data selects
employment years without checking faculty roles. First last-author papers can
precede or follow independence; neither source establishes an exact lab age.
"""
import json, glob, os, sys, unicodedata, datetime
from collections import defaultdict, Counter
from pathlib import Path
from data_quality import audit_dataset, count_available
from storage import write_json

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
    age = max(YEARS) - year
    src = 'ORCID employment~' if is_appt else 'first-paper~'
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
                    'cns_by_year': {str(y): cby.get(y, 0) for y in YEARS}, 'cns_total': sum(cby.get(y, 0) for y in YEARS),
                    'cns_available': ('affil' if use_affil else 'noaffil') in p,
                    'noncns_by_year': {str(y): nby.get(y, 0) for y in YEARS},
                    'noncns_total': (sum(nby.get(y, 0) for y in YEARS) if nr else None),
                    'noncns_available': nr is not None})

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
    nc_raw = cand_nc.get(c['name'])
    ncd = {int(a): b for a, b in (nc_raw or {}).items()}
    full, inst, field, conf = ident.get(c['name'], (c['name'], ';'.join(c['insts']), 'neuroscience', 'core'))
    records.append({'name': full, 'pubmed_name': c['name'], 'group': 'non-HHMI', 'institution': inst, 'field': field,
                    'neuro_confidence': conf, 'career_stage': 'established',
                    'first_senior_paper_yr': None, 'lab_start_year': None, 'lab_age': None, 'lab_age_source': '',
                    'awards': awards_for(full),
                    'cns_by_year': {str(y): cby.get(y, 0) for y in YEARS}, 'cns_total': c['cns'],
                    'noncns_by_year': {str(y): ncd.get(y, 0) for y in YEARS},
                    'noncns_total': sum(ncd.get(y, 0) for y in YEARS) if nc_raw is not None else None,
                    'noncns_available': nc_raw is not None})

enrich = load('enrich.json', {})
seen_keys = set()
for c in load('rising_base.json', []):
    k = (c['ln'], c['ini']); cby = {y: cby_c[k].get(y, 0) for y in YEARS}
    e = enrich.get(c['name'])
    nc_available = e is not None and 'noncns' in e and not e.get('common_name', False)
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
                    'noncns_total': (sum(ncd.get(y, 0) for y in YEARS) if nc_available else None),
                    'noncns_available': nc_available})

existing_keys = {key(r['name']) for r in records}
for k, meta in award_meta.items():
    if k in seen_keys or k in existing_keys:
        continue
    ae = awards_enrich.get(meta['full_name'], {})
    ae_available = 'cns_by_year' in ae and not ae.get('common_name', False)
    nc_available = 'noncns_by_year' in ae and not ae.get('common_name', False)
    cby = {int(a): b for a, b in ae.get('cns_by_year', {}).items()}
    ncd = {int(a): b for a, b in ae.get('noncns_by_year', {}).items()}
    fpaper = ae.get('first_pi_year')
    cs, age, src = stage_from(fpaper, False)
    records.append({'name': meta['full_name'], 'group': 'early-career awardee',
                    'institution': meta['institution'], 'field': 'neuroscience (awardee)',
                    'neuro_confidence': 'core', 'career_stage': cs,
                    'first_senior_paper_yr': fpaper, 'lab_start_year': None, 'lab_age': age, 'lab_age_source': src,
                    'awards': award_map[k],
                    'cns_by_year': {str(y): cby.get(y, 0) for y in YEARS},
                    'cns_total': sum(cby.get(y, 0) for y in YEARS), 'cns_available': ae_available,
                    'noncns_by_year': {str(y): ncd.get(y, 0) for y in YEARS},
                    'noncns_total': (sum(ncd.get(y, 0) for y in YEARS) if nc_available else None),
                    'noncns_available': nc_available})

for r in records:
    r['award_names'] = ', '.join(sorted({a['award'] for a in r.get('awards', [])}))
    r['n_awards'] = len(r.get('awards', []))

# ---------- add manual roster supplement (missed by HHMI scrape / institution moves) ----------
sup = load('roster_supplement.json', [])
sup_meta = {  # name -> (group, field, institution)
    'Cornelia Bargmann': ('HHMI', 'Neuroscience (HHMI)', 'Rockefeller University'),
    'Karel Svoboda': ('non-HHMI', 'systems neuroscience / imaging', 'Allen Institute'),
    'David Julius': ('non-HHMI', 'somatosensation / ion channels', 'UCSF'),
}
existing_keys = {key(r['name']) for r in records}
for name, ln, ini, inst in sup:
    if key(name) in existing_keys:
        continue
    grp, field, institution = sup_meta.get(name, ('non-HHMI', 'neuroscience', inst))
    records.append({'name': name, 'group': grp, 'institution': institution, 'field': field,
                    'neuro_confidence': 'core', 'career_stage': 'established',
                    'first_senior_paper_yr': None, 'lab_start_year': None, 'lab_age': None, 'lab_age_source': '',
                    'awards': awards_for(name), 'award_names': '', 'n_awards': 0,
                    'cns_by_year': {str(y): 0 for y in YEARS}, 'cns_total': None, 'cns_available': False,
                    'noncns_by_year': {str(y): 0 for y in YEARS}, 'noncns_total': None, 'noncns_available': False})
    records[-1]['award_names'] = ', '.join(sorted({a['award'] for a in records[-1]['awards']}))
    records[-1]['n_awards'] = len(records[-1]['awards'])
    existing_keys.add(key(name))

# ---------- per-person recount override (CNS / Neuron+NatNeuro / eLife) ----------
recount = load('recount.json', {})
recount_by_key = defaultdict(list)
for nm, v in recount.items():
    keys = {key(nm), (v.get('ln', '').lower(), (v.get('ini', '') or ' ')[0].lower())}
    for cache_key in keys:
        recount_by_key[cache_key].append(v)

fj = load('field_journals.json', {})
for r in records:
    rc = recount.get(r['name'])
    if rc is None:
        matches = recount_by_key.get(key(r['name']), [])
        if len(matches) == 1:
            rc = matches[0]
        elif len(matches) > 1:
            r['identity_warning'] = 'Ambiguous surname/initial recount matches; no automatic override applied.'
    if rc:
        cby = {int(k): v for k, v in rc['cns'].items()}
        ft = {int(k): v for k, v in rc['field'].items()}
        el = {int(k): v for k, v in rc['elife'].items()}
        r['cns_by_year'] = {str(y): cby.get(y, 0) for y in YEARS}
        r['cns_total'] = sum(cby.get(y, 0) for y in YEARS)
        r['cns_available'] = True
        r['fieldtier_by_year'] = {str(y): ft.get(y, 0) for y in YEARS}
        r['fieldtier_total'] = sum(ft.get(y, 0) for y in YEARS)
        r['elife_by_year'] = {str(y): el.get(y, 0) for y in YEARS}
        r['elife_total'] = sum(el.get(y, 0) for y in YEARS)
        r['fieldjournals_available'] = True
        r['count_source'] = 'person_cns(' + rc.get('mode', '?') + ')'
        r['count_method_version'] = rc.get('method_version')
        r['count_fetched_at'] = rc.get('fetched_at')
        r['count_query'] = rc.get('query')
        r['count_match_keywords'] = rc.get('inst_keywords', [])
        r['publications'] = rc.get('papers', [])
    else:
        # fall back to prior field_journals data if recount not yet available for this person
        e = fj.get(r['name'])
        ft = {int(k): v for k, v in (e['field_tier'] if e else {}).items()}
        el = {int(k): v for k, v in (e['elife'] if e else {}).items()}
        r['fieldtier_by_year'] = {str(y): ft.get(y, 0) for y in YEARS}
        r['fieldtier_total'] = (sum(ft.get(y, 0) for y in YEARS) if e else None)
        r['elife_by_year'] = {str(y): el.get(y, 0) for y in YEARS}
        r['elife_total'] = (sum(el.get(y, 0) for y in YEARS) if e else None)
        r['fieldjournals_available'] = bool(e)
        r['count_source'] = 'discovery/awardee-enrich'

# ---------- unavailable is distinct from an observed zero ----------
for r in records:
    for prefix in ('cns', 'noncns', 'fieldtier', 'elife'):
        if not count_available(r, prefix):
            r[f'{prefix}_total'] = None
            r[f'{prefix}_by_year'] = {str(y): None for y in YEARS}
    cby = r['cns_by_year']
    r['cns_gap_years'] = [str(y) for y in YEARS if cby.get(str(y)) == 0] if count_available(r, 'cns') else None
    r['cns_years_covered'] = len(YEARS) - len(r['cns_gap_years']) if count_available(r, 'cns') else None

# ---------- reclassify discovery-derived groups by per-person recount CNS totals ----------
# (a person's group must reflect the corrected counts, e.g. Julius 3->12 => established non-HHMI)
DISCOVERY_GROUPS = {'non-HHMI', 'rising-star', 'non-HHMI (low-CNS)', 'candidate (career TBD)'}
for r in records:
    if r['group'] not in DISCOVERY_GROUPS or not count_available(r, 'cns'):
        continue
    cns = r.get('cns_total', 0)
    age = r.get('lab_age')
    recent = age is not None and age <= 10
    if cns >= 5:
        r['group'] = 'non-HHMI'
    elif cns >= 2:
        r['group'] = 'rising-star' if recent else 'non-HHMI (low-CNS)'
    else:
        r['group'] = 'rising-star' if recent else 'candidate (career TBD)'

# ---------- drop clear non-neuroscientists that slipped through discovery ----------
# (never drop award winners or manually-added supplement people)
_ex = load('nonneuro_exclude.json', {}).get('exclude', [])
_supp_keys = {key(n) for n, *_ in load('roster_supplement.json', [])}
def _exkey(name):
    return f"{key(name)[0]} {key(name)[1]}"
records = [r for r in records
          if _exkey(r['name']) not in _ex or r.get('n_awards', 0) > 0 or key(r['name']) in _supp_keys]

if not records:
    raise ValueError("No researcher records were assembled; refusing to replace the published snapshot.")
snapshot = {
    'years': YEARS, 'records': records, 'generated': datetime.date.today().isoformat(),
    'generated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
    'schema_version': 2, 'authorship_measure': 'last-author proxy',
    'career_reference_year': max(YEARS),
}
registry_path = Path(D) / 'researchers.json'
if registry_path.exists():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from pipeline.evidence import EvidenceStore
    from pipeline.profiles import load_registry, migrate
    from pipeline.snapshot import build_snapshot
    registry = migrate(snapshot, load_registry(registry_path))
    database = Path(D) / 'publications.sqlite3'
    if database.exists():
        with EvidenceStore(database, readonly=True) as store:
            snapshot = build_snapshot(snapshot, registry, store)
    else:
        snapshot = build_snapshot(snapshot, registry)
    write_json(registry_path, registry)
issues = audit_dataset(snapshot)
if any(issue['Code'].endswith('_total_mismatch')
       or issue['Code'] in {'paper_evidence_mismatch', 'duplicate_pmid'} for issue in issues):
    raise ValueError("Counts, annual totals, or paper evidence disagree; refusing to publish the dataset.")
write_json(OUT, snapshot)
records = snapshot["records"]
print("records:", len(records), dict(Counter(r['group'] for r in records)),
      "| with awards:", sum(1 for r in records if r['n_awards']),
      "| recounted:", sum(1 for r in records if r.get('count_source', '').startswith(('person_cns', 'unified_pubmed'))),
      "| review flags:", len(issues))
