"""Heuristic per-person last-author counts, with an auditable PMID list.

Both name-only and affiliation-scoped searches use the same PubMed XML parser.
Neither strategy proves identity or corresponding authorship. first_pi_year is
the earliest qualifying last-author paper found in these journals since 2005,
not a verified faculty appointment or the person's first paper in any journal.
"""
import datetime
import os
import sys
import urllib.error
import urllib.request, urllib.parse, json, time, unicodedata, re
import xml.etree.ElementTree as ET

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
METHOD_VERSION = 2
START_YEAR, END_YEAR = 2016, 2025
CP = {'tool': 'neuro-cns-explorer'}
if os.environ.get('NCBI_API_KEY'):
    CP['api_key'] = os.environ['NCBI_API_KEY']
if os.environ.get('NCBI_EMAIL'):
    CP['email'] = os.environ['NCBI_EMAIL']
REQUEST_INTERVAL = 0.11 if 'api_key' in CP else 0.35

CNS = {'cell', 'nature', 'science', 'science (new york, n.y.)'}
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
    'khan', 'ali', 'ahmed', 'das', 'gupta', 'reddy', 'rao', 'jain', 'loh', 'lim', 'goh', 'tan',
    'ong', 'sim', 'yap', 'teo', 'koh', 'toh',
}


def strip(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', s or '') if not unicodedata.combining(c)).lower()


def is_common(surname):
    return strip(surname) in COMMON_SURNAMES


class SearchTooLarge(RuntimeError):
    """The PubMed result window must be split before retrieval."""


def call(ep, p, exp):
    p = dict(p); p.update(CP)
    for attempt in range(6):
        time.sleep(REQUEST_INTERVAL)
        try:
            with urllib.request.urlopen(BASE + ep + "?" + urllib.parse.urlencode(p), timeout=60) as r:
                txt = r.read().decode('utf-8', 'replace')
            if exp == 'json':
                j = json.loads(txt)
                result = j.get('esearchresult', {})
                if 'idlist' in result and 'ERROR' not in result and 'error' not in j:
                    return j
            elif txt.lstrip().startswith('<'):
                return txt
            raise ValueError("Unexpected PubMed response")
        except (OSError, ValueError) as error:
            # Do not print request URLs: they can contain the NCBI API key.
            print(f"PubMed {ep}: attempt {attempt + 1}/6 failed "
                  f"({type(error).__name__})", file=sys.stderr, flush=True)
        if attempt < 5:
            time.sleep(min(2 ** attempt, 30))
    print(f"PubMed {ep}: retries exhausted; no result saved", file=sys.stderr, flush=True)
    return None


def esearch_all(term):
    ids = []; rs = 0
    while True:
        j = call("esearch.fcgi", {'db': 'pubmed', 'term': term, 'retmax': '500',
                                  'retstart': str(rs), 'retmode': 'json'}, 'json')
        if j is None:
            return None
        er = j['esearchresult']; b = er['idlist']
        cnt = int(er['count'])
        if cnt > 9999:
            raise SearchTooLarge("PubMed search exceeds 9,999 results; narrow the query before counting.")
        ids.extend(b)
        if len(ids) >= cnt:
            if len(ids) != cnt or len(set(ids)) != cnt:
                raise RuntimeError("PubMed returned inconsistent search results; recount aborted.")
            return ids
        if not b:
            raise RuntimeError("PubMed returned an incomplete result page; recount aborted.")
        rs += len(b)


def _tier(src):
    s = src.strip().lower()
    if s in CNS:
        return 'cns'
    if s in FIELD:
        return 'field'
    if s in ELIFE:
        return 'elife'
    return None


def parse_articles(xml, expected_ids):
    """Parse the common paper evidence used by legacy and all-journal counters."""
    root = ET.fromstring(xml)
    returned = {art.findtext('.//PMID') for art in root}
    if root.tag != 'PubmedArticleSet' or returned != set(expected_ids):
        raise RuntimeError("PubMed returned incomplete article XML; recount aborted.")
    papers = []
    for art in root.findall('./PubmedArticle'):
        pmid = art.findtext('.//PMID')
        authors = art.findall('.//Article/AuthorList/Author')
        last = authors[-1] if authors else None
        given = last.findtext('ForeName') or '' if last is not None else ''
        family = last.findtext('LastName') or '' if last is not None else ''
        initials = last.findtext('Initials') or '' if last is not None else ''
        affiliations = ([''.join(a.itertext()) for a in last.findall('AffiliationInfo/Affiliation')]
                        if last is not None else [])
        affiliations = [re.sub(r'(?:electronic address:|e-?mail:)?\s*[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',
                               '', value, flags=re.I).strip() for value in affiliations]
        orcids = ([identifier.text or '' for identifier in last.findall('Identifier')
                   if (identifier.get('Source') or '').casefold() == 'orcid'] if last is not None else [])
        electronic = art.findtext('.//Article/ArticleDate[@DateType="Electronic"]/Year')
        printed = art.findtext('.//Article/Journal/JournalIssue/PubDate/Year')
        if not printed:
            medline = art.findtext('.//Article/Journal/JournalIssue/PubDate/MedlineDate') or ''
            match = re.match(r'(\d{4})', medline)
            printed = match.group(1) if match else None
        title_node = art.find('.//Article/ArticleTitle')
        title = ''.join(title_node.itertext()) if title_node is not None else ''
        journal = art.findtext('.//Article/Journal/Title') or ''
        abbreviation = art.findtext('.//Article/Journal/ISOAbbreviation') or ''
        papers.append({
            'pmid': pmid, 'title': title, 'journal': journal, 'journal_abbreviation': abbreviation,
            'tier': _tier(abbreviation) or _tier(journal) or 'other',
            'year': int(electronic or printed) if electronic or printed else None,
            'electronic_year': int(electronic) if electronic else None,
            'print_year': int(printed) if printed else None,
            'doi': art.findtext('.//PubmedData/ArticleIdList/ArticleId[@IdType="doi"]') or '',
            'publication_types': [pt.text or '' for pt in art.findall('.//PublicationTypeList/PublicationType')],
            'retracted': any(node.get('RefType') in {'RetractionIn', 'RetractionOf'}
                             for node in art.findall('.//CommentsCorrections')),
            'last_author': f'{given or initials} {family}'.strip(),
            'last_author_given': given, 'last_author_family': family, 'last_author_initials': initials,
            'last_author_affiliations': affiliations, 'last_author_orcids': orcids,
            'mesh': [node.text or '' for node in art.findall('.//MeshHeading/DescriptorName')],
            'keywords': [''.join(node.itertext()) for node in art.findall('.//KeywordList/Keyword')],
            'url': f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/',
        })
    return papers


def counts(lastname, initial, inst_keywords, common=None, want_first_pi=True, expected_given_name=None):
    if not lastname.strip() or not initial.strip():
        raise ValueError("A surname and initial are required.")
    sn = strip(lastname); fi = initial.strip()[0].upper()
    if common is None:
        common = is_common(lastname)
    keywords = [k.strip() for k in inst_keywords if k.strip()]
    if common and not keywords:
        raise ValueError("Affiliation matching requires at least one institution keyword.")
    out = {'cns': {}, 'field': {}, 'elife': {}, 'first_pi_year': None,
           'mode': 'affil' if common else 'name', 'method_version': METHOD_VERSION,
           'papers': [], 'inst_keywords': keywords, 'expected_given_name': expected_given_name}
    first_years = []; seen = set()
    kwl = [strip(k) for k in keywords]
    ad = ' OR '.join(f'"{k}"[ad]' for k in keywords)
    affiliation = f' AND ({ad})' if common else ''
    term = (f'{lastname} {fi}[au]{affiliation} AND {JOURNAL_FILTER} '
            f'AND ("2005"[dp]:"{END_YEAR}"[dp])')
    out['query'] = term
    ids = esearch_all(term)
    if ids is None:
        return None
    for i in range(0, len(ids), 200):
        batch = ids[i:i + 200]
        xml = call("efetch.fcgi", {'db': 'pubmed', 'id': ','.join(batch), 'retmode': 'xml'}, 'xml')
        if xml is None:
            return None
        for paper in parse_articles(xml, batch):
            pmid = paper['pmid']
            if pmid in seen:
                continue
            ln = paper['last_author_family']; ini = paper['last_author_initials']
            if not ln or strip(ln) != sn or ini[:1].upper() != fi:
                continue
            aff = ' | '.join(paper['last_author_affiliations'])
            if common and not any(k in strip(aff) for k in kwl):
                continue
            seen.add(pmid)
            ptypes = {strip(pt) for pt in paper['publication_types']}
            title = paper['title']
            if ptypes & BAD_PUBTYPES or 'journal article' not in ptypes:
                continue
            if any(k in title.lower() for k in ('erratum', 'author correction', 'correction:', 'retraction')):
                continue
            journal = paper['journal']
            tier = paper['tier']
            if tier == 'other':
                continue
            year = paper['year']
            if year is None:
                raise ValueError(f"Qualifying PubMed article {pmid} has no usable publication year.")
            if 2005 <= year <= END_YEAR:
                first_years.append(year)
            if not START_YEAR <= year <= END_YEAR:
                continue
            given = paper['last_author_given']
            first_given = given.split()[0] if given else ''
            normalized_given = strip(first_given).replace('-', '').replace('.', '')
            expected = strip(expected_given_name).replace('-', '').replace('.', '')
            name_warning = ''
            if expected and len(normalized_given) > 1 and normalized_given != expected:
                name_warning = (f"Expected given name {expected_given_name}; PubMed lists {given}. "
                                "Review for an alias or a different person; not automatically excluded.")
            out[tier][year] = out[tier].get(year, 0) + 1
            out['papers'].append({
                'pmid': pmid, 'year': year, 'tier': tier, 'journal': journal, 'title': title,
                'doi': paper['doi'],
                'last_author': f"{given or ini} {ln}",
                'last_author_affiliation': aff,
                'match': 'last-author surname/initial + affiliation' if common else 'last-author surname/initial only',
                'given_name_warning': name_warning,
                'url': f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/',
            })

    if want_first_pi and first_years:
        out['first_pi_year'] = min(first_years)
    out['papers'].sort(key=lambda paper: (paper['year'], paper['pmid']))
    out['fetched_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
    return out


if __name__ == '__main__':
    import sys
    from inst_keywords import keywords_for
    ln, ini, inst = sys.argv[1], sys.argv[2], sys.argv[3]
    kw = keywords_for(inst)
    r = counts(ln, ini, kw)
    if r is None:
        raise SystemExit("PubMed count failed; no result available.")
    print(f"mode={r['mode']} keywords={kw}")
    for k in ('cns', 'field', 'elife'):
        print(f"  {k}: total={sum(r[k].values())} {dict(sorted(r[k].items()))}")
    print("  first_pi_year:", r['first_pi_year'])
