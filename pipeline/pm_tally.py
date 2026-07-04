import urllib.request,urllib.parse,json,time,unicodedata,re
BASE="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
def strip(s): return ''.join(c for c in unicodedata.normalize('NFKD',s) if not unicodedata.combining(c)).lower()
def get(u):
    for _ in range(4):
        try:
            with urllib.request.urlopen(u,timeout=30) as r: return r.read().decode()
        except Exception: time.sleep(1.0)
    return ''
def esearch(term):
    q=urllib.parse.urlencode({'db':'pubmed','term':term,'retmax':'250','retmode':'json'})
    d=get(BASE+"esearch.fcgi?"+q)
    try: return json.loads(d)['esearchresult'].get('idlist',[])
    except: return []
def esum(ids):
    if not ids: return {}
    q=urllib.parse.urlencode({'db':'pubmed','id':','.join(ids),'retmode':'json'})
    d=get(BASE+"esummary.fcgi?"+q)
    try: return json.loads(d).get('result',{})
    except: return {}
Y0,Y1=2016,2025
def lastauth_years(surname,initial,affil=''):
    sn=strip(surname); fi=initial[0].upper()
    aff=f' AND "{affil}"[ad]' if affil else ''
    # FIRST-INITIAL-ONLY query = maximal recall; filter precisely below
    term=f'{surname} {fi}[au]{aff} AND (Cell[ta] OR Nature[ta] OR Science[ta]) AND ("{Y0}"[dp]:"{Y1}"[dp])'
    ids=esearch(term); time.sleep(0.34)
    res=esum(ids); time.sleep(0.34)
    last={}
    for pid in ids:
        it=res.get(pid)
        if not it: continue
        if (it.get('source','') or '').strip().lower() not in ('cell','nature','science'): continue
        pd=it.get('sortpubdate') or it.get('pubdate') or ''
        m=re.match(r'(\d{4})',pd)
        if not m: continue
        yr=int(m.group(1))
        if yr<Y0 or yr>Y1: continue
        ttl=(it.get('title') or '').lower()
        if any(k in ttl for k in ['erratum','author correction','correction:','reply','retraction','publisher correction']): continue
        au=[a['name'] for a in it.get('authors',[])]
        if not au: continue
        p=au[-1].rsplit(' ',1)
        if len(p)==2 and strip(p[0])==sn and p[1][:1].upper()==fi:
            last[yr]=last.get(yr,0)+1
    return last
if __name__=='__main__':
    import sys
    print(lastauth_years(sys.argv[1],sys.argv[2],sys.argv[3] if len(sys.argv)>3 else ''))
