import urllib.request,urllib.parse,json,time,unicodedata,re,sys
BASE="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
COMMON_PARAMS={'tool':'hhmi-neuro-audit','email':'research@mit.edu'}
def strip(s): return ''.join(c for c in unicodedata.normalize('NFKD',s) if not unicodedata.combining(c)).lower()
def call(endpoint,params,need_key):
    p=dict(params); p.update(COMMON_PARAMS)
    url=BASE+endpoint+"?"+urllib.parse.urlencode(p)
    for att in range(12):
        try:
            with urllib.request.urlopen(url,timeout=60) as r: txt=r.read().decode()
            j=json.loads(txt)
            if need_key=='esearch' and 'esearchresult' in j and 'idlist' in j['esearchresult'] and 'ERROR' not in j['esearchresult']:
                return j
            if need_key=='esum' and 'result' in j:
                return j
        except Exception: pass
        time.sleep(2.5)
    return None
def esearch_all(term):
    ids=[]; rs=0
    while True:
        j=call("esearch.fcgi",{'db':'pubmed','term':term,'retmax':'500','retstart':str(rs),'retmode':'json'},'esearch')
        if not j: return None
        er=j['esearchresult']; b=er.get('idlist',[]); ids+=b
        cnt=int(er.get('count','0')); rs+=500; time.sleep(1.2)
        if rs>=cnt or not b: break
    return ids
def esum(ids):
    res={}
    for i in range(0,len(ids),150):
        j=call("esummary.fcgi",{'db':'pubmed','id':','.join(ids[i:i+150]),'retmode':'json'},'esum')
        if not j: return None
        res.update(j['result']); time.sleep(1.2)
    return res
def run(sn,ini,affil):
    fi=ini[0].upper(); s=strip(sn)
    term=f'{sn} {fi}[au] AND "{affil}"[ad] AND ("2016"[dp]:"2025"[dp]) AND Journal Article[pt]'
    ids=esearch_all(term)
    if ids is None: return None
    res=esum(ids)
    if res is None: return None
    yrs={}
    for pid in ids:
        it=res.get(pid)
        if not it: continue
        src=(it.get('source','') or '').strip().lower()
        if not src or src in {'cell','nature','science'}: continue
        m=re.match(r'(\d{4})',it.get('sortpubdate') or it.get('pubdate') or '')
        if not m: continue
        yr=int(m.group(1))
        if not (2016<=yr<=2025): continue
        ttl=(it.get('title') or '').lower()
        if any(k in ttl for k in ['erratum','author correction','correction:','retraction','publisher correction']): continue
        au=[a['name'] for a in it.get('authors',[])]
        if not au: continue
        p=au[-1].rsplit(' ',1)
        if len(p)==2 and strip(p[0])==s and p[1][:1].upper()==fi:
            yrs[yr]=yrs.get(yr,0)+1
    return yrs
sn,ini,affil=sys.argv[1],sys.argv[2],sys.argv[3]
y=run(sn,ini,affil)
if y is None: print(sn,"FAILED (throttled)")
else:
    import json as J
    print(f"RESULT|{sn}|{sum(y.values())}|{len(y)}|"+J.dumps({str(k):v for k,v in sorted(y.items())}))
