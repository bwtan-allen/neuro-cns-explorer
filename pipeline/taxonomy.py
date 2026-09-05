"""Versioned paper-topic and species-mention tags, never lab model-organism claims."""
import re

from .profiles import normalize


TAG_METHOD_VERSION = 2
RULES = {
    "topics": {
        "Learning and memory": ("learning", "memory", "hippocamp", "plasticity"),
        "Neural circuits and behavior": ("neural circuit", "neuronal circuit", "behavior", "behaviour", "connectom"),
        "Sensory systems": ("visual", "vision", "auditory", "olfact", "somatosens", "sensory", "retina"),
        "Development": ("neurogenesis", "neural development", "brain development", "axon guidance", "neuronal differentiation"),
        "Glia and neuroimmunology": ("glia", "astrocyt", "microglia", "neuroimmun", "oligodendro"),
        "Neurodegeneration and aging": ("alzheimer", "parkinson", "neurodegenerat", "brain aging", "dementia"),
        "Cellular and molecular neuroscience": ("synap", "ion channel", "neurotransmi", "chromatin", "transcriptom"),
        "Sleep and circadian rhythms": ("sleep", "circadian", "wakefulness"),
        "Motor systems": ("motor control", "motor cortex", "movement", "locomotion", "basal ganglia", "cerebell"),
        "Computation and cognition": ("cognition", "decision making", "neural network", "computational", "neural coding"),
    },
    "methods": {
        "Imaging and microscopy": ("microscopy", "imaging", "fluorescen", "super resolution", "two photon"),
        "Calcium imaging": ("calcium imaging", "gcamp"),
        "Electrophysiology": ("electrophysiolog", "patch clamp", "voltage clamp", "single unit recording"),
        "Optogenetics": ("optogen", "channelrhodopsin"),
        "Connectomics": ("connectom", "electron microscopy", "circuit tracing"),
        "Sequencing and transcriptomics": ("sequencing", "transcriptom", "rna seq", "single cell rna", "merfish"),
        "MRI and neuroimaging": ("magnetic resonance", "fmri", "neuroimaging", "diffusion mri"),
        "Computational modeling": ("computational model", "mathematical model", "neural network", "machine learning"),
        "Organoids and stem-cell models": ("organoid", "stem cell", "induced pluripotent"),
    },
}
SPECIES_TERMS = {
    "Human": ("humans", "human"),
    "Mouse": ("mice", "mouse", "mus musculus", "murine"),
    "Rat": ("rats", "rat", "rattus"),
    "Drosophila": ("drosophila", "fruit fly", "fruit flies"),
    "Zebrafish": ("zebrafish", "danio rerio"),
    "C. elegans": ("caenorhabditis elegans", "c elegans"),
    "Nonhuman primates": ("macaque", "macaques", "monkey", "monkeys", "marmoset", "marmosets",
                         "rhesus", "nonhuman primate", "nonhuman primates", "non human primates"),
}


def classify(title, mesh=(), keywords=()):
    fields = [title, *mesh, *keywords]
    text = normalize(" ".join(fields))
    tags = {}
    evidence = {}
    for category, labels in RULES.items():
        tags[category] = []
        for label, terms in labels.items():
            matches = [term for term in terms
                       if re.search(r"\b" + re.escape(term) + (r"\b" if len(term) <= 3 else r"\w*\b"), text)]
            if matches:
                tags[category].append(label)
                evidence[f"{category}:{label}"] = matches
    species = {}
    notes = []
    for origin, values in (("title", [title]), ("MeSH", mesh), ("keyword", keywords)):
        for value in values:
            normalized = normalize(value)
            for label, terms in SPECIES_TERMS.items():
                if label == "Human" and origin == "MeSH":
                    if normalized == "humans":
                        notes.append("PubMed MeSH 'Humans' is indexing context, not evidence of human participants or a lab model.")
                    continue
                matches = [term for term in terms if re.search(
                    (r"(?<!non )" if label == "Human" else "") + r"\b" + re.escape(term) + r"\b", normalized
                )]
                if matches:
                    species.setdefault(label, []).append({"source": origin, "text": value, "matched_terms": matches})
    tags["species_mentions"] = sorted(species)
    for label, matches in species.items():
        evidence[f"species_mentions:{label}"] = sorted({term for match in matches for term in match["matched_terms"]})
    return {
        **tags, "species_evidence": species, "species_notes": list(dict.fromkeys(notes)),
        "tag_evidence": evidence, "tag_method_version": TAG_METHOD_VERSION,
        "tag_source": "title/MeSH/keywords; species mentions are not lab models or proof of study participants",
    }


def retag_paper(paper):
    """Update derived tags from saved evidence without changing attribution or retrieval dates."""
    if paper.get("tag_method_version") == TAG_METHOD_VERSION and "organisms" not in paper:
        return paper
    result = dict(paper)
    result.pop("organisms", None)
    result.update(classify(paper["title"], paper.get("mesh", []), paper.get("keywords", [])))
    return result
