"""Best-effort real lab-start (faculty appointment) year via ORCID.

For each candidate we need a full given name; PubMed only gives initials, so we
first pull the last author's ForeName from one of their papers, then query ORCID
employments and take the earliest start-year at the matching institution.

Output: data/labstart.json  -> {pubmed_name: {full_name, orcid, appt_year}}  (resumable)
Falls back to null when ORCID has no usable record (caller then uses the
first-senior-author-paper year as a labelled lower-bound proxy).
"""
import urllib.request, urllib.parse, json, time, unicodedata, re, os, sys

EUT = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
CP = {'tool': 'hhmi-neuro-audit', 'email': 'research@mit.edu'}
import os as _os
if _os.environ.get('NCBI_API_KEY'): CP['api_key'] = _os.environ['NCBI_API_KEY']
def strip(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', s or '') if not unicodedata.combining(c)).lower()


def eget(ep, p):
    p = dict(p); p.update(CP)
    for _ in range(6):
        try:
            with urllib.request.urlopen(EUT + ep + "?" + urllib.parse.urlencode(p), timeout=40) as r:
                return r.read().decode()
        except Exception:
            time.sleep(2)
    return None


def full_first_name(ln, ini, kw):
    """Get the last author's full ForeName from one of their affiliation-bounded papers."""
    term = f'{ln} {ini}[au] AND "{kw}"[ad] AND ("2016"[dp]:"2025"[dp])'
    d = eget("esearch.fcgi", {'db': 'pubmed', 'term': term, 'retmode': 'json', 'retmax': '20'})
    if not d:
        return None
    try:
        ids = json.loads(d)['esearchresult']['idlist']
    except Exception:
        return None
    if not ids:
        return None
    xml = eget("efetch.fcgi", {'db': 'pubmed', 'id': ','.join(ids), 'retmode': 'xml'})
    if not xml:
        return None
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml)
    except Exception:
        return None
    for art in root.findall('.//PubmedArticle'):
        authors = art.findall('.//Article/AuthorList/Author')
        if not authors:
            continue
        last = authors[-1]
        lname = last.findtext('LastName') or ''
        fore = last.findtext('ForeName') or ''
        if strip(lname) == strip(ln) and fore:
            given = fore.split()[0]
            if len(given) > 1:
                return given
    return None


def oget(url):
    req = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'research'})
    for _ in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except Exception:
            time.sleep(2)
    return None


def orcid_appt(given, family, inst):
    toks = [t for t in strip(inst).replace('university', '').split() if len(t) > 3]
    instk = toks[0] if toks else strip(inst)[:5]
    d = oget("https://pub.orcid.org/v3.0/expanded-search/?q="
             + urllib.parse.quote(f'given-names:{given} AND family-name:{family}') + "&rows=20")
    if not d:
        return None, None
    for r in (d.get('expanded-result') or []):
        oid = r.get('orcid-id')
        emp = oget(f"https://pub.orcid.org/v3.0/{oid}/employments")
        time.sleep(0.15)
        if not emp:
            continue
        yrs = []
        for grp in emp.get('affiliation-group', []):
            for s in grp.get('summaries', []):
                e = s.get('employment-summary', {})
                org = strip(e.get('organization', {}).get('name'))
                yr = ((e.get('start-date') or {}).get('year') or {}).get('value')
                if instk in org and yr:
                    yrs.append(int(yr))
        if yrs:
            return oid, min(yrs)
    return None, None


KW = {'Stanford': 'Stanford', 'UC Berkeley': 'Berkeley', 'UCSF': 'UCSF', 'Rockefeller': 'Rockefeller',
      'Columbia': 'Columbia', 'Harvard Medical School': 'Harvard', 'MIT': 'Massachusetts Institute of Technology',
      'UT Southwestern': 'Southwestern', 'Duke': 'Duke', 'Caltech': 'California Institute of Technology',
      'UCLA': 'UCLA', 'UCSD': 'San Diego', 'Scripps': 'Scripps', 'Salk': 'Salk', 'NYU': 'New York University',
      'USC': 'Southern California', 'University of Washington': 'University of Washington', 'Princeton': 'Princeton',
      'Yale': 'Yale', 'Janelia': 'Janelia', 'Mount Sinai': 'Mount Sinai', 'Johns Hopkins': 'Johns Hopkins',
      'Harvard (FAS)': 'Harvard', 'WashU St. Louis': 'Washington University', 'Penn': 'Pennsylvania',
      'CSHL': 'Cold Spring Harbor', 'Baylor': 'Baylor', 'Weill Cornell': 'Weill Cornell',
      'Allen Institute': 'Allen Institute', 'MPFI': 'Max Planck Florida'}


if __name__ == '__main__':
    rising = json.load(open('rising_base.json'))
    out = json.load(open('labstart.json')) if os.path.exists('labstart.json') else {}
    for c in rising:
        if c['name'] in out:
            continue
        inst0 = c['insts'][0]
        kw = KW.get(inst0, inst0.split()[0])
        given = full_first_name(c['ln'], c['ini'], kw)
        time.sleep(0.3)
        appt = orcid = None
        if given:
            orcid, appt = orcid_appt(given, c['ln'], inst0)
        out[c['name']] = {'full_name': f"{given} {c['ln']}" if given else c['name'],
                          'given': given, 'orcid': orcid, 'appt_year': appt, 'institution': inst0}
        json.dump(out, open('labstart.json', 'w'))
        print(f"{c['name']:<16} given={given} ORCID_appt={appt}", flush=True)
    print("LABSTART_DONE", len(out))
