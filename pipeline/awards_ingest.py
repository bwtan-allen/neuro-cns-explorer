"""Ingest award recipients (Searle/Pew/McKnight/Klingenstein) and enrich with PubMed stats.
Input : data/awards.json  -> list of {name, institution, award, year}
Output: data/awards_enrich.json -> {display_name: {ln,ini,institution,awards:[{award,year}],
         first_pi_year, cns_by_year, noncns_by_year}}  (resumable)
"""
import urllib.request, urllib.parse, json, time, unicodedata, re, os
from collections import defaultdict

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
CP = {'tool': 'hhmi-neuro-audit', 'email': 'research@mit.edu'}
import os as _os
if _os.environ.get('NCBI_API_KEY'): CP['api_key'] = _os.environ['NCBI_API_KEY']
FLAG = {'cell', 'nature', 'science'}
STOP = {'university', 'the', 'of', 'college', 'school', 'medicine', 'medical', 'institute',
        'for', 'center', 'centre', 'research', 'sciences', 'science', 'health', 'and', 'at'}
# distinctive [ad] keyword per institution (extend as needed)
INST_KW = {
    'stanford': 'Stanford', 'berkeley': 'Berkeley', 'ucsf': 'UCSF', 'rockefeller': 'Rockefeller',
    'columbia': 'Columbia University', 'harvard medical': 'Harvard Medical School', 'mit': 'Massachusetts Institute of Technology',
    'massachusetts institute': 'Massachusetts Institute of Technology', 'southwestern': 'Southwestern',
    'duke': 'Duke University', 'caltech': 'California Institute of Technology',
    'california institute': 'California Institute of Technology', 'ucla': 'UCLA', 'los angeles': 'Los Angeles',
    'ucsd': 'UCSD', 'san diego': 'San Diego', 'scripps': 'Scripps', 'salk': 'Salk',
    'nyu': 'New York University', 'new york university': 'New York University', 'southern california': 'Southern California',
    'washington': 'University of Washington', 'princeton': 'Princeton', 'yale': 'Yale', 'janelia': 'Janelia',
    'mount sinai': 'Mount Sinai', 'hopkins': 'Johns Hopkins', 'washu': 'Washington University',
    'washington university': 'Washington University', 'pennsylvania': 'University of Pennsylvania',
    'cold spring harbor': 'Cold Spring Harbor', 'baylor': 'Baylor', 'weill cornell': 'Weill Cornell',
    'allen institute': 'Allen Institute', 'max planck florida': 'Max Planck Florida',
    'northwestern': 'Northwestern', 'boston university': 'Boston University', 'florida': 'Florida',
    'vanderbilt': 'Vanderbilt', 'colorado': 'Colorado', 'michigan': 'Michigan', 'chicago': 'Chicago',
    'pittsburgh': 'Pittsburgh', 'brown': 'Brown University', 'emory': 'Emory', 'texas': 'Texas',
    'santa barbara': 'Santa Barbara', 'davis': 'California, Davis', 'irvine': 'California, Irvine',
    'cornell': 'Cornell', 'rutgers': 'Rutgers', 'brandeis': 'Brandeis', 'nih': 'National Institutes of Health',
    'flatiron': 'Flatiron', 'dana-farber': 'Dana-Farber', 'monell': 'Monell', 'whitehead': 'Whitehead',
    'new mexico': 'New Mexico', 'minnesota': 'Minnesota', 'wisconsin': 'Wisconsin',
}


def strip(s): return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c)).lower()


def inst_keyword(inst):
    low = strip(inst)
    for k, v in INST_KW.items():
        if k in low:
            return v
    toks = [t for t in re.sub(r'[^a-z ]', ' ', low).split() if t not in STOP and len(t) > 3]
    return toks[0].capitalize() if toks else inst.split(',')[0]


def name_parts(full):
    # "Sergiu P. Pasca" -> ("Pasca","S"); handles middle names/initials
    clean = re.sub(r',.*$', '', full).strip()
    clean = re.sub(r'\b(Ph\.?D\.?|M\.?D\.?|Dr\.?)\b', '', clean, flags=re.I).strip()
    parts = clean.split()
    if len(parts) < 2:
        return None, None
    return parts[-1], parts[0][0].upper()


def call(ep, p, exp):
    p = dict(p); p.update(CP)
    for _ in range(10):
        try:
            with urllib.request.urlopen(BASE + ep + "?" + urllib.parse.urlencode(p), timeout=60) as r:
                j = json.loads(r.read().decode())
            if exp == 'es' and 'esearchresult' in j and 'idlist' in j['esearchresult']:
                return j
            if exp == 'su' and 'result' in j:
                return j
        except Exception:
            pass
        time.sleep(3)
    return None


def esearch_all(term):
    ids = []; rs = 0
    while True:
        j = call("esearch.fcgi", {'db': 'pubmed', 'term': term, 'retmax': '500', 'retstart': str(rs), 'retmode': 'json'}, 'es')
        if j is None:
            return None
        er = j['esearchresult']; b = er.get('idlist', []); ids += b
        c = int(er.get('count', '0')); rs += 500; time.sleep(0.4)
        if rs >= c or not b or rs >= 2000:
            break
    return ids


def esum(ids):
    res = {}
    for i in range(0, len(ids), 200):
        j = call("esummary.fcgi", {'db': 'pubmed', 'id': ','.join(ids[i:i + 200]), 'retmode': 'json'}, 'su')
        if j is None:
            return None
        res.update(j['result']); time.sleep(0.4)
    return res


def enrich(ln, ini, kw):
    s = strip(ln); fi = ini.upper()
    term = f'{ln} {fi}[au] AND "{kw}"[ad] AND ("2005"[dp]:"2025"[dp]) AND Journal Article[pt]'
    probe = call("esearch.fcgi", {'db': 'pubmed', 'term': term, 'retmax': '1', 'retmode': 'json'}, 'es')
    if probe is None:
        return None
    if int(probe['esearchresult'].get('count', '0')) > 800:
        return {'first_pi_year': None, 'cns_by_year': {}, 'noncns_by_year': {}, 'common_name': True}
    ids = esearch_all(term)
    if ids is None:
        return None
    res = esum(ids)
    if res is None:
        return None
    last_years = []; cns = {}; nc = {}
    for pid in ids:
        it = res.get(pid)
        if not it:
            continue
        au = [a['name'] for a in it.get('authors', [])]
        if not au:
            continue
        p = au[-1].rsplit(' ', 1)
        if not (len(p) == 2 and strip(p[0]) == s and p[1][:1].upper() == fi):
            continue
        m = re.match(r'(\d{4})', it.get('sortpubdate') or it.get('pubdate') or '')
        if not m:
            continue
        yr = int(m.group(1)); last_years.append(yr)
        src = (it.get('source', '') or '').strip().lower()
        ttl = (it.get('title') or '').lower()
        if any(k in ttl for k in ['erratum', 'correction', 'retraction']):
            continue
        if 2016 <= yr <= 2025:
            (cns if src in FLAG else nc)[yr] = (cns if src in FLAG else nc).get(yr, 0) + 1
    return {'first_pi_year': (min(last_years) if last_years else None),
            'cns_by_year': cns, 'noncns_by_year': nc}


if __name__ == '__main__':
    awards = json.load(open('awards.json'))
    people = {}
    for a in awards:
        ln, fi = name_parts(a['name'])
        if not ln:
            continue
        key = a['name']
        people.setdefault(key, {'ln': ln, 'ini': fi, 'institution': a['institution'], 'awards': []})
        people[key]['awards'].append({'award': a['award'], 'year': a['year']})
    out = json.load(open('awards_enrich.json')) if os.path.exists('awards_enrich.json') else {}
    failed = []
    for name, p in people.items():
        if name in out:
            continue
        kw = inst_keyword(p['institution'])
        r = enrich(p['ln'], p['ini'], kw)
        if r is None:
            print("FAIL", name, flush=True); failed.append(name); continue
        out[name] = {**p, **r, 'kw': kw}
        json.dump(out, open('awards_enrich.json', 'w'))
        print(f"{name:<26} {kw:<16} first_PI={r.get('first_pi_year')} CNS={sum(r.get('cns_by_year',{}).values())} nonCNS={sum(r.get('noncns_by_year',{}).values())}", flush=True)
    if failed:
        raise SystemExit(f"Awardee enrichment failed for {len(failed)} people; refresh stopped.")
    print("AWARDS_ENRICH_DONE", len(out))
