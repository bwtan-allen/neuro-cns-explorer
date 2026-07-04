"""Build data/awards.json from compiled award recipient lists.
Parses embedded 'YEAR | Name | Institution' blocks (+ Pew/Searle pipe-tables from raw_*.txt).
Re-run whenever a new award block is added."""
import json, re, os, glob

D = os.path.dirname(os.path.abspath(__file__)).replace('pipeline', 'data')

MCKNIGHT = """
2016 | Mark Andermann | Beth Israel Deaconess Medical Center
2016 | John Cunningham | Columbia University
2016 | Roozbeh Kiani | New York University
2016 | Yuki Oka | California Institute of Technology
2016 | Abigail Person | University of Colorado Denver
2016 | Wei Wei | University of Chicago
2017 | Martha Bagnall | Washington University in St. Louis
2017 | Stephen Brohawn | University of California, Berkeley
2017 | Mehrdad Jazayeri | Massachusetts Institute of Technology
2017 | Katherine Nagel | New York University
2017 | Matthew Pecot | Harvard Medical School
2017 | Michael Yartsev | University of California, Berkeley
2018 | Eiman Azim | Salk Institute for Biological Studies
2018 | Rudy Behnia | Columbia University
2018 | Felice Dunn | University of California, San Francisco
2018 | John Tuthill | University of Washington
2018 | Mingshan Xue | Baylor College of Medicine
2018 | Brad Zuchero | Stanford University
2019 | Jayeeta Basu | New York University
2019 | Juan Du | Van Andel Research Institute
2019 | Mark Harnett | Massachusetts Institute of Technology
2019 | Weizhe Hong | University of California, Los Angeles
2019 | Rachel Roberts-Galbraith | University of Georgia
2019 | Shigeki Watanabe | Johns Hopkins University
2020 | Steven Flavell | Massachusetts Institute of Technology
2020 | Nuo Li | Baylor College of Medicine
2020 | Lauren O'Connell | Stanford University
2020 | Zhaozhu Qiu | Johns Hopkins University
2020 | Maria Antonietta Tosches | Columbia University
2020 | Daniel Wacker | Icahn School of Medicine at Mount Sinai
2021 | Lucas Cheadle | Cold Spring Harbor Laboratory
2021 | Josie Clowney | University of Michigan
2021 | Shaul Druckmann | Stanford University
2021 | Laura Lewis | Boston University
2021 | Ashok Litwin-Kumar | Columbia University
2021 | David Schneider | New York University
2021 | Swathi Yadlapalli | University of Michigan
2022 | Christine Constantinople | New York University
2022 | Bradley Dickerson | Princeton University
2022 | Markita Landry | University of California, Berkeley
2022 | Lauren Orefice | Massachusetts General Hospital
2022 | Kanaka Rajan | Icahn School of Medicine at Mount Sinai
2022 | Weiwei Wang | University of Texas Southwestern Medical Center
2023 | Ishmail Abdus-Saboor | Columbia University
2023 | Yasmine El-Shamayleh | Columbia University
2023 | Vikram Gadagkar | Columbia University
2023 | Hidehiko Inagaki | Max Planck Florida Institute for Neuroscience
2023 | Peri Kurshan | Albert Einstein College of Medicine
2023 | Scott Linderman | Stanford University
2023 | Swetha Murthy | Oregon Health & Science University
2023 | Karthik Shekhar | University of California, Berkeley
2024 | Annegret Falkner | Princeton University
2024 | Andrea Gomez | University of California, Berkeley
2024 | Sinisa Hrvatin | Whitehead Institute for Biomedical Research
2024 | Xin Jin | Scripps Research
2024 | Ann Kennedy | Northwestern University
2024 | Sung Soo Kim | University of California, Santa Barbara
2024 | Bianca Jones Marlin | Columbia University
2024 | Nancy Padilla-Coreano | University of Florida
2024 | Mubarak Hussain Syed | University of New Mexico
2024 | Longzhi Tan | Stanford University
2025 | Arkarup Banerjee | Cold Spring Harbor Laboratory
2025 | Josefina del Marmol | Harvard Medical School
2025 | Chantell Evans | Duke University
2025 | Yvette Fisher | University of California, Berkeley
2025 | Christine Grienberger | Brandeis University
2025 | Theanne Griffith | University of California, Davis
2025 | Matthew Lovett-Barron | University of California, San Diego
2025 | Lucas Pinto | Northwestern University
2025 | Sergey Stavisky | University of California, Davis
2025 | Alex Williams | New York University
"""

KLINGENSTEIN = """
2016 | Stephen Brohawn | University of California, Berkeley
2016 | Monica Dus | University of Michigan
2016 | Evan Feinberg | University of California, San Francisco
2016 | Biyu He | New York University
2016 | Andrew Kruse | Harvard Medical School
2016 | Conor Liston | Weill Cornell Medical College
2016 | Evan W. Miller | University of California, Berkeley
2016 | Tiffany Schmidt | Northwestern University
2016 | John Tuthill | University of Washington
2016 | Michael Yartsev | University of California, Berkeley
2016 | Yuki Oka | California Institute of Technology
2017 | Susanne Ahmari | University of Pittsburgh
2017 | Matthew Banghart | University of California, San Diego
2017 | Jayeeta Basu | New York University
2017 | Benjamin de Bivort | Harvard University
2017 | Richard Daneman | University of California, San Diego
2017 | Gul Dolen | Johns Hopkins University
2017 | Jeff Donlea | University of California, Los Angeles
2017 | Harrison W. Gabel | Washington University in St. Louis
2017 | Catherine Hartley | New York University
2017 | Michael Hoppa | Dartmouth College
2017 | Elaine Y. Hsiao | University of California, Los Angeles
2017 | Christine Merlin | Texas A&M University
2017 | Kate Meyer | University of North Carolina at Chapel Hill
2017 | Wei Xu | UT Southwestern Medical Center
2018 | Andres Bendesky | Columbia University
2018 | J. Nicholas Betley | University of Pennsylvania
2018 | Denise Cai | Icahn School of Medicine at Mount Sinai
2018 | Xin Duan | University of California, San Francisco
2018 | Junjie Guo | UT Southwestern Medical Center
2018 | Mark Harnett | Massachusetts Institute of Technology
2018 | Weizhe Hong | University of California, Los Angeles
2018 | Aashish Manglik | University of California, San Francisco
2018 | Joseph Parker | California Institute of Technology
2018 | Priya Rajasethupathy | Rockefeller University
2018 | Celine Riera | Cedars-Sinai Medical Center
2018 | Simon Sponberg | Georgia Institute of Technology
2018 | Hongdian Yang | University of California, Riverside
2019 | Nicholas Bellono | Harvard University
2019 | Juan Du | Van Andel Institute
2019 | Erica Korb | University of Pennsylvania
2019 | Elias Issa | Columbia University
2019 | Hiroyuki Kato | University of North Carolina at Chapel Hill
2019 | Aubrey Kelly | Fordham University
2019 | Mazen Kheirbek | University of California, San Francisco
2019 | Mark Howe | Northwestern University
2019 | Lauren Orefice | Massachusetts General Hospital
2019 | Zhaozhu Qiu | Johns Hopkins University
2019 | Caroline Runyan | University of Pittsburgh
2019 | Francois St-Pierre | Baylor College of Medicine
2019 | Shigeki Watanabe | Johns Hopkins University
2020 | Amber Alhadeff | Monell Chemical Senses Center
2020 | Ghazaleh Ashrafi | Washington University in St. Louis
2020 | Christine Constantinople | New York University
2020 | Laura Duvall | Brandeis University
2020 | Michael Economo | Boston University
2020 | James Jeanne | Yale University
2020 | Liang Liang | Harvard University
2020 | Qili Liu | University of California, San Francisco
2020 | Derek Southwell | University of California, San Francisco
2020 | Summer Thyme | Icahn School of Medicine at Mount Sinai
2020 | Nicholas Steinmetz | University of Washington
2020 | Amanda Whipple | Harvard University
2020 | Moriel Zelikowsky | University of Utah
2021 | Aparna Bhaduri | University of California, Los Angeles
2021 | Frederick Bennett | University of Pennsylvania
2021 | Lucas Cheadle | Cold Spring Harbor Laboratory
2021 | Laura DeNardo | University of California, Los Angeles
2021 | Annegret Falkner | Princeton University
2021 | Hidehiko Inagaki | Max Planck Florida Institute for Neuroscience
2021 | Isha Jain | Gladstone Institutes
2021 | Tomasz Nowakowski | University of California, San Francisco
2021 | Yi-Rong Peng | University of California, Los Angeles
2021 | Hongying Shen | Yale University
2021 | Nikhil Sharma | Columbia University
2021 | Nicolas Tritsch | New York University
2021 | Ross Williamson | University of Pittsburgh
2022 | Marie Bechler | SUNY Upstate Medical University
2022 | Antonio Fernandez-Ruiz | Cornell University
2022 | Yvette Fisher | University of California, Berkeley
2022 | Robert Hill | Dartmouth College
2022 | Xin Jin | Scripps Research
2022 | Justus Kebschull | Johns Hopkins University
2022 | Sung Soo Kim | University of California, Santa Barbara
2022 | Aakanksha Singhvi | Fred Hutchinson Cancer Center
2022 | Hume Stroud | UT Southwestern Medical Center
2022 | Steffen Wolff | University of Maryland School of Medicine
2022 | Meg Younger | Boston University
2022 | Eviatar Yemini | UMass Chan Medical School
2022 | Lejla Zubcevic | University of Kansas Medical Center
2023 | Sarah Ackerman | Washington University in St. Louis
2023 | Arkarup Banerjee | Cold Spring Harbor Laboratory
2023 | Ritchie Chen | University of California, San Francisco
2023 | SueYeon Chung | New York University
2023 | Yasmine El-Shamayleh | Columbia University
2023 | Vikram Gadagkar | Columbia University
2023 | Fenna Krienen | Princeton University
2023 | Ken Loh | Yale University
2023 | Brittany D. Needham | Indiana University
2023 | Lu Sun | UT Southwestern Medical Center
2023 | Emily Sylwestrak | University of Oregon
2023 | Brady Weissbourd | Massachusetts Institute of Technology
2023 | Kevin Yackle | University of California, San Francisco
2024 | Vineet Augustine | University of California, San Diego
2024 | Jeeyun Chung | Harvard University
2024 | Linlin Fan | Massachusetts Institute of Technology
2024 | Jordan Farrell | Boston Children's Hospital
2024 | Anna K. Gillespie | University of Washington
2024 | Eirene Markenscoff-Papadimitriou | Cornell University
2024 | Vijay Mohan K. Namboodiri | University of California, San Francisco
2024 | Anders Nelson | New York University
2024 | Neset Ozel | Stowers Institute for Medical Research
2024 | Jessica Osterhout | University of Utah
2024 | Nancy Padilla-Coreano | University of Florida
2024 | Kartik Pattabiraman | Yale University
2024 | Elizabeth Pollina | Washington University in St. Louis
2024 | Kapil V. Ramachandran | Columbia University
2024 | Herbert Zheng Wu | Icahn School of Medicine at Mount Sinai
2025 | Salil Bidaye | Max Planck Florida Institute for Neuroscience
2025 | Sebastian Choi | UT Southwestern Medical Center
2025 | Carolyn Elya | Harvard University
2025 | Tristan Geiller | Yale University
2025 | Xin Gu | Dana-Farber Cancer Institute
2025 | Laura Gwilliams | Stanford University
2025 | Danique Jeurissen | New York University
2025 | Aaron Kuan | Yale University
2025 | Changyang Linghu | University of Michigan
2025 | Quynh Anh Nguyen | Vanderbilt University
2025 | Justin O'Hare | University of Colorado
2025 | Debosmita Sardar | University of Colorado
2025 | Carl Schoonover | Allen Institute for Brain Science
"""
SEARLE = """
2016 | Yevgenia Kozorovitskiy | Northwestern University
2016 | Michael Yartsev | University of California, Berkeley
2017 | Eiman Azim | Salk Institute for Biological Studies
2017 | Weizhe Hong | University of California, Los Angeles
2017 | John Tuthill | University of Washington
2018 | Andres Bendesky | Columbia University
2018 | Kathryn D. Meyer | Duke University
2018 | Priya Rajasethupathy | The Rockefeller University
2018 | Mark Sheffield | University of Chicago
2019 | Nick Bellono | Harvard University
2019 | Paul Greer | UMass Medical School
2019 | Andrew Miri | Northwestern University
2019 | Caroline Runyan | University of Pittsburgh
2020 | Hidehiko Inagaki | Max Planck Florida Institute for Neuroscience
2020 | Sung Soo Kim | University of California, Santa Barbara
2020 | Laura D. Lewis | Boston University
2020 | Lauren L. Orefice | Massachusetts General Hospital
2020 | Xiao Wang | Broad Institute
2021 | Ahmed Abdelfattah | Brown University
2021 | Fei Chen | Broad Institute
2021 | Bradley H. Dickerson | Princeton University
2021 | Yun Ding | University of Pennsylvania
2021 | Vikram Gadagkar | Columbia University
2021 | Matthew Lovett-Barron | University of California, San Diego
2022 | Arkarup Banerjee | Cold Spring Harbor Laboratory
2022 | Ian C. Fiebelkorn | University of Rochester
2022 | Christina Kim | University of California, Davis
2022 | Guangyu Robert Yang | Massachusetts Institute of Technology
2022 | Meg A. Younger | Boston University
2023 | Sinisa Hrvatin | Whitehead Institute for Biomedical Research
2023 | Sergey Stavisky | University of California, Davis
2023 | Humsa Venkatesh | Harvard Medical School
2023 | Brittany Needham | Indiana University
2024 | Caroline Albertin | Marine Biological Laboratory
2024 | Vineet Augustine | University of California, San Diego
2024 | Ian Oldenburg | Rutgers University
2024 | Brandon Weissbourd | Massachusetts Institute of Technology
2025 | Carolyn Elya | Harvard University
2025 | Linlin Fan | Massachusetts Institute of Technology
2025 | Chen Ran | Scripps Research
2025 | Weizhen Xie | University of Maryland
2025 | Andrew Yang | Gladstone Institutes
"""


def parse_block(text, award):
    out = []
    for line in text.strip().splitlines():
        parts = [p.strip() for p in line.split('|')]
        if len(parts) >= 3 and re.match(r'20\d\d', parts[0]):
            out.append({'name': parts[1], 'institution': parts[2], 'award': award, 'year': int(parts[0])})
    return out


def parse_pipe_table(path, award, name_col=1, inst_col=2, year_col=0):
    out = []
    if not os.path.exists(path):
        return out
    for line in open(path):
        if '|' not in line:
            continue
        parts = [p.strip() for p in line.split('|')]
        parts = [p for p in parts if p != '']
        if len(parts) > max(name_col, inst_col, year_col) and re.match(r'^20\d\d$', parts[year_col]):
            nm = parts[name_col]
            if nm.lower() in ('full name', 'scholar', 'name') or nm.isdigit() or len(nm) < 3:
                continue
            inst = parts[inst_col]
            if inst.isdigit() or len(inst) < 3:
                continue
            out.append({'name': nm, 'institution': inst, 'award': award, 'year': int(parts[year_col])})
    return out


awards = []
awards += parse_block(MCKNIGHT, 'McKnight Scholar')
awards += parse_block(KLINGENSTEIN, 'Klingenstein-Simons')
awards += parse_block(SEARLE, 'Searle Scholar')
awards += parse_pipe_table(os.path.join(D, 'raw_pew.txt'), 'Pew Biomedical')
awards += parse_pipe_table(os.path.join(D, 'raw_searle.txt'), 'Searle Scholar')
awards += parse_pipe_table(os.path.join(D, 'raw_klingenstein.txt'), 'Klingenstein-Simons')

# dedup by (name, award, year)
seen = set(); uniq = []
for a in awards:
    k = (a['name'].lower(), a['award'], a['year'])
    if k in seen:
        continue
    seen.add(k); uniq.append(a)
json.dump(uniq, open(os.path.join(D, 'awards.json'), 'w'), indent=1)
from collections import Counter
print("awards.json:", len(uniq), dict(Counter(a['award'] for a in uniq)))
