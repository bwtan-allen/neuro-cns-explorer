import urllib.request,urllib.parse,json,time,unicodedata,os
M="tan.research@example.com"
ISSN="0092-8674|0028-0836|0036-8075"
def strip(s): return ''.join(c for c in unicodedata.normalize('NFKD',s) if not unicodedata.combining(c)).lower()
def get(url):
    delay=3
    for _ in range(9):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'research-tally/1.0 (mailto:%s)'%M})
            with urllib.request.urlopen(req,timeout=60) as r: return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code==429:
                ra=e.headers.get('Retry-After')
                w=int(ra) if (ra and ra.isdigit()) else delay
                time.sleep(min(w,90)); delay=min(delay*2,90)
            else: time.sleep(delay); delay=min(delay*2,60)
        except Exception: time.sleep(delay); delay=min(delay*2,60)
    return {}
def resolve(name,inst):
    d=get("https://api.openalex.org/authors?search="+urllib.parse.quote(name)+"&per_page=10&mailto="+M)
    res=d.get('results',[])
    if not res: return None,None
    key=strip(inst).replace('the ','').split(',')[0]
    def im(a):
        alln=' '.join(strip(i['display_name']) for i in (a.get('last_known_institutions') or []))+' '+' '.join(strip(af['institution']['display_name']) for af in a.get('affiliations',[]))
        return key and key in alln
    for a in res:
        if im(a): return a['id'].split('/')[-1],a['display_name']
    return res[0]['id'].split('/')[-1],res[0]['display_name']
def grpyear(filt):
    d=get(f"https://api.openalex.org/works?filter={filt}&group_by=publication_year&per_page=200&mailto={M}")
    out={}
    for g in d.get('group_by',[]):
        try: out[int(g['key'])]=g['count']
        except: pass
    return out
def counts(aid):
    base=f"corresponding_author_ids:{aid},from_publication_date:2016-01-01,to_publication_date:2025-12-31,type:article"
    total=grpyear(base); time.sleep(1.2)
    cns=grpyear(base+f",primary_location.source.issn:{ISSN}"); time.sleep(1.2)
    return total,cns

inst_map=json.load(open('inst_map.json'))
cache=json.load(open('tally_cache.json')) if os.path.exists('tally_cache.json') else {}
for name,inst in inst_map.items():
    if name in cache and cache[name].get('ok'): continue
    aid,oaname=resolve(name,inst); time.sleep(1.2)
    if not aid:
        cache[name]={'ok':False}; continue
    total,cns=counts(aid)
    cache[name]={'ok':True,'aid':aid,'oa':oaname,
                 'total':{str(k):v for k,v in total.items()},
                 'cns':{str(k):v for k,v in cns.items()}}
    json.dump(cache,open('tally_cache.json','w'))
    print("done",name,"total",sum(total.values()),"cns",sum(cns.values()),flush=True)
print("ALL DONE",len([1 for v in cache.values() if v.get('ok')]))

# ---- finalize CSV merge ----
import csv as _csv
base=json.load(open('csv_base.json'))
YR=list(range(2016,2026))
def gaps(dct):
    yrsp=set(int(k) for k,v in dct.items() if v>0)
    return sorted(set(YR)-yrsp)
out="/Users/bwtan/Desktop/Interview2026/hhmi_neuro_corresponding_tally.csv"
order=sorted(base.items(),key=lambda kv:(-kv[1]['cns_tot'],-kv[1]['cns_yrs']))
with open(out,'w',newline='') as f:
    w=_csv.writer(f)
    w.writerow(["Investigator","Institution","City",
        "CNS_corr_total_2016_2025","CNS_years_covered","CNS_avg_per_yr","CNS_gap_years",
        "nonCNS_corr_total_2016_2025","nonCNS_years_covered","nonCNS_avg_per_yr","nonCNS_gap_years",
        "ALLjournals_corr_total"])
    for name,d in order:
        cg=';'.join(str(y) for y in d['cns_gaps']) if d['cns_gaps'] else 'none'
        c=cache.get(name,{})
        if c.get('ok'):
            tot={int(k):v for k,v in c['total'].items()}
            cns={int(k):v for k,v in c['cns'].items()}
            non={y:tot.get(y,0)-cns.get(y,0) for y in YR}
            ntot=sum(non.values()); nyr=len([y for y in YR if non[y]>0])
            ng=gaps(non); ngs=';'.join(str(y) for y in ng) if ng else 'none'
            w.writerow([name,d['inst'],d['city'],d['cns_tot'],f"{d['cns_yrs']}/10",d['cns_avg'],cg,
                        ntot,f"{nyr}/10",round(ntot/10,1),ngs,sum(tot.values())])
        else:
            w.writerow([name,d['inst'],d['city'],d['cns_tot'],f"{d['cns_yrs']}/10",d['cns_avg'],cg,
                        "NA","NA","NA","NA","NA"])
print("CSV finalized:",out)
