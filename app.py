"""Home page: overall cloud cost summary and platform status."""

import pandas as pd
import plotly.express as px
import streamlit as st

from finops import billing as B
from finops import ui
from finops.capabilities import probe

ui.page_setup("Home", ":material/home:")
st.title("Intelligent Cloud FinOps Platform")
st.caption("Cloud cost visibility, financial planning and optimisation. "
           "Built with Floci (local AWS emulator), Python/boto3 and Streamlit.")

COMPANY_BUDGET = 5000  # final-demo scenario: monthly cloud budget


@st.cache_data(show_spinner=False)
def billing():
    return B.load_synthetic_billing()


@st.cache_data(ttl=120, show_spinner="Probing Floci operations...")
def capabilities():
    return probe()


df = billing()
ins = B.insights(df)

st.error("Spend figures on this page come from the **simulated billing dataset**, because Floci Cost Explorer "
         "returns no billing records. They are not actual AWS expenditure.", icon=":material/science:")

k1, k2, k3, k4 = st.columns(4)
if "last_month" in ins:
    lm, lv = ins["last_month"]
    k1.metric(f"Spend {lm:%b %Y}", ui.money(lv, 0), f"{ins['mom_pct']:+.1f}% MoM", delta_color="inverse")
    k2.metric("Monthly budget", ui.money(COMPANY_BUDGET, 0), f"{100 * lv / COMPANY_BUDGET:.0f}% used",
              delta_color="off")
    k3.metric("Over / under budget", ui.money(lv - COMPANY_BUDGET, 0),
              "over budget" if lv > COMPANY_BUDGET else "within budget",
              delta_color="inverse" if lv > COMPANY_BUDGET else "normal")
    k4.metric("15% reduction target", ui.money(lv * 0.85, 0), f"save {ui.money(lv * 0.15, 0)}/month",
              delta_color="off")

c1, c2 = st.columns([3, 2])
with c1:
    m = B.monthly(df, "department")
    fig = px.bar(m, x="month", y="cost_usd", color="department", title="Monthly spend by department (simulated)",
                 labels={"cost_usd": "USD", "month": ""})
    fig.add_hline(y=COMPANY_BUDGET, line_dash="dash", annotation_text="$5,000 budget")
    st.plotly_chart(fig, width="stretch")
with c2:
    svc = B.by_dimension(df[df.date >= df.date.max() - pd.Timedelta(days=30)], "service")
    st.plotly_chart(px.pie(svc, names="service", values="cost_usd", hole=0.5, title="Last 30 days by service"),
                    width="stretch")

st.subheader("Modules")
MODULES = [
    ("pages/1_Pricing_Explorer.py", "1 · Pricing Explorer", ":material/sell:",
     "Retrieve and explore service prices through the Floci Pricing API"),
    ("pages/2_Cost_Explorer.py", "2 · Cost Explorer", ":material/query_stats:",
     "Analyse expenditure by service, region and period; export reports"),
    ("pages/3_Infrastructure_Builder.py", "3 · Infrastructure Builder", ":material/construction:",
     "Configure and save hypothetical cloud environments"),
    ("pages/4_Cost_Estimator.py", "4 · Cost Estimator", ":material/calculate:",
     "Hourly / daily / monthly / annual cost of a scenario"),
    ("pages/5_Pricing_Comparison.py", "5 · Pricing Comparison", ":material/compare_arrows:",
     "On-Demand vs Reserved vs Savings Plans vs Spot; S3 storage tiers"),
]
cols = st.columns(len(MODULES))
for col, (path, label, icon, desc) in zip(cols, MODULES):
    with col.container(border=True, height="stretch"):
        st.page_link(path, label=label, icon=icon)
        st.caption(desc)

st.subheader("Floci service compatibility")
st.caption("Each operation is called once against the running Floci instance, as the brief requires.")
caps = capabilities()
st.dataframe(caps, hide_index=True, width="stretch",
             column_config={"status": st.column_config.TextColumn("Status")})
