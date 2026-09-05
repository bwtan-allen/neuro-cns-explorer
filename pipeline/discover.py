import urllib.request,urllib.parse,json,time,unicodedata,re,sys
import xml.etree.ElementTree as ET
BASE="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
CP={'tool':'hhmi-neuro-audit','email':'research@mit.edu'}
import os as _os
if _os.environ.get('NCBI_API_KEY'): CP['api_key'] = _os.environ['NCBI_API_KEY']
def norm(s): return ''.join(c for c in unicodedata.normalize('NFKD',s) if not unicodedata.combining(c)).lower()
def call(endpoint,params,expect):
    p=dict(params); p.update(CP)
    url=BASE+endpoint+"?"+urllib.parse.urlencode(p)
    for _ in range(10):
        try:
            with urllib.request.urlopen(url,timeout=90) as r: txt=r.read().decode('utf-8','replace')
            if expect=='json':
                j=json.loads(txt)
                if 'esearchresult' in j and 'ERROR' not in j['esearchresult']: return j
            else:
                if txt.strip().startswith('<'): return txt
        except Exception: pass
        time.sleep(3)
    return None
def esearch_all(term):
    ids=[]; rs=0
    while True:
        j=call("esearch.fcgi",{'db':'pubmed','term':term,'retmax':'500','retstart':str(rs),'retmode':'json'},'json')
        if not j: return None
        er=j['esearchresult']; b=er.get('idlist',[]); ids+=b
        cnt=int(er.get('count','0')); rs+=500; time.sleep(0.5)
        if rs>=cnt or not b or rs>=6000: break
    return ids

NEURO_TERMS='(brain[tiab] OR neuron*[tiab] OR neural[tiab] OR neuronal[tiab] OR nervous[tiab] OR synap*[tiab] OR cortex[tiab] OR cortical[tiab] OR hippocamp*[tiab] OR neurosci*[tiab] OR axon*[tiab] OR dendrit*[tiab] OR glia*[tiab] OR cerebell*[tiab] OR amygdala[tiab] OR thalam*[tiab] OR olfact*[tiab] OR retina*[tiab] OR "nervous system"[tiab] OR neural circuit[tiab] OR neurotransmit*[tiab])'
STRONG=['neuro','brain','neuron','neural','nerv','synap','cortex','cortical','hippocamp','axon',
 'dendrit','glia','cerebell','amygdala','thalam','retina','olfact','cognit','sensory','motor cortex',
 'visual cortex','memory','circuit','behavi','vision','auditory','somatosens','sleep','pain','spinal']
FLAG={'cell','nature','science','science (new york, n.y.)'}

# institution: (query [ad] fragment, list of match-token predicates)
INST={
 'Stanford':('"Stanford"[ad]', lambda a:'stanford' in a),
 'UC Berkeley':('"Berkeley"[ad]', lambda a:'berkeley' in a and 'california' in a),
 'UCSF':('("UCSF"[ad] OR "University of California, San Francisco"[ad] OR "San Francisco, CA"[ad])',
         lambda a:'ucsf' in a or ('san francisco' in a and 'california' in a)),
 'Rockefeller':('"Rockefeller"[ad]', lambda a:'rockefeller' in a),
 'Columbia':('"Columbia University"[ad]', lambda a:'columbia univ' in a),
 'Harvard Medical School':('"Harvard Medical School"[ad]', lambda a:'harvard medical school' in a),
 'MIT':('"Massachusetts Institute of Technology"[ad]', lambda a:'massachusetts institute of technology' in a),
 'UT Southwestern':('"Southwestern"[ad]', lambda a:'southwestern' in a and 'texas' in a),
 'Duke':('"Duke University"[ad]', lambda a:'duke univ' in a),
 'Caltech':('("California Institute of Technology"[ad] OR "Caltech"[ad])',
            lambda a:'california institute of technology' in a or 'caltech' in a),
 'UCLA':('("UCLA"[ad] OR "University of California, Los Angeles"[ad])',
         lambda a:'ucla' in a or ('los angeles' in a and 'california' in a)),
 'UCSD':('("UCSD"[ad] OR "University of California, San Diego"[ad] OR "La Jolla"[ad])',
         lambda a:'ucsd' in a or ('san diego' in a and 'california' in a)),
 'Scripps':('"Scripps"[ad]', lambda a:'scripps' in a),
 'Salk':('"Salk"[ad]', lambda a:'salk' in a),
 'NYU':('("New York University"[ad] OR "NYU"[ad])', lambda a:'new york university' in a or 'nyu' in a),
 'USC':('("University of Southern California"[ad] OR "USC"[ad])', lambda a:'southern california' in a),
 'University of Washington':('"University of Washington"[ad]', lambda a:'university of washington' in a),
 'Princeton':('"Princeton"[ad]', lambda a:'princeton' in a),
 'Yale':('"Yale"[ad]', lambda a:'yale' in a),
 'Janelia':('"Janelia"[ad]', lambda a:'janelia' in a),
 'Mount Sinai':('("Mount Sinai"[ad] OR "Icahn School"[ad])', lambda a:'mount sinai' in a or 'icahn' in a),
 'Johns Hopkins':('"Johns Hopkins"[ad]', lambda a:'hopkins' in a),
 'Harvard (FAS)':('("Harvard University"[ad] AND "Cambridge"[ad])', lambda a:'harvard' in a and 'cambridge' in a and 'medical school' not in a),
 'WashU St. Louis':('("Washington University"[ad] AND "Louis"[ad])', lambda a:'washington university' in a and 'louis' in a),
 'Penn':('("University of Pennsylvania"[ad] OR "Perelman"[ad])', lambda a:'university of pennsylvania' in a or 'perelman' in a),
 'CSHL':('"Cold Spring Harbor"[ad]', lambda a:'cold spring harbor' in a),
 'Baylor':('"Baylor College of Medicine"[ad]', lambda a:'baylor' in a),
 'Weill Cornell':('"Weill Cornell"[ad]', lambda a:'weill cornell' in a),
 'Allen Institute':('"Allen Institute"[ad]', lambda a:'allen institute' in a),
 'MPFI':('("Max Planck Florida"[ad] OR "Max Planck Institute for Neuroscience"[ad])', lambda a:'max planck florida' in a or ('max planck' in a and 'jupiter' in a)),
}

def parse(xml,inst,pred):
    out=[]
    root=ET.fromstring(xml)
    if root.tag != 'PubmedArticleSet':
        raise ValueError("Unexpected PubMed XML; discovery aborted.")
    for art in root.findall('.//PubmedArticle'):
        jt=(art.findtext('.//Article/Journal/Title') or '').strip().lower()
        if jt not in FLAG: continue
        # year
        y=art.findtext('.//Article/Journal/JournalIssue/PubDate/Year')
        if not y:
            md=art.findtext('.//Article/Journal/JournalIssue/PubDate/MedlineDate') or ''
            m=re.match(r'(\d{4})',md); y=m.group(1) if m else None
        if not y: continue
        yr=int(y)
        if yr<2016 or yr>2025: continue
        ptypes=[pt.text or '' for pt in art.findall('.//PublicationTypeList/PublicationType')]
        if any('Retract' in p or 'Correction' in p or 'Erratum' in p for p in ptypes): continue
        title=(art.findtext('.//Article/ArticleTitle') or '')
        authors=art.findall('.//Article/AuthorList/Author')
        if not authors: continue
        last=authors[-1]
        ln=last.findtext('LastName'); ini=last.findtext('Initials') or ''
        if not ln: continue  # collective author
        affs=[ (a.text or '') for a in last.findall('AffiliationInfo/Affiliation')]
        afftxt=norm(' | '.join(affs))
        if 'howard hughes' in afftxt or 'hhmi' in afftxt: continue  # exclude HHMI
        if not pred(afftxt): continue  # last author must be at this institution
        # neuro?
        mesh=[ (m.text or '') for m in art.findall('.//MeshHeadingList/MeshHeading/DescriptorName')]
        blob=norm(title+' '+' '.join(mesh)+' '+afftxt)
        is_neuro=any(tok in blob for tok in STRONG)
        pmid=art.findtext('.//PMID')
        out.append({'pmid':pmid,'yr':yr,'journal':jt.split(' ')[0],'ln':norm(ln),'ini':ini[:1].upper(),
                    'name':f"{ln} {ini}",'inst':inst,'neuro':is_neuro,'aff':(affs[0] if affs else '')[:120]})
    return out

def run_inst(inst):
    adq,pred=INST[inst]
    term=f'(Cell[ta] OR Nature[ta] OR Science[ta]) AND {adq} AND ("2016"[dp]:"2025"[dp]) AND Journal Article[pt] AND {NEURO_TERMS}'
    ids=esearch_all(term)
    if ids is None: return None
    recs=[]
    for i in range(0,len(ids),200):
        xml=call("efetch.fcgi",{'db':'pubmed','id':','.join(ids[i:i+200]),'retmode':'xml'},'xml')
        if xml is None: return None
        recs+=parse(xml,inst,pred)
        time.sleep(0.5)
    return recs

if __name__=='__main__':
    inst=sys.argv[1]
    import os
    fn=f'disc_{inst.replace(" ","_")}.json'
    if os.path.exists(fn):
        print("exists",fn); sys.exit()
    r=run_inst(inst)
    if r is None:
        print("FAILED",inst); sys.exit(1)
    json.dump(r,open(fn,'w'))
    print(f"{inst}: {len(r)} last-author CNS papers ({sum(x['neuro'] for x in r)} neuro)")
