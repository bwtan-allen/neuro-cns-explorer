import urllib.request,urllib.parse,json,time,unicodedata,re
BASE="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
def strip(s): return ''.join(c for c in unicodedata.normalize('NFKD',s) if not unicodedata.combining(c)).lower()
def get(u):
    for _ in range(5):
        try:
            with urllib.request.urlopen(u,timeout=45) as r: return r.read().decode()
        except Exception: time.sleep(1.2)
    return ''
def esearch_all(term):
    ids=[]; retstart=0
    while True:
        q=urllib.parse.urlencode({'db':'pubmed','term':term,'retmax':'500','retstart':str(retstart),'retmode':'json'})
        d=get(BASE+"esearch.fcgi?"+q)
        try: j=json.loads(d)['esearchresult']
        except: break
        batch=j.get('idlist',[]); ids+=batch
        cnt=int(j.get('count','0'))
        retstart+=500
        time.sleep(0.34)
        if retstart>=cnt or not batch or retstart>=2000: break
    return ids
def esum(ids):
    res={}
    for i in range(0,len(ids),200):
        chunk=ids[i:i+200]
        q=urllib.parse.urlencode({'db':'pubmed','id':','.join(chunk),'retmode':'json'})
        d=get(BASE+"esummary.fcgi?"+q)
        try: res.update(json.loads(d).get('result',{}))
        except: pass
        time.sleep(0.34)
    return res
Y0,Y1=2016,2025
FLAG={'cell','nature','science'}
def noncns_lastauth(surname,initial,affil=''):
    sn=strip(surname); fi=initial[0].upper()
    aff=f' AND "{affil}"[ad]' if affil else ''
    term=f'{surname} {fi}[au]{aff} AND ("{Y0}"[dp]:"{Y1}"[dp]) AND Journal Article[pt]'
    ids=esearch_all(term)
    res=esum(ids)
    yrs={}
    for pid in ids:
        it=res.get(pid)
        if not it: continue
        src=(it.get('source','') or '').strip().lower()
        if not src or src in FLAG: continue  # exclude CNS
        pd=it.get('sortpubdate') or it.get('pubdate') or ''
        m=re.match(r'(\d{4})',pd)
        if not m: continue
        yr=int(m.group(1))
        if yr<Y0 or yr>Y1: continue
        ttl=(it.get('title') or '').lower()
        if any(k in ttl for k in ['erratum','author correction','correction:','retraction','publisher correction']): continue
        au=[a['name'] for a in it.get('authors',[])]
        if not au: continue
        p=au[-1].rsplit(' ',1)
        if len(p)==2 and strip(p[0])==sn and p[1][:1].upper()==fi:
            yrs[yr]=yrs.get(yr,0)+1
    return yrs
if __name__=='__main__':
    import sys
    r=noncns_lastauth(sys.argv[1],sys.argv[2],sys.argv[3] if len(sys.argv)>3 else '')
    print(sum(r.values()),dict(sorted(r.items())))
