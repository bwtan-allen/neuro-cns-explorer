"""Recompute heuristic CNS / Neuron+NatNeuro / eLife last-author counts.

Roster = HHMI inst_map + non-HHMI candidates + rising_base + award recipients + manual supplement.
Output: data/recount.json  {display_name: {cns:{yr:n}, field:{...}, elife:{...},
        first_pi_year, mode, ln, ini, institution, papers, method_version, fetched_at}}

Use --name / --limit and --output for a small review sample before a bulk recount.
Legacy method versions and changed author/affiliation inputs are not reused.
"""
import argparse
import datetime
import json, os, re, unicodedata
from pathlib import Path
import person_cns as P
from inst_keywords import keywords_for
from storage import write_json

D = str(Path(__file__).resolve().parents[1] / 'data')


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
    add(full, c['ln'], c['ini'], ';'.join(c['insts']))
# award recipients
for a in load('awards.json', []):
    ln, ini = ln_ini_from_full(a['name'])
    add(a['name'], ln, ini, a['institution'])
# manual supplement (people missed by scrape / institution moves)
for name, ln, ini, inst in load('roster_supplement.json', []):
    add(name, ln, ini, inst)

def given_name_for(name):
    if ln_ini_from_pubmed(name) != (None, None):
        return None
    first = name.split()[0].strip('.')
    if len(first) <= 1 or (first.isupper() and len(first) <= 3):
        return None
    return first


def cache_current(cached, name, person, max_age_days=30):
    ln, ini, inst = person
    mode = 'name' if name in FORCE_NAME_MODE or not P.is_common(ln) else 'affil'
    try:
        fetched = datetime.datetime.fromisoformat(cached.get('fetched_at', ''))
    except (TypeError, ValueError):
        return False
    if fetched.tzinfo is None:
        return False
    age = datetime.datetime.now(datetime.timezone.utc) - fetched
    return (cached.get('method_version') == P.METHOD_VERSION
            and {'cns', 'field', 'elife', 'papers', 'query'} <= cached.keys()
            and cached.get('expected_given_name') == given_name_for(name)
            and datetime.timedelta(0) <= age < datetime.timedelta(days=max_age_days)
            and (cached.get('ln'), cached.get('ini'), cached.get('institution')) == person
            and cached.get('inst_keywords') == keywords_for(inst)
            and cached.get('mode') == mode)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', action='append', help='Exact roster name; repeat to select several.')
    parser.add_argument('--limit', type=int, help='Maximum number of people to query.')
    parser.add_argument('--output', type=Path, default=Path(D) / 'recount.json',
                        help='Use a separate file for review samples.')
    parser.add_argument('--force', action='store_true', help='Recompute even current cached results.')
    parser.add_argument('--max-age-days', type=int, default=30, help='Cache lifetime in days (default: 30).')
    parser.add_argument('--dry-run', action='store_true', help='List selected names without querying or writing.')
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error('--limit must be at least 1')
    if args.max_age_days < 0:
        parser.error('--max-age-days cannot be negative')
    selected = list(roster)
    if args.name:
        missing = set(args.name) - roster.keys()
        if missing:
            parser.error(f"Unknown roster names: {', '.join(sorted(missing))}")
        selected = list(dict.fromkeys(args.name))
    if args.output.exists():
        with args.output.open(encoding='utf-8') as handle:
            out = json.load(handle)
    else:
        out = {}
    todo = [name for name in selected if args.force
            or not cache_current(out.get(name, {}), name, roster[name], args.max_age_days)]
    if args.limit is not None:
        todo = todo[:args.limit]
    print(f"roster={len(roster)} selected={len(selected)} to_query={len(todo)} "
          f"method_version={P.METHOD_VERSION}", flush=True)
    if args.dry_run:
        print('\n'.join(todo))
        return 0
    for name in todo:
        ln, ini, inst = roster[name]
        kw = keywords_for(inst)
        force = False if name in FORCE_NAME_MODE else None
        r = P.counts(ln, ini, kw, common=force, expected_given_name=given_name_for(name))
        if r is None:
            raise RuntimeError(f"Recount failed for {name}; previous results were not overwritten.")
        out[name] = {**r, 'ln': ln, 'ini': ini, 'institution': inst}
        write_json(args.output, out)
        print(f"{name:<26} [{r['mode']}] CNS={sum(r['cns'].values())} "
              f"NeuronNN={sum(r['field'].values())} eLife={sum(r['elife'].values())}", flush=True)
    print("RECOUNT_DONE", len(out))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
