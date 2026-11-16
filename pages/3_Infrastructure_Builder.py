"""Module 3: Cloud Infrastructure Configuration Builder."""

import json

import pandas as pd
import streamlit as st

from finops import assumptions as A
from finops import config_store as C
from finops import pricing as P
from finops import ui

ui.page_setup("Infrastructure Builder", ":material/construction:")
st.title("Infrastructure Configuration Builder")
st.caption("Module 3: define hypothetical cloud environments, save them, and build multiple scenarios. "
           "These are user-defined configurations, not deployed resources.")
ui.source_badges(["user_defined"])


@st.cache_data
def ec2_types() -> list[str]:
    return sorted(P.load_ec2_reference().instance_type.unique())


def column_config(rtype: str) -> dict:
    cfg = {}
    for field, (kind, default, opts, help_) in C.RESOURCE_SPECS[rtype]["fields"].items():
        label = field.replace("_", " ").capitalize()
        if kind == "select":
            options = ec2_types() if opts == "EC2_TYPES" else opts
            cfg[field] = st.column_config.SelectboxColumn(label, options=options, default=default,
                                                          required=True, help=help_)
        elif kind in ("int", "float"):
            lo, hi = opts
            cfg[field] = st.column_config.NumberColumn(label, min_value=lo, max_value=hi, default=default,
                                                       step=1 if kind == "int" else None, required=True, help=help_)
        elif kind == "bool":
            cfg[field] = st.column_config.CheckboxColumn(label, default=default, help=help_)
        else:
            cfg[field] = st.column_config.TextColumn(label, default=default, required=True, help=help_)
    return cfg


# ------------------------------------------------------------------ pick scenario
names = C.list_scenarios()
NEW = "➕ New scenario"
c1, c2 = st.columns([3, 1])
choice = c1.selectbox("Scenario", [NEW] + names,
                      index=(names.index(st.session_state["active_scenario"]) + 1)
                      if st.session_state.get("active_scenario") in names else 1 if names else 0)
uploaded = c2.file_uploader("Import JSON", type="json", label_visibility="collapsed")

if uploaded is not None and st.session_state.get("_imported") != uploaded.file_id:
    scn = json.load(uploaded)
    C.save_scenario(scn)
    st.session_state["_imported"] = uploaded.file_id
    st.session_state["active_scenario"] = scn["name"]
    st.rerun()

if st.session_state.get("_loaded") != choice:
    st.session_state["work"] = C.new_scenario("") if choice == NEW else C.load_scenario(choice)
    # The editors always receive the rows as loaded; st.data_editor keeps the
    # user's edits in its own widget state on top of that base.
    st.session_state["base_rows"] = {k: list(v) for k, v in st.session_state["work"]["resources"].items()}
    st.session_state["_loaded"] = choice
    st.session_state["_ver"] = st.session_state.get("_ver", 0) + 1
    if choice != NEW:
        st.session_state["active_scenario"] = choice
work = st.session_state["work"]
ver = st.session_state["_ver"]

# ------------------------------------------------------------------ header fields
c1, c2 = st.columns([2, 1])
work["name"] = c1.text_input("Scenario name", work["name"], placeholder="e.g. Analytics growth 2027")
regions = list(A.REGIONS)
work["region"] = c2.selectbox("Region", regions, index=regions.index(work.get("region", A.BASE_REGION)),
                              format_func=lambda r: f"{r} ({A.REGIONS[r]})")
work["description"] = st.text_area("Description / notes", work.get("description", ""), height=68)

# ------------------------------------------------------------------ resource editors
st.subheader("Resources")
st.caption("Add rows with the ➕ at the bottom of each table. Every resource carries a *department* tag "
           "for cost allocation.")
edited = {}
for rtype, spec in C.RESOURCE_SPECS.items():
    base = st.session_state["base_rows"].get(rtype, [])
    current = work["resources"].get(rtype, [])
    with st.expander(f"{spec['label']} ({len(current)})", expanded=bool(base)):
        df = pd.DataFrame(base, columns=list(spec["fields"]))
        out = st.data_editor(df, num_rows="dynamic", column_config=column_config(rtype),
                             hide_index=True, width="stretch", key=f"ed_{rtype}_{ver}")
        edited[rtype] = C.normalise_rows(rtype, out.to_dict("records"))
work["resources"] = edited

# ------------------------------------------------------------------ actions
st.divider()
summary = C.scenario_summary(work)
st.write("**Scenario contents:** " + (", ".join(f"{C.RESOURCE_SPECS[k]['label']}: {v}" for k, v in summary.items())
                                      or "no resources yet"))
b1, b2, b3, b4 = st.columns(4)
if b1.button("Save scenario", type="primary", icon=":material/save:", width="stretch"):
    if not work["name"].strip():
        st.error("Give the scenario a name first.")
    else:
        path = C.save_scenario(work)
        st.session_state["active_scenario"] = work["name"]
        st.session_state["_loaded"] = work["name"]
        st.toast(f"Saved to {path}", icon=":material/check:")
        st.rerun()
if b2.button("Duplicate as new", icon=":material/content_copy:", width="stretch", disabled=choice == NEW):
    copy = {**work, "name": f"{work['name']} (copy)"}
    C.save_scenario(copy)
    st.session_state["active_scenario"] = copy["name"]
    st.session_state["_loaded"] = None
    st.rerun()
if b3.button("Delete", icon=":material/delete:", width="stretch", disabled=choice == NEW):
    C.delete_scenario(choice)
    st.session_state.pop("active_scenario", None)
    st.session_state["_loaded"] = None
    st.rerun()
b4.download_button("Export JSON", json.dumps(work, indent=2), f"{C.slugify(work['name'] or 'scenario')}.json",
                   mime="application/json", icon=":material/download:", width="stretch")

if choice != NEW:
    st.page_link("pages/4_Cost_Estimator.py", label="Estimate the cost of this scenario →", icon=":material/calculate:")

# ------------------------------------------------------------------ all scenarios
st.subheader("Saved scenarios")
rows = []
for n in C.list_scenarios():
    s = C.load_scenario(n)
    rows.append({"name": n, "region": s["region"], "resources": sum(C.scenario_summary(s).values()),
                 "types": ", ".join(C.scenario_summary(s)), "updated": s.get("updated")})
st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
