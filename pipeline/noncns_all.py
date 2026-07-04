import json,time
from noncns import noncns_lastauth
affil=json.load(open('affil_kw.json'))
# collision-prone surnames for ALL-journal search -> must use affiliation filter
COMMON={'Lee','Ye','Gu','Shen','Dong','Luo','Zhang','Wang','Li','Wilson','Frank','Moore',
        'Stevens','Tsao','Anderson','Friedman','Walsh','Chapman','Knight','Kim','Shapiro','Zhuang'}
def surname(n): return n.split()[-1]
res={}
for line in open('authors.tsv',encoding='utf-8'):
    disp,sn,ini=line.rstrip('\n').split('\t')
    common = surname(disp) in COMMON
    aff = affil.get(disp,'') if common else ''
    y=noncns_lastauth(sn,ini,aff)
    res[disp]={'yrs':{int(k):v for k,v in y.items()},'tot':sum(y.values()),
               'ncov':len(y),'method':'withAffil(common)' if common else 'noAffil(distinctive)'}
    print(f"{disp:<22} nonCNS={sum(y.values()):>3} ({len(y)}/10) [{res[disp]['method']}]",flush=True)
json.dump(res,open('noncns.json','w'))
print("SAVED")
