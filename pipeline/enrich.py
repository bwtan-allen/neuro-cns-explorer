"""Enrich rising-star candidates: career-start proxy (first last-author year) + non-CNS counts.
Resumable: writes enrich.json incrementally. One affiliation-bounded pass per candidate."""
import urllib.request, urllib.parse, json, time, unicodedata, re, os, sys

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
CP = {'tool': 'hhmi-neuro-audit', 'email': 'research@mit.edu'}
import os as _os
if _os.environ.get('NCBI_API_KEY'): CP['api_key'] = _os.environ['NCBI_API_KEY']
FLAG = {'cell', 'nature', 'science'}
KW = {'Stanford':'Stanford','UC Berkeley':'Berkeley','UCSF':'UCSF','Rockefeller':'Rockefeller',
'Columbia':'Columbia University','Harvard Medical School':'Harvard','MIT':'Massachusetts Institute of Technology',
'UT Southwestern':'Southwestern','Duke':'Duke University','Caltech':'California Institute of Technology',
'UCLA':'UCLA','UCSD':'San Diego','Scripps':'Scripps','Salk':'Salk','NYU':'New York University',
'USC':'Southern California','University of Washington':'University of Washington','Princeton':'Princeton',
'Yale':'Yale','Janelia':'Janelia','Mount Sinai':'Mount Sinai','Johns Hopkins':'Johns Hopkins',
'Harvard (FAS)':'Harvard','WashU St. Louis':'Washington University','Penn':'University of Pennsylvania',
'CSHL':'Cold Spring Harbor','Baylor':'Baylor','Weill Cornell':'Weill Cornell','Allen Institute':'Allen Institute',
'MPFI':'Max Planck Florida'}


def strip(s): return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c)).lower()


def call(ep, p, exp):
    p = dict(p); p.update(CP)
    for _ in range(12):
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
        if rs >= c or not b or rs >= 3000:
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


def enrich(ln, ini, insts):
    fi = ini[0].upper(); s = strip(ln)
    ad = ' OR '.join(f'"{KW[i]}"[ad]' for i in insts if i in KW)
    if not ad:
        return None
    term = f'{ln} {fi}[au] AND ({ad}) AND ("2005"[dp]:"2025"[dp]) AND Journal Article[pt]'
    probe = call("esearch.fcgi", {'db':'pubmed','term':term,'retmax':'1','retmode':'json'}, 'es')
    if probe is None:
        return None
    total = int(probe['esearchresult'].get('count','0'))
    if total > 800:
        return {'first_pi_year': None, 'noncns': {}, 'cns_confirm': {}, 'common_name': True}
    ids = esearch_all(term)
    if ids is None:
        return None
    res = esum(ids)
    if res is None:
        return None
    last_years = []          # all years they are last author (any journal)
    noncns = {}              # non-CNS last-author per year (2016-2025)
    cns = {}                 # CNS last-author per year (2016-2025)
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
        yr = int(m.group(1))
        last_years.append(yr)
        src = (it.get('source', '') or '').strip().lower()
        ttl = (it.get('title') or '').lower()
        if any(k in ttl for k in ['erratum', 'author correction', 'correction:', 'retraction']):
            continue
        if 2016 <= yr <= 2025:
            if src in FLAG:
                cns[yr] = cns.get(yr, 0) + 1
            elif src:
                noncns[yr] = noncns.get(yr, 0) + 1
    if not last_years:
        return {'first_pi_year': None, 'noncns': {}, 'cns_confirm': {}}
    return {'first_pi_year': min(last_years), 'noncns': noncns, 'cns_confirm': cns}


if __name__ == '__main__':
    base = json.load(open('rising_base.json'))
    if len(sys.argv) > 1:  # test mode: enrich first N
        base = base[:int(sys.argv[1])]
    out = json.load(open('enrich.json')) if os.path.exists('enrich.json') else {}
    for c in base:
        if c['name'] in out:
            continue
        r = enrich(c['ln'], c['ini'], c['insts'])
        if r is None:
            print("FAIL", c['name'], flush=True); continue
        out[c['name']] = r
        json.dump(out, open('enrich.json', 'w'))
        fy = r['first_pi_year']
        age = (2025 - fy) if fy else None
        print(f"{c['name']:<16} first_PI_yr={fy} lab_age~{age} nonCNS={sum(r['noncns'].values())}", flush=True)
    print("ENRICH_DONE", len(out))
