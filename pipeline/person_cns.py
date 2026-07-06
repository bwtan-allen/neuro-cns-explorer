"""Authoritative per-person corresponding-author (last-author) publication counts.

Two strategies (chosen by surname):
  * distinctive surname -> search `Surname I[au] AND <journals> AND dates` (NO affiliation);
    count papers where this person is LAST author. High recall, correct for names unlikely to collide.
  * common surname     -> search `Surname I[au] AND (<institution keywords>) AND <journals>`;
    count LAST-author papers whose last-author affiliation contains an institution keyword.
    Collision-safe for East-Asian / very common surnames.

Journal tiers: CNS (Cell/Nature/Science), field (Neuron/Nat Neurosci), eLife.
Returns {cns:{yr:n}, field:{yr:n}, elife:{yr:n}, first_pi_year:int|None, mode:'name'|'affil'}.
"""
import urllib.request, urllib.parse, json, time, unicodedata, re
import xml.etree.ElementTree as ET

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
CP = {'tool': 'hhmi-neuro-audit', 'email': 'research@mit.edu'}
import os as _os
if _os.environ.get('NCBI_API_KEY'):
    CP['api_key'] = _os.environ['NCBI_API_KEY']

CNS = {'cell', 'nature', 'science'}
FIELD = {'neuron', 'nat neurosci', 'nature neuroscience'}
ELIFE = {'elife'}
JOURNAL_FILTER = ('("Cell"[ta] OR "Nature"[ta] OR "Science"[ta] OR "Neuron"[ta] '
                  'OR "Nat Neurosci"[ta] OR "Elife"[ta]) AND "Journal Article"[pt]')

# Non-research publication types to exclude (defeats journalists/news sharing a surname+initial,
# e.g. Ewen Callaway (Nature News) vs Edward Callaway (neuroscientist)).
BAD_PUBTYPES = {'news', 'comment', 'editorial', 'biography', 'interview', 'historical article',
                'portrait', 'newspaper article', 'autobiography', 'address', 'congress',
                'retraction of publication', 'retracted publication', 'published erratum',
                'personal narrative', 'video-audio media', 'news release'}

COMMON_SURNAMES = {
    'wang', 'li', 'zhang', 'liu', 'chen', 'yang', 'huang', 'zhao', 'wu', 'zhou', 'xu', 'sun', 'ma',
    'zhu', 'hu', 'guo', 'lin', 'he', 'gao', 'luo', 'song', 'tang', 'deng', 'han', 'feng', 'cao',
    'peng', 'duan', 'ye', 'ding', 'shen', 'gu', 'dong', 'ren', 'jin', 'fan', 'yan', 'xie', 'yu',
    'lu', 'jiang', 'cheng', 'shi', 'wei', 'ran', 'qiu', 'pan', 'su', 'yao', 'zheng', 'tan', 'meng',
    'yuan', 'qian', 'cai', 'jia', 'xia', 'lei', 'mo', 'niu', 'kuang',
    'kim', 'lee', 'park', 'choi', 'cho', 'jung', 'kang', 'yoon', 'jang', 'shin', 'oh',
    'nguyen', 'tran', 'pham', 'do', 'ng', 'ho', 'wong', 'yeung',
    'smith', 'johnson', 'brown', 'jones', 'miller', 'davis', 'wilson', 'moore', 'taylor',
    'anderson', 'thomas', 'jackson', 'white', 'harris', 'martin', 'thompson', 'young', 'king',
    'wright', 'hill', 'green', 'adams', 'baker', 'nelson', 'carter', 'roberts', 'turner',
    'parker', 'evans', 'edwards', 'collins', 'morris', 'murphy', 'cook', 'rogers', 'bell',
    'cooper', 'cox', 'ward', 'gray', 'james', 'watson', 'brooks', 'kelly', 'price', 'bennett',
    'wood', 'ross', 'long', 'hughes', 'foster', 'russell', 'griffin', 'hayes',
    # additional common Western surnames prone to initial-collision
    'gordon', 'cohen', 'klein', 'freeman', 'stein', 'katz', 'levy', 'meyer', 'schwartz', 'weiss',
    'fisher', 'snyder', 'reed', 'cole', 'hunt', 'palmer', 'mills', 'black', 'warren', 'dixon',
    'ellis', 'gibson', 'hansen', 'grant', 'knight', 'ford', 'hamilton', 'graham', 'sullivan',
    'wallace', 'woods', 'west', 'owens', 'harrison', 'mcdonald', 'stone', 'stewart', 'morgan',
    'murray', 'ford', 'burns', 'gardner', 'stephens', 'fox', 'holmes', 'rice', 'robertson',
    'hunter', 'oliver', 'shaw', 'lynch', 'walsh', 'schmidt', 'day', 'lane', 'chan', 'chang',
    'chung', 'chen', 'chu', 'han', 'hong', 'kwon', 'lim', 'ryu', 'seo', 'son', 'yi', 'goldberg',
    'rosenberg', 'friedman', 'kaplan', 'roth', 'berg', 'stern', 'singh', 'kumar', 'patel', 'shah',
    'khan', 'ali', 'ahmed', 'das', 'gupta', 'reddy', 'rao', 'jain',
}


def strip(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', s or '') if not unicodedata.combining(c)).lower()


def is_common(surname):
    return strip(surname) in COMMON_SURNAMES


def call(ep, p, exp):
    p = dict(p); p.update(CP)
    for _ in range(10):
        try:
            with urllib.request.urlopen(BASE + ep + "?" + urllib.parse.urlencode(p), timeout=60) as r:
                txt = r.read().decode('utf-8', 'replace')
            if exp == 'json':
                j = json.loads(txt)
                if 'esearchresult' in j and 'idlist' in j['esearchresult']:
                    return j
            elif exp == 'json_su':
                j = json.loads(txt)
                if 'result' in j:
                    return j['result']
            elif txt.lstrip().startswith('<'):
                return txt
        except Exception:
            pass
        time.sleep(3)
    return None


def esearch_all(term):
    ids = []; rs = 0
    while True:
        j = call("esearch.fcgi", {'db': 'pubmed', 'term': term, 'retmax': '500',
                                  'retstart': str(rs), 'retmode': 'json'}, 'json')
        if j is None:
            return None
        er = j['esearchresult']; b = er.get('idlist', []); ids += b
        cnt = int(er.get('count', '0')); rs += 500; time.sleep(0.3)
        if rs >= cnt or not b or rs >= 4000:
            break
    return ids


def _tier(src):
    s = src.strip().lower()
    if s in CNS:
        return 'cns'
    if s in FIELD:
        return 'field'
    if s in ELIFE:
        return 'elife'
    return None


def _esum(ids):
    res = {}
    for i in range(0, len(ids), 200):
        j = call("esummary.fcgi", {'db': 'pubmed', 'id': ','.join(ids[i:i + 200]), 'retmode': 'json'}, 'json_su')
        if j is None:
            return None
        res.update(j)
        time.sleep(0.3)
    return res


def counts(lastname, initial, inst_keywords, common=None, want_first_pi=True):
    sn = strip(lastname); fi = initial[0].upper()
    if common is None:
        common = is_common(lastname)
    out = {'cns': {}, 'field': {}, 'elife': {}, 'first_pi_year': None, 'mode': 'affil' if common else 'name'}
    first_years = []; seen = set()
    kwl = [strip(k) for k in inst_keywords]

    if not common:
        # DISTINCTIVE: simple, validated esummary method (matches pm_tally; high recall).
        term = f'{lastname} {fi}[au] AND {JOURNAL_FILTER} AND ("2005"[dp]:"2025"[dp])'
        ids = esearch_all(term)
        if ids is None:
            return None
        res = _esum(ids)
        if res is None:
            return None
        for pid in ids:
            it = res.get(pid)
            if not it or pid in seen:
                continue
            au = [a.get('name', '') for a in it.get('authors', [])]
            if not au:
                continue
            p = au[-1].rsplit(' ', 1)
            if not (len(p) == 2 and strip(p[0]) == sn and p[1][:1].upper() == fi):
                continue
            seen.add(pid)
            m = re.match(r'(\d{4})', it.get('sortpubdate') or it.get('pubdate') or '')
            if not m:
                continue
            yr = int(m.group(1)); first_years.append(yr)
            if yr < 2016 or yr > 2025:
                continue
            ttl = (it.get('title') or '').lower()
            if any(k in ttl for k in ('erratum', 'author correction', 'correction:', 'retraction')):
                continue
            pubtypes = {p.lower() for p in it.get('pubtype', [])}
            if pubtypes & BAD_PUBTYPES:
                continue
            if 'journal article' not in pubtypes:
                continue
            t = _tier(it.get('source', '') or '')
            if t:
                out[t][yr] = out[t].get(yr, 0) + 1
    else:
        # COMMON: efetch + affiliation verification on the last author.
        ad = ' OR '.join(f'"{k}"[ad]' for k in inst_keywords)
        term = f'{lastname} {fi}[au] AND ({ad}) AND {JOURNAL_FILTER} AND ("2005"[dp]:"2025"[dp])'
        ids = esearch_all(term)
        if ids is None:
            return None
        for i in range(0, len(ids), 200):
            xml = call("efetch.fcgi", {'db': 'pubmed', 'id': ','.join(ids[i:i + 200]), 'retmode': 'xml'}, 'xml')
            if xml is None:
                return None
            try:
                root = ET.fromstring(xml)
            except Exception:
                continue
            for art in root.findall('.//PubmedArticle'):
                pmid = art.findtext('.//PMID')
                if pmid in seen:
                    continue
                authors = art.findall('.//Article/AuthorList/Author')
                if not authors:
                    continue
                last = authors[-1]
                ln = last.findtext('LastName'); ini = last.findtext('Initials') or ''
                if not ln or strip(ln) != sn or ini[:1].upper() != fi:
                    continue
                aff = strip(' | '.join((a.text or '') for a in last.findall('AffiliationInfo/Affiliation')))
                if not any(k in aff for k in kwl):
                    continue
                seen.add(pmid)
                y = art.findtext('.//Article/Journal/JournalIssue/PubDate/Year')
                if not y:
                    md = art.findtext('.//Article/Journal/JournalIssue/PubDate/MedlineDate') or ''
                    m = re.match(r'(\d{4})', md); y = m.group(1) if m else None
                if not y:
                    continue
                yr = int(y); first_years.append(yr)
                if yr < 2016 or yr > 2025:
                    continue
                ptypes = [pt.text or '' for pt in art.findall('.//PublicationTypeList/PublicationType')]
                pl = {p.lower() for p in ptypes}
                if pl & BAD_PUBTYPES or 'journal article' not in pl:
                    continue
                t = _tier(art.findtext('.//Article/Journal/Title') or '')
                if t:
                    out[t][yr] = out[t].get(yr, 0) + 1
            time.sleep(0.3)

    if want_first_pi and first_years:
        out['first_pi_year'] = min(first_years)
    return out


if __name__ == '__main__':
    import sys
    from inst_keywords import keywords_for
    ln, ini, inst = sys.argv[1], sys.argv[2], sys.argv[3]
    kw = keywords_for(inst)
    r = counts(ln, ini, kw)
    print(f"mode={r['mode']} keywords={kw}")
    for k in ('cns', 'field', 'elife'):
        print(f"  {k}: total={sum(r[k].values())} {dict(sorted(r[k].items()))}")
    print("  first_pi_year:", r['first_pi_year'])
