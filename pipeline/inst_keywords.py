"""Curated institution -> distinctive PubMed [ad] affiliation keyword(s).

Returns a list of quoted phrases suitable for an OR'd [ad] filter that uniquely
identifies the institution WITHOUT collision (e.g. UCSF must NOT match all of
'California', WashU-StLouis must NOT match 'University of Washington' in Seattle).
"""
import re

# order matters: check longer / more specific substrings first
INST_MAP = [
    ("university of california, san francisco", ['University of California, San Francisco', 'UCSF']),
    ("ucsf", ['UCSF', 'University of California, San Francisco']),
    ("university of california, san diego", ['University of California, San Diego', 'La Jolla']),
    ("ucsd", ['University of California, San Diego', 'La Jolla']),
    ("university of california, los angeles", ['University of California, Los Angeles', 'UCLA']),
    ("ucla", ['UCLA', 'University of California, Los Angeles']),
    ("university of california, berkeley", ['University of California, Berkeley']),
    ("berkeley", ['University of California, Berkeley']),
    ("university of california, davis", ['University of California, Davis']),
    ("university of california, irvine", ['University of California, Irvine']),
    ("university of california, santa barbara", ['Santa Barbara']),
    ("santa barbara", ['Santa Barbara']),
    ("university of california, riverside", ['Riverside']),
    ("california institute of technology", ['California Institute of Technology']),
    ("caltech", ['California Institute of Technology']),
    ("washington university in st", ['Washington University in St. Louis', 'Washington University School of Medicine']),
    ("washu", ['Washington University in St. Louis']),
    ("university of washington", ['University of Washington']),
    ("stanford", ['Stanford']),
    ("harvard medical school", ['Harvard Medical School']),
    ("harvard university", ['Harvard University']),
    ("harvard", ['Harvard']),
    ("massachusetts institute of technology", ['Massachusetts Institute of Technology']),
    ("mit", ['Massachusetts Institute of Technology']),
    ("rockefeller", ['Rockefeller']),
    ("columbia", ['Columbia University']),
    ("weill cornell", ['Weill Cornell']),
    ("cornell", ['Cornell University']),
    ("new york university", ['New York University', 'NYU ']),
    ("nyu", ['New York University']),
    ("mount sinai", ['Mount Sinai']),
    ("icahn", ['Icahn School of Medicine', 'Mount Sinai']),
    ("princeton", ['Princeton']),
    ("yale", ['Yale']),
    ("johns hopkins", ['Johns Hopkins']),
    ("ut southwestern", ['Southwestern Medical']),
    ("southwestern medical", ['Southwestern Medical']),
    ("baylor college", ['Baylor College of Medicine']),
    ("duke", ['Duke University']),
    ("scripps", ['Scripps Research']),
    ("salk", ['Salk Institute']),
    ("cold spring harbor", ['Cold Spring Harbor']),
    ("allen institute", ['Allen Institute']),
    ("janelia", ['Janelia']),
    ("max planck florida", ['Max Planck Florida']),
    ("university of pennsylvania", ['University of Pennsylvania', 'Perelman']),
    ("perelman", ['Perelman', 'University of Pennsylvania']),
    ("university of southern california", ['Southern California']),
    ("northwestern", ['Northwestern University']),
    ("boston children", ["Boston Children's Hospital"]),
    ("boston university", ['Boston University']),
    ("brandeis", ['Brandeis']),
    ("university of michigan", ['University of Michigan']),
    ("university of chicago", ['University of Chicago']),
    ("university of pittsburgh", ['University of Pittsburgh']),
    ("brown university", ['Brown University']),
    ("emory", ['Emory']),
    ("vanderbilt", ['Vanderbilt']),
    ("university of colorado", ['University of Colorado']),
    ("university of utah", ['University of Utah']),
    ("university of florida", ['University of Florida']),
    ("university of oregon", ['University of Oregon']),
    ("oregon health", ['Oregon Health']),
    ("university of minnesota", ['University of Minnesota']),
    ("university of wisconsin", ['University of Wisconsin']),
    ("university of north carolina", ['University of North Carolina', 'Chapel Hill']),
    ("chapel hill", ['University of North Carolina', 'Chapel Hill']),
    ("university of maryland", ['University of Maryland']),
    ("university of rochester", ['University of Rochester']),
    ("university of virginia", ['University of Virginia']),
    ("university of texas at austin", ['Texas at Austin']),
    ("rutgers", ['Rutgers']),
    ("dartmouth", ['Dartmouth']),
    ("indiana university", ['Indiana University']),
    ("texas a&m", ['Texas A&M']),
    ("georgia institute", ['Georgia Institute of Technology']),
    ("university of georgia", ['University of Georgia']),
    ("fordham", ['Fordham']),
    ("cedars-sinai", ['Cedars-Sinai']),
    ("van andel", ['Van Andel']),
    ("umass chan", ['UMass Chan', 'Massachusetts Medical']),
    ("umass medical", ['Massachusetts Medical']),
    ("massachusetts general", ['Massachusetts General Hospital']),
    ("whitehead", ['Whitehead Institute']),
    ("broad institute", ['Broad Institute']),
    ("gladstone", ['Gladstone']),
    ("flatiron", ['Flatiron']),
    ("simons foundation", ['Simons Foundation', 'Flatiron']),
    ("monell", ['Monell']),
    ("dana-farber", ['Dana-Farber']),
    ("albert einstein", ['Albert Einstein College']),
    ("einstein", ['Albert Einstein College']),
    ("fred hutchinson", ['Fred Hutchinson']),
    ("sloan kettering", ['Sloan Kettering']),
    ("stowers", ['Stowers Institute']),
    ("marine biological", ['Marine Biological Laboratory']),
    ("national institutes of health", ['National Institutes of Health']),
    ("nih", ['National Institutes of Health']),
    ("university of alabama", ['University of Alabama']),
    ("suny", ['State University of New York', 'SUNY']),
    ("university of kansas", ['University of Kansas']),
    ("university of colorado", ['University of Colorado']),
    ("children's national", ["Children's National"]),
    ("van andel", ['Van Andel']),
]


def keywords_for(institution):
    """Return list of distinctive [ad] phrases for an institution string.
    institution may contain ';' for multiple; handles the first known match per part."""
    out = []
    for part in institution.split(';'):
        low = part.strip().lower()
        matched = None
        for key, kws in INST_MAP:
            if key in low:
                matched = kws
                break
        if matched:
            for k in matched:
                if k not in out:
                    out.append(k)
        else:
            # conservative fallback: strip generic words, quote the remaining distinctive phrase
            cleaned = re.sub(r'\b(university|the|of|college|school|medicine|medical|institute|for|'
                             r'center|centre|research|sciences|science|health|and|at|department)\b',
                             ' ', low)
            toks = [t.capitalize() for t in re.split(r'[^a-z]+', cleaned) if len(t) > 3]
            if toks:
                out.append(' '.join(toks[:2]))
    return out or [institution.split(',')[0].strip()]
