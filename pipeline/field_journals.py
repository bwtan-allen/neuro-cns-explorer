"""Count last-author (corresponding proxy) papers in field-tier journals:
   Neuron + Nature Neuroscience  ->  'field_tier'
   eLife                         ->  'elife'
for every researcher in neuro_stats.json (2016-2025).  Resumable -> data/field_journals.json
"""
import urllib.request, urllib.parse, json, time, unicodedata, re, os

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
CP = {'tool': 'hhmi-neuro-audit', 'email': 'research@mit.edu'}
import os as _os
if _os.environ.get('NCBI_API_KEY'): CP['api_key'] = _os.environ['NCBI_API_KEY']
STOP = {'university', 'the', 'of', 'college', 'school', 'medicine', 'medical', 'institute',
        'for', 'center', 'research', 'sciences', 'science', 'health', 'and', 'at', 'hospital'}
INST_KW = {
    'stanford': 'Stanford', 'berkeley': 'Berkeley', 'ucsf': 'UCSF', 'san francisco': 'San Francisco',
    'rockefeller': 'Rockefeller', 'columbia': 'Columbia', 'harvard med': 'Harvard', 'harvard': 'Harvard',
    'mit': 'Massachusetts Institute of Technology', 'massachusetts institute': 'Massachusetts Institute of Technology',
    'southwestern': 'Southwestern', 'duke': 'Duke', 'caltech': 'California Institute of Technology',
    'california institute': 'California Institute of Technology', 'ucla': 'UCLA', 'los angeles': 'Los Angeles',
    'ucsd': 'San Diego', 'san diego': 'San Diego', 'scripps': 'Scripps', 'salk': 'Salk',
    'nyu': 'New York University', 'new york university': 'New York University', 'southern california': 'Southern California',
    'washington': 'University of Washington', 'princeton': 'Princeton', 'yale': 'Yale', 'janelia': 'Janelia',
    'mount sinai': 'Mount Sinai', 'hopkins': 'Johns Hopkins', 'washu': 'Washington University',
    'washington university': 'Washington University', 'pennsylvania': 'Pennsylvania', 'penn': 'Pennsylvania',
    'cold spring harbor': 'Cold Spring Harbor', 'baylor': 'Baylor', 'weill cornell': 'Weill Cornell',
    'cornell': 'Cornell', 'allen institute': 'Allen Institute', 'max planck florida': 'Max Planck Florida',
    'northwestern': 'Northwestern', 'boston university': 'Boston University', 'florida': 'Florida',
    'vanderbilt': 'Vanderbilt', 'colorado': 'Colorado', 'michigan': 'Michigan', 'chicago': 'Chicago',
    'pittsburgh': 'Pittsburgh', 'brown': 'Brown', 'emory': 'Emory', 'santa barbara': 'Santa Barbara',
    'davis': 'Davis', 'irvine': 'Irvine', 'rutgers': 'Rutgers', 'brandeis': 'Brandeis', 'rochester': 'Rochester',
    'nih': 'National Institutes of Health', 'flatiron': 'Flatiron', 'dana-farber': 'Dana-Farber',
    'monell': 'Monell', 'whitehead': 'Whitehead', 'broad': 'Broad', 'gladstone': 'Gladstone',
    'einstein': 'Einstein', 'georgia': 'Georgia', 'utmb': 'Texas', 'indiana': 'Indiana',
    'maryland': 'Maryland', 'van andel': 'Van Andel', 'marine biological': 'Marine Biological',
    'alabama': 'Alabama', 'minnesota': 'Minnesota', 'utah': 'Utah', 'north carolina': 'North Carolina',
    'sloan kettering': 'Sloan Kettering', 'oregon': 'Oregon',
}
JOURN = '("Neuron"[ta] OR "Nat Neurosci"[ta] OR "Elife"[ta])'


def strip(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', s or '') if not unicodedata.combining(c)).lower()


def inst_keyword(inst):
    low = strip(inst.split(';')[0])
    for k, v in INST_KW.items():
        if k in low:
            return v
    toks = [t for t in re.sub(r'[^a-z ]', ' ', low).split() if t not in STOP and len(t) > 3]
    return toks[0].capitalize() if toks else inst.split(',')[0]


def ln_ini(rec):
    pn = rec.get('pubmed_name')
    if pn:                                   # "Rajasethupathy P"
        p = pn.rsplit(' ', 1)
        if len(p) == 2:
            return p[0], p[1][0].upper()
    nm = re.sub(r'\(.*?\)|,.*$', '', rec['name']).strip()
    parts = nm.split()
    if len(parts) >= 2:
        return parts[-1], parts[0][0].upper()
    return None, None


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


def counts(ln, ini, kw):
    s = strip(ln); fi = ini.upper()
    term = f'{ln} {fi}[au] AND "{kw}"[ad] AND {JOURN} AND ("2016"[dp]:"2025"[dp])'
    j = call("esearch.fcgi", {'db': 'pubmed', 'term': term, 'retmode': 'json', 'retmax': '300'}, 'es')
    if j is None:
        return None
    ids = j['esearchresult']['idlist']
    res = {}
    for i in range(0, len(ids), 200):
        jj = call("esummary.fcgi", {'db': 'pubmed', 'id': ','.join(ids[i:i + 200]), 'retmode': 'json'}, 'su')
        if jj is None:
            return None
        res.update(jj['result']); time.sleep(0.34)
    field, elife = {}, {}
    for pid in ids:
        it = res.get(pid)
        if not it:
            continue
        src = (it.get('source', '') or '').strip().lower()
        au = [a['name'] for a in it.get('authors', [])]
        if not au:
            continue
        p = au[-1].rsplit(' ', 1)
        if not (len(p) == 2 and strip(p[0]) == s and p[1][:1].upper() == fi):
            continue
        m = re.match(r'(\d{4})', it.get('sortpubdate') or it.get('pubdate') or '')
        if not m:
            continue
        yr = int(m.group(1))
        if not (2016 <= yr <= 2025):
            continue
        ttl = (it.get('title') or '').lower()
        if any(k in ttl for k in ['erratum', 'correction', 'retraction']):
            continue
        if src == 'elife':
            elife[yr] = elife.get(yr, 0) + 1
        elif src in ('neuron', 'nat neurosci'):
            field[yr] = field.get(yr, 0) + 1
    return {'field_tier': field, 'elife': elife}


if __name__ == '__main__':
    data = json.load(open('../neuro_stats.json'))['records']
    out = json.load(open('field_journals.json')) if os.path.exists('field_journals.json') else {}
    for rec in data:
        name = rec['name']
        if name in out:
            continue
        ln, ini = ln_ini(rec)
        if not ln:
            out[name] = {'field_tier': {}, 'elife': {}}; continue
        kw = inst_keyword(rec['institution'])
        r = counts(ln, ini, kw)
        if r is None:
            print("FAIL", name, flush=True); continue
        out[name] = r
        json.dump(out, open('field_journals.json', 'w'))
        print(f"{name:<24} {kw:<14} Neuron+NatNeuro={sum(r['field_tier'].values())} eLife={sum(r['elife'].values())}", flush=True)
    print("FIELD_JOURNALS_DONE", len(out))
