"""Conservative discovery tags inferred from titles, MeSH headings and keywords."""
import re

from .profiles import normalize


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
    "organisms": {
        "Human": ("humans", "human", "patient"),
        "Mouse": ("mice", "mouse", "mus musculus", "murine"),
        "Rat": ("rats", "rat", "rattus"),
        "Drosophila": ("drosophila", "fruit fly"),
        "Zebrafish": ("zebrafish", "danio rerio"),
        "C. elegans": ("caenorhabditis elegans", "c elegans"),
        "Nonhuman primates": ("macaque", "monkey", "marmoset", "rhesus"),
    },
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
    return {**tags, "tag_evidence": evidence, "tag_source": "title/MeSH/keywords (rule-inferred)"}
