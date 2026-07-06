"""Authoritatively (re)compute CNS / Neuron+NatNeuro / eLife last-author counts for the
whole roster using person_cns (fixes both collision over-counts and neuro-filter under-counts).

Roster = HHMI inst_map + non-HHMI candidates + rising_base + award recipients + manual supplement.
Output: data/recount.json  {display_name: {cns:{yr:n}, field:{...}, elife:{...},
        first_pi_year, mode, ln, ini, institution}}   (resumable)
"""
import json, os, re, time, unicodedata
import person_cns as P
from inst_keywords import keywords_for

D = os.path.dirname(os.path.abspath(__file__)).replace('pipeline', 'data')


def norm(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))


def load(fn, default):
    p = os.path.join(D, fn)
    return json.load(open(p)) if os.path.exists(p) else default


def ln_ini_from_pubmed(pn):
    p = pn.rsplit(' ', 1)
    if len(p) == 2 and p[1].isalpha() and p[1].isupper():
        return p[0], p[1][0]
    return None, None


def ln_ini_from_full(name):
    nm = re.sub(r'\(.*?\)|,.*$|\b(Ph\.?D\.?|M\.?D\.?|Dr\.?|Jr\.?)\b', '', name).strip()
    parts = nm.split()
    if len(parts) >= 2:
        return parts[-1], parts[0][0]
    return None, None


# Verified distinctive-prolific researchers with common surnames -> force name-mode
# (their papers use variant affiliations that affiliation-mode would under-count).
FORCE_NAME_MODE = {'Christopher A. Walsh', 'Edward Chang', 'Jeffrey M. Friedman', 'Zachary A. Knight'}


# ---- assemble roster: name -> (ln, ini, institution) ----
roster = {}


def add(name, ln, ini, inst):
    if not ln or not ini:
        return
    roster.setdefault(name, (ln, ini, inst))


# HHMI
for name, inst in load('inst_map.json', {}).items():
    ln, ini = ln_ini_from_full(name)
    add(name, ln, ini, inst)
# non-HHMI established
ident = load('ident.json', {})
for c in load('candidates2.json', []):
    full = ident.get(c['name'], (c['name'],))[0]
    inst = ident.get(c['name'], (None, ';'.join(c['insts'])))[1] if c['name'] in ident else ';'.join(c['insts'])
    add(full, c['ln'], c['ini'], inst)
# rising / low-CNS
labstart = load('labstart.json', {})
for c in load('rising_base.json', []):
    ls = labstart.get(c['name'], {})
    given = ls.get('given')
    full = f"{given} {c['name'].rsplit(' ', 1)[0]}" if given else c['name']
    add(full, c['ln'], c['ini'], c['insts'][0])
# award recipients
for a in load('awards.json', []):
    ln, ini = ln_ini_from_full(a['name'])
    add(a['name'], ln, ini, a['institution'])
# manual supplement (people missed by scrape / institution moves)
for name, ln, ini, inst in load('roster_supplement.json', []):
    add(name, ln, ini, inst)

if __name__ == '__main__':
    out = load('recount.json', {})
    todo = [k for k in roster if k not in out]
    print(f"roster={len(roster)}  already done={len(out)}  todo={len(todo)}", flush=True)
    for name in todo:
        ln, ini, inst = roster[name]
        kw = keywords_for(inst)
        force = False if name in FORCE_NAME_MODE else None
        try:
            r = P.counts(ln, ini, kw, common=force)
        except Exception as e:
            r = None
        if r is None:
            print("FAIL", name, flush=True)
            continue
        out[name] = {'cns': {str(k): v for k, v in r['cns'].items()},
                     'field': {str(k): v for k, v in r['field'].items()},
                     'elife': {str(k): v for k, v in r['elife'].items()},
                     'first_pi_year': r['first_pi_year'], 'mode': r['mode'],
                     'ln': ln, 'ini': ini, 'institution': inst}
        json.dump(out, open(os.path.join(D, 'recount.json'), 'w'))
        print(f"{name:<26} [{r['mode']}] CNS={sum(r['cns'].values())} "
              f"NeuronNN={sum(r['field'].values())} eLife={sum(r['elife'].values())}", flush=True)
    print("RECOUNT_DONE", len(out))
