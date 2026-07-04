import json,time
from pm_tally import lastauth_years
affil=json.load(open('affil_kw.json'))
out={}
for line in open('authors.tsv',encoding='utf-8'):
    disp,sn,ini=line.rstrip('\n').split('\t')
    noaf=lastauth_years(sn,ini,'')
    wiaf=lastauth_years(sn,ini,affil.get(disp,''))
    out[disp]={'noaffil':noaf,'noaffil_tot':sum(noaf.values()),'noaffil_yrs':len(noaf),
               'affil':wiaf,'affil_tot':sum(wiaf.values()),'affil_yrs':len(wiaf)}
    print(f"{disp:<22} noAffil={sum(noaf.values()):>2}({len(noaf)}/10)  withAffil={sum(wiaf.values()):>2}({len(wiaf)}/10)",flush=True)
json.dump(out,open('pm_tally2.json','w'))
print("SAVED")
