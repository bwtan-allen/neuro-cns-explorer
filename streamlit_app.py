"""
HHMI & non-HHMI Neuroscience CNS-publication explorer.

Data source: neuro_stats.json (built from PubMed last-author / corresponding-author tallies).
Run:  streamlit run streamlit_app.py
"""
import json
import os
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Neuro CNS Publication Explorer", layout="wide")

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "neuro_stats.json")


@st.cache_data
def load():
    with open(DATA) as f:
        d = json.load(f)
    years = [str(y) for y in d["years"]]
    rows = []
    for r in d["records"]:
        cby = r.get("cns_by_year", {})
        nby = r.get("noncns_by_year", {})
        cns_years_covered = sum(1 for y in years if cby.get(y, 0) > 0)
        nc_avail = r.get("noncns_available", True)
        noncns_total = r.get("noncns_total")
        nc_years_covered = sum(1 for y in years if nby.get(y, 0) > 0) if nc_avail else None
        rows.append({
            "Name": r["name"],
            "Group": r["group"],
            "Institution": r["institution"],
            "Field": r.get("field", ""),
            "Neuro_confidence": r.get("neuro_confidence", ""),
            "Career_stage": r.get("career_stage", ""),
            "Lab_start_year": r.get("lab_start_year"),
            "First_senior_paper": r.get("first_senior_paper_yr"),
            "Lab_age": r.get("lab_age"),
            "Lab_age_source": r.get("lab_age_source", ""),
            "Awards": r.get("award_names", ""),
            "N_awards": r.get("n_awards", 0),
            "CNS_total": r.get("cns_total", 0),
            "CNS_years_covered": cns_years_covered,
            "CNS_avg_per_yr": round((r.get("cns_total", 0) or 0) / 10, 2),
            "nonCNS_total": noncns_total,
            "nonCNS_years_covered": nc_years_covered,
            "nonCNS_avg_per_yr": (round(noncns_total / 10, 2) if isinstance(noncns_total, (int, float)) else None),
            "NeuronNatNeuro_total": r.get("fieldtier_total"),
            "eLife_total": r.get("elife_total"),
            **{f"CNS_{y}": cby.get(y, 0) for y in years},
            **{f"nonCNS_{y}": (nby.get(y, 0) if nc_avail else None) for y in years},
            **{f"field_{y}": (r.get("fieldtier_by_year", {}).get(y, 0) if r.get("fieldjournals_available") else None) for y in years},
            **{f"elife_{y}": (r.get("elife_by_year", {}).get(y, 0) if r.get("fieldjournals_available") else None) for y in years},
        })
    df = pd.DataFrame(rows)
    return df, years


df, YEARS = load()

st.title("🧠 Neuroscience CNS Publication Explorer")
st.caption(
    "Corresponding-author (last-author proxy) papers in **Cell / Nature / Science** and non-CNS journals, "
    "2016–2025. HHMI investigators, established non-HHMI PIs, **rising-star junior PIs**, and **early-career "
    "award winners** (Searle / Pew / McKnight / Klingenstein-Simons), across 30+ top US institutions (incl. MPFI). "
    "Lab start = ORCID faculty-appointment year when available, else first senior-author paper year (~lower bound)."
)

# ---------------- Sidebar filters ----------------
st.sidebar.header("Filters")
groups = st.sidebar.multiselect("Group", sorted(df["Group"].unique()), default=list(df["Group"].unique()))
stages = st.sidebar.multiselect("Career stage", sorted(df["Career_stage"].dropna().unique()))
insts = st.sidebar.multiselect("Institution", sorted(df["Institution"].unique()))
award_opts = sorted({a for s in df["Awards"] for a in (s.split(", ") if s else []) if a})
awards_sel = st.sidebar.multiselect("Award", award_opts)
name_q = st.sidebar.text_input("Search name / institution / field")
min_cns = st.sidebar.slider("Min CNS total", 0, int(df["CNS_total"].max()), 0)
min_cns_years = st.sidebar.slider("Min CNS years covered", 0, 10, 0)
max_lab_age = st.sidebar.slider("Max lab age (yrs since lab start / first paper; 0 = ignore)", 0, 25, 0)
conf_only_core = st.sidebar.checkbox("Only 'core' neuroscience (exclude neuro-adjacent)", value=False)

f = df[df["Group"].isin(groups)].copy()
if stages:
    f = f[f["Career_stage"].isin(stages)]
if insts:
    f = f[f["Institution"].isin(insts)]
if awards_sel:
    f = f[f["Awards"].apply(lambda s: any(a in (s.split(", ") if s else []) for a in awards_sel))]
if name_q:
    q = name_q.lower()
    f = f[f.apply(lambda r: q in str(r["Name"]).lower() or q in str(r["Institution"]).lower()
                  or q in str(r["Field"]).lower(), axis=1)]
f = f[(f["CNS_total"] >= min_cns) & (f["CNS_years_covered"] >= min_cns_years)]
if max_lab_age > 0:
    f = f[f["Lab_age"].notna() & (f["Lab_age"] <= max_lab_age)]
if conf_only_core:
    f = f[f["Neuro_confidence"].str.startswith("core")]

# ---------------- Top metrics ----------------
c1, c2, c3, c4 = st.columns(4)
c1.metric("Researchers", len(f))
c2.metric("Rising stars", int((f["Group"] == "rising-star").sum()))
c3.metric("Award winners", int((f["N_awards"] > 0).sum()))
c4.metric("≥1 CNS/yr avg (≥10 total)", int((f["CNS_total"] >= 10).sum()))

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["📋 Table", "📊 Rankings", "👤 Researcher detail", "🔬 CNS vs non-CNS", "🌟 Rising stars"])

# ---------------- Table ----------------
with tab1:
    sort_col = st.selectbox("Sort by", ["CNS_total", "nonCNS_total", "CNS_years_covered", "Name"], index=0)
    show = f.sort_values(sort_col, ascending=(sort_col == "Name"))
    base_cols = ["Name", "Group", "Institution", "Field", "Awards", "Career_stage", "Lab_start_year",
                 "First_senior_paper", "Lab_age", "CNS_total", "NeuronNatNeuro_total", "eLife_total",
                 "nonCNS_total", "CNS_years_covered", "Neuro_confidence"]
    st.dataframe(show[base_cols], use_container_width=True, height=560)
    st.download_button("Download filtered CSV", show.to_csv(index=False).encode(),
                       "filtered_neuro_stats.csv", "text/csv")

# ---------------- Rankings ----------------
with tab2:
    metric = st.radio("Metric", ["CNS_total", "NeuronNatNeuro_total", "eLife_total", "nonCNS_total",
                                 "CNS_avg_per_yr"], horizontal=True)
    topn = st.slider("Show top N", 5, 60, 25)
    r = f.dropna(subset=[metric]).sort_values(metric, ascending=False).head(topn)
    fig = px.bar(r, x=metric, y="Name", color="Group", orientation="h",
                 hover_data=["Institution", "Field", "CNS_total", "nonCNS_total"],
                 height=max(400, 22 * len(r)))
    fig.update_layout(yaxis={"categoryorder": "total ascending"}, legend_title="")
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Institution summary")
    inst_sum = (f.groupby("Institution")
                .agg(researchers=("Name", "count"), CNS_total=("CNS_total", "sum"))
                .reset_index().sort_values("CNS_total", ascending=False))
    st.plotly_chart(px.bar(inst_sum, x="Institution", y="CNS_total", hover_data=["researchers"],
                           height=420), use_container_width=True)

# ---------------- Researcher detail ----------------
with tab3:
    if len(f):
        who = st.selectbox("Researcher", f.sort_values("CNS_total", ascending=False)["Name"].tolist())
        row = f[f["Name"] == who].iloc[0]
        st.markdown(f"**{who}** — {row['Institution']} · _{row['Field']}_ · **{row['Group']}**")
        if row.get("Awards"):
            st.markdown(f"🏅 **Awards:** {row['Awards']}")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("CNS (Cell/Nat/Sci)", int(row["CNS_total"]), f"{row['CNS_years_covered']}/10 yrs")
        ftt = row["NeuronNatNeuro_total"]
        m2.metric("Neuron + Nat Neurosci", "n/a" if pd.isna(ftt) else int(ftt))
        elt = row["eLife_total"]
        m3.metric("eLife", "n/a" if pd.isna(elt) else int(elt))
        nct = row["nonCNS_total"]
        m4.metric("non-CNS (all other)", "n/a" if pd.isna(nct) else int(nct))
        cns = [int(row[f"CNS_{y}"]) for y in YEARS]
        ncs = [None if pd.isna(row[f"nonCNS_{y}"]) else int(row[f"nonCNS_{y}"]) for y in YEARS]
        fld = [None if pd.isna(row[f"field_{y}"]) else int(row[f"field_{y}"]) for y in YEARS]
        elf = [None if pd.isna(row[f"elife_{y}"]) else int(row[f"elife_{y}"]) for y in YEARS]
        fig = go.Figure()
        fig.add_bar(x=YEARS, y=cns, name="CNS", marker_color="#d62728")
        fig.add_bar(x=YEARS, y=fld, name="Neuron+NatNeuro", marker_color="#9467bd")
        fig.add_bar(x=YEARS, y=elf, name="eLife", marker_color="#2ca02c")
        fig.add_bar(x=YEARS, y=ncs, name="non-CNS", marker_color="#c7c7c7")
        fig.update_layout(barmode="group", height=440, xaxis_title="Year",
                          yaxis_title="Corresponding-author papers")
        st.plotly_chart(fig, use_container_width=True)
        gaps = [y for y in YEARS if row[f"CNS_{y}"] == 0]
        st.caption(f"CNS gap years: {', '.join(gaps) if gaps else 'none'}")
    else:
        st.info("No researchers match the current filters.")

# ---------------- CNS vs non-CNS scatter ----------------
with tab4:
    s = f.dropna(subset=["nonCNS_total"]).copy()
    fig = px.scatter(s, x="nonCNS_total", y="CNS_total", color="Group", hover_name="Name",
                     hover_data=["Institution", "Field"], size="CNS_total", size_max=22, height=560)
    fig.add_hline(y=5, line_dash="dot", annotation_text="0.5 CNS/yr")
    fig.add_hline(y=10, line_dash="dot", annotation_text="1 CNS/yr")
    fig.update_layout(xaxis_title="non-CNS corresponding papers (10 yr)",
                      yaxis_title="CNS corresponding papers (10 yr)")
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Upper-left = CNS-concentrated labs; lower-right = high-volume labs whose flagship count "
               "understates output. Dotted lines mark the 0.5/yr and 1/yr thresholds.")

# ---------------- Rising stars ----------------
with tab5:
    st.subheader("🌟 Rising-star junior PIs & early-career award winners")
    st.caption("Junior PIs (recent lab start) with flagship traction or prestigious early-career awards "
               "(Searle / Pew / McKnight / Klingenstein-Simons). **Lab start** = ORCID faculty-appointment year "
               "when available, else first senior-author paper year (a lagging lower bound).")
    rs = df[df["Group"].isin(["rising-star", "early-career awardee"]) | (df["N_awards"] > 0)].copy()
    ca, cb, cc = st.columns(3)
    max_age = ca.slider("Max lab age (yrs)", 3, 20, 12, key="rs_age")
    inst_rs = cb.multiselect("Institution", sorted(rs["Institution"].unique()), key="rs_inst")
    aw_rs = cc.multiselect("Award", award_opts, key="rs_award")
    rs = rs[(rs["Lab_age"].isna()) | (rs["Lab_age"] <= max_age)]
    if inst_rs:
        rs = rs[rs["Institution"].isin(inst_rs)]
    if aw_rs:
        rs = rs[rs["Awards"].apply(lambda s: any(a in (s.split(", ") if s else []) for a in aw_rs))]
    rs = rs.sort_values(["Lab_age", "CNS_total"], ascending=[True, False], na_position="last")
    st.metric("Rising stars / awardees shown", len(rs))
    cols = ["Name", "Institution", "Awards", "Lab_start_year", "First_senior_paper", "Lab_age",
            "Lab_age_source", "CNS_total", "nonCNS_total", "Career_stage"]
    st.dataframe(rs[cols], use_container_width=True, height=460)
    plot = rs.copy()
    plot["Start"] = plot["Lab_start_year"].fillna(plot["First_senior_paper"])
    plot = plot.dropna(subset=["Start"])
    if len(plot):
        fig = px.scatter(plot, x="Start", y="CNS_total", size=plot["nonCNS_total"].fillna(1).clip(lower=1),
                         color="Institution", hover_name="Name", size_max=20, height=460,
                         hover_data=["Awards", "Career_stage"],
                         labels={"Start": "Lab start (ORCID appt or first-paper proxy)",
                                 "CNS_total": "CNS papers (2016–2025)"})
        st.plotly_chart(fig, use_container_width=True)
    st.download_button("Download rising stars / awardees CSV", rs.to_csv(index=False).encode(),
                       "rising_stars_awardees.csv", "text/csv")
