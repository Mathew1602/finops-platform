"""Module 4: Cloud Infrastructure Cost Estimator."""

import pandas as pd
import plotly.express as px
import streamlit as st

from finops import assumptions as A
from finops import config_store as C
from finops import estimator as E
from finops import ui

ui.page_setup("Cost Estimator", ":material/calculate:")
st.title("Infrastructure Cost Estimator")
st.caption("Module 4: estimate hourly, daily, monthly and annual cost of a saved Module 3 scenario, "
           "priced from the Module 1 catalog (Floci API first, then documented reference prices).")

catalog, api_err = ui.get_catalog()
names = C.list_scenarios()
if not names:
    st.info("No scenarios yet. Create one in the Infrastructure Builder.")
    st.page_link("pages/3_Infrastructure_Builder.py", label="Open Infrastructure Builder", icon=":material/construction:")
    st.stop()

active = st.session_state.get("active_scenario")
name = st.selectbox("Scenario", names, index=names.index(active) if active in names else 0)
st.session_state["active_scenario"] = name
scn = C.load_scenario(name)
lines, missing = E.estimate(scn, catalog)

if scn.get("description"):
    st.caption(scn["description"])
if api_err:
    st.warning("Floci is unreachable, so every price comes from reference data.")
if missing:
    st.error("No price found for: " + ", ".join(missing) + ". Those lines are counted as $0.")
if lines.empty:
    st.info("This scenario has no resources. Add some in the Infrastructure Builder.")
    st.stop()

src = lines.price_source.unique().tolist()
ui.source_badges(["user_defined"] + [s for s in src if s != "missing"])

# ------------------------------------------------------------------ KPIs
t = E.totals(lines)
k1, k2, k3, k4 = st.columns(4)
k1.metric("Estimated monthly cost", ui.money(t["monthly"]))
k2.metric("Estimated annual cost", ui.money(t["annual"], 0))
k3.metric("Daily", ui.money(t["daily"]))
k4.metric("Hourly (average)", ui.money(t["hourly"], 4))

api_cost = lines.loc[lines.price_source == "floci_api", "monthly_usd"].sum()
api_share = 100 * api_cost / t["monthly"] if t["monthly"] else 0.0
st.caption(f"Region **{scn['region']}** · On-Demand pricing · {api_share:.0f}% of the estimate uses prices "
           "retrieved from the Floci Pricing API; the rest uses documented reference prices.")

# ------------------------------------------------------------------ breakdowns
by_svc = E.summarise(lines, "service")
by_res = E.summarise(lines, ["resource", "resource_type"])
money_cols = {c: st.column_config.NumberColumn(c.replace("_usd", "").capitalize(), format="$%.2f")
              for c in ["hourly_usd", "daily_usd", "monthly_usd", "annual_usd"]}
money_cols["hourly_usd"] = st.column_config.NumberColumn("Hourly", format="$%.4f")
money_cols["share_pct"] = st.column_config.ProgressColumn("Share", format="%.1f%%", min_value=0, max_value=100)

c1, c2 = st.columns([1, 1])
with c1:
    st.subheader("Cost per service")
    st.dataframe(by_svc, hide_index=True, width="stretch", column_config=money_cols)
with c2:
    st.plotly_chart(px.pie(by_svc, names="service", values="monthly_usd", hole=0.45,
                           title="Monthly cost share by service"), width="stretch")

st.subheader("Cost per resource")
st.plotly_chart(px.bar(lines, x="resource", y="monthly_usd", color="component", text_auto=".2f",
                       labels={"monthly_usd": "Monthly USD", "resource": ""},
                       title="Monthly cost per resource, stacked by component"), width="stretch")
st.dataframe(by_res, hide_index=True, width="stretch", column_config=money_cols)

if lines.department.nunique() > 1:
    st.plotly_chart(px.bar(E.summarise(lines, "department"), x="department", y="monthly_usd", text_auto=".2f",
                           labels={"monthly_usd": "Monthly USD"}, title="Monthly cost by department tag"),
                    width="stretch")

st.subheader("Line-item calculation")
st.caption("Every line shows the formula, unit price and the source of that price.")
st.dataframe(lines[["resource", "service", "component", "formula", "quantity", "unit", "unit_price",
                    "monthly_usd", "annual_usd", "price_source", "department"]],
             hide_index=True, width="stretch",
             column_config={"unit_price": st.column_config.NumberColumn("Unit price", format="$%.6g"),
                            **{k: v for k, v in money_cols.items() if k in ("monthly_usd", "annual_usd")}})
ui.download_csv(lines.assign(scenario=name, region=scn["region"], pricing_model="On-Demand"),
                f"estimate_{C.slugify(name)}.csv", "Download estimate (CSV)")

ui.assumptions_panel({
    "Pricing source": "Floci Pricing API where available, else data/reference (see price_source column)",
    "Region": scn["region"],
    "Billing period": "1 month = 730 h; annual = 12 months; no growth applied",
    "Pricing model": "On-Demand (see Pricing Comparison for commitment models)",
    "EC2 storage": "EBS GB per instance x instance count",
    "RDS": f"Multi-AZ = x{A.RDS_MULTI_AZ_FACTOR:g} instance + storage; PostgreSQL priced as MySQL",
    "Lambda": "Requests + GB-seconds; free tier not applied",
    "DynamoDB": "On-demand capacity mode",
    "Load balancer": "Hours + average capacity units per hour",
})

# ------------------------------------------------------------------ scenario comparison
st.divider()
st.subheader("Compare scenarios")
picked = st.multiselect("Scenarios", names, default=names[: min(3, len(names))])
if picked:
    rows = []
    for n in picked:
        ln, _ = E.estimate(C.load_scenario(n), catalog)
        if not ln.empty:
            rows.append(ln.groupby("service", as_index=False).monthly_usd.sum().assign(scenario=n))
    if rows:
        comp = pd.concat(rows)
        st.plotly_chart(px.bar(comp, x="scenario", y="monthly_usd", color="service", text_auto=".0f",
                               labels={"monthly_usd": "Monthly USD", "scenario": ""}), width="stretch")
        pivot = comp.pivot_table(index="service", columns="scenario", values="monthly_usd", aggfunc="sum",
                                 fill_value=0)
        pivot.loc["TOTAL / month"] = pivot.sum()
        pivot.loc["TOTAL / year"] = pivot.loc["TOTAL / month"] * A.MONTHS_PER_YEAR
        st.dataframe(pivot.style.format("${:,.2f}"), width="stretch")
