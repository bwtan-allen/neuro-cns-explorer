import urllib.request,urllib.parse,json,time,unicodedata,re
BASE="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
CP={'tool':'hhmi-neuro-audit','email':'research@mit.edu'}
import os as _os
if _os.environ.get('NCBI_API_KEY'): CP['api_key'] = _os.environ['NCBI_API_KEY']
def strip(s): return ''.join(c for c in unicodedata.normalize('NFKD',s) if not unicodedata.combining(c)).lower()
def call(ep,params,expect):
    p=dict(params); p.update(CP)
    for _ in range(10):
        try:
            with urllib.request.urlopen(BASE+ep+"?"+urllib.parse.urlencode(p),timeout=60) as r: t=r.read().decode('utf-8','replace')
            j=json.loads(t)
            if expect=='es' and 'esearchresult' in j and 'ERROR' not in j['esearchresult']: return j
            if expect=='su' and 'result' in j: return j
        except Exception: pass
        time.sleep(3)
    return None
def esearch_all(term):
    ids=[];rs=0
    while True:
        j=call("esearch.fcgi",{'db':'pubmed','term':term,'retmax':'500','retstart':str(rs),'retmode':'json'},'es')
        if not j: return None
        er=j['esearchresult'];b=er.get('idlist',[]);ids+=b
        c=int(er.get('count','0'));rs+=500;time.sleep(0.4)
        if rs>=c or not b or rs>=4000: break
    return ids
def esum(ids):
    res={}
    for i in range(0,len(ids),200):
        j=call("esummary.fcgi",{'db':'pubmed','id':','.join(ids[i:i+200]),'retmode':'json'},'su')
        if j is None: return None
        res.update(j['result']);time.sleep(0.4)
    return res
KW={'Stanford':'Stanford','UC Berkeley':'Berkeley','UCSF':'UCSF','Rockefeller':'Rockefeller',
'Columbia':'Columbia University','Harvard Medical School':'Harvard','MIT':'Massachusetts Institute of Technology',
'UT Southwestern':'Southwestern','Duke':'Duke University','Caltech':'California Institute of Technology',
'UCLA':'UCLA','UCSD':'San Diego','Scripps':'Scripps','Salk':'Salk','NYU':'New York University',
'USC':'Southern California','University of Washington':'University of Washington','Princeton':'Princeton',
'Yale':'Yale','Janelia':'Janelia','Mount Sinai':'Mount Sinai',
'Johns Hopkins':'Johns Hopkins','Harvard (FAS)':'Harvard','WashU St. Louis':'Washington University',
'Penn':'University of Pennsylvania','CSHL':'Cold Spring Harbor','Baylor':'Baylor',
'Weill Cornell':'Weill Cornell','Allen Institute':'Allen Institute'}
FLAG={'cell','nature','science'}
def noncns(ln,ini,insts):
    fi=ini[0].upper(); s=strip(ln)
    ad=' OR '.join(f'"{KW[i]}"[ad]' for i in insts if i in KW)
    term=f'{ln} {fi}[au] AND ({ad}) AND ("2016"[dp]:"2025"[dp]) AND Journal Article[pt]'
    ids=esearch_all(term)
    if ids is None: return None
    res=esum(ids)
    if res is None: return None
    yrs={}
    for pid in ids:
        it=res.get(pid)
        if not it: continue
        src=(it.get('source','') or '').strip().lower()
        if not src or src in FLAG: continue
        m=re.match(r'(\d{4})',it.get('sortpubdate') or it.get('pubdate') or '')
        if not m: continue
        yr=int(m.group(1))
        if not(2016<=yr<=2025): continue
        ttl=(it.get('title') or '').lower()
        if any(k in ttl for k in ['erratum','author correction','correction:','retraction','publisher correction']): continue
        au=[a['name'] for a in it.get('authors',[])]
        if not au: continue
        p=au[-1].rsplit(' ',1)
        if len(p)==2 and strip(p[0])==s and p[1][:1].upper()==fi:
            yrs[yr]=yrs.get(yr,0)+1
    return yrs
cands=json.load(open('candidates2.json'))
import os
out=json.load(open('cand_noncns.json')) if os.path.exists('cand_noncns.json') else {}
for c in cands:
    key=c['name']
    if key in out: continue
    y=noncns(c['ln'],c['ini'],c['insts'])
    if y is None:
        print("FAIL",key,flush=True); continue
    out[key]={str(k):v for k,v in y.items()}
    json.dump(out,open('cand_noncns.json','w'))
    print(f"{key:<18} nonCNS={sum(y.values())} ({len(y)}/10)",flush=True)
print("DONE",len(out))
