"""Module 5: Cloud Pricing Model Comparison."""

import plotly.express as px
import streamlit as st

from finops import assumptions as A
from finops import pricing as P
from finops import pricing_models as M
from finops import ui

ui.page_setup("Pricing Comparison", ":material/compare_arrows:")
st.title("Pricing Model Comparison")
st.caption("Module 5: compare On-Demand, Reserved, Savings Plans, Spot and storage tiers, "
           "calculate the potential savings, and explain each model's conditions.")

catalog, _ = ui.get_catalog()
region = st.sidebar.selectbox("Region", list(A.REGIONS), format_func=lambda r: f"{r} ({A.REGIONS[r]})")

MONEY = {c: st.column_config.NumberColumn(c.replace("_usd", "").replace("_", " ").capitalize(), format="$%.2f")
         for c in ["monthly_usd", "annual_usd", "period_usd", "upfront_usd", "savings_month_usd",
                   "savings_annual_usd", "period_savings_usd", "storage_usd", "retrieval_usd"]}
MONEY.update({
    "effective_hourly": st.column_config.NumberColumn("Effective $/h", format="$%.4f"),
    "savings_pct": st.column_config.NumberColumn("Savings %", format="%.1f%%"),
    "breakeven_utilisation_pct": st.column_config.NumberColumn("Break-even utilisation", format="%.0f%%"),
    "storage_price_gb": st.column_config.NumberColumn("$/GB-Mo", format="$%.5f"),
    "retrieval_price_gb": st.column_config.NumberColumn("Retrieval $/GB", format="$%.3f"),
})


def show_compute(models, count, util, months, unit_label):
    if not models:
        st.error("No On-Demand price found for this configuration.")
        return
    df = M.compare(models, count, util / 100, months)
    ui.source_badges(df)
    od = df.iloc[0]
    best = df.sort_values("monthly_usd").iloc[0]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("On-Demand monthly", ui.money(od.monthly_usd))
    k2.metric("On-Demand annual", ui.money(od.annual_usd, 0))
    k3.metric("Cheapest model", best.model)
    k4.metric("Max annual savings", ui.money(best.savings_annual_usd, 0),
              f"{best.savings_pct:.1f}% vs On-Demand", delta_color="normal" if best.savings_pct > 0 else "off")

    st.dataframe(df[["model", "effective_hourly", "billed_hours_month", "monthly_usd", "annual_usd",
                     "savings_month_usd", "savings_annual_usd", "savings_pct", "paid_months", "period_usd",
                     "period_savings_usd", "upfront_usd", "breakeven_utilisation_pct", "source"]],
                 hide_index=True, width="stretch",
                 column_config={**MONEY,
                                "paid_months": st.column_config.NumberColumn(
                                    "Months billed", help="Commitments are billed for whole terms."),
                                "period_usd": st.column_config.NumberColumn(
                                    f"Total paid for a {months}-month need", format="$%.0f"),
                                "period_savings_usd": st.column_config.NumberColumn(
                                    "Saving vs On-Demand over the period", format="$%.0f")})
    longer = df[df.paid_months > months]
    if not longer.empty:
        st.info(f"You need capacity for **{months} months**, but these commitments are billed for their whole "
                "term: " + ", ".join(f"{r.model} ({r.paid_months} months)" for r in longer.itertuples())
                + ". The monthly and annual columns show the rate while running; *Total paid* shows the full "
                "commitment, which can exceed On-Demand for a short need.", icon=":material/event_busy:")
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(px.bar(df, x="model", y=["monthly_usd"], text_auto=".0f", color="model",
                               title=f"Monthly cost: {count} x {unit_label} at {util}% utilisation",
                               labels={"value": "Monthly USD", "model": ""}).update_layout(showlegend=False),
                        width="stretch")
    with c2:
        curve = M.utilisation_curve(models, count)
        fig = px.line(curve, x="utilisation_pct", y="monthly_usd", color="model",
                      title="Monthly cost vs utilisation (commitments are flat)",
                      labels={"utilisation_pct": "Hours used (% of month)", "monthly_usd": "Monthly USD"})
        fig.add_vline(x=util, line_dash="dot")
        st.plotly_chart(fig, width="stretch")

    if util < 100:
        losers = df[(df.committed) & (df.savings_pct < 0)]
        if not losers.empty:
            st.warning(f"At {util}% utilisation, these commitments cost **more** than On-Demand: "
                       + ", ".join(losers.model) + ". You pay for reserved hours you do not use.")
    st.markdown("#### Conditions and limitations")
    for _, r in df.iterrows():
        st.markdown(f"- **{r.model}** ({r.basis}): {r.conditions}")


tab_ec2, tab_rds, tab_s3 = st.tabs([":material/dns: EC2 compute", ":material/database: RDS",
                                    ":material/inventory_2: S3 storage tiers"])

with tab_ec2:
    for k, v in {"ec2_type": "m5.large", "ec2_os": "Linux", "ec2_count": 5, "ec2_util": 100,
                 "ec2_months": 12}.items():
        st.session_state.setdefault(k, v)
    if st.button("Load brief example: 5 instances running continuously for 1 year", icon=":material/lightbulb:"):
        st.session_state.update({"ec2_type": "m5.large", "ec2_os": "Linux", "ec2_count": 5,
                                 "ec2_util": 100, "ec2_months": 12})
    types = sorted(catalog[(catalog.service == "AmazonEC2")]["product"].unique())
    c1, c2, c3, c4, c5 = st.columns(5)
    itype = c1.selectbox("Instance type", types, key="ec2_type")
    os_name = c2.selectbox("OS", ["Linux", "Windows"], key="ec2_os")
    count = c3.number_input("Instances", 1, 1000, key="ec2_count")
    util = c4.slider("Utilisation %", 5, 100, step=5, key="ec2_util",
                     help="Share of the month the instances actually run.")
    months = c5.number_input("Months", 1, 36, key="ec2_months")
    show_compute(M.ec2_models(catalog, itype, os_name, region), count, util, months, itype)

with tab_rds:
    c1, c2, c3, c4 = st.columns(4)
    rclass = c1.selectbox("DB instance class", sorted(catalog[(catalog.service == "AmazonRDS") &
                                                              (catalog.variant == "MySQL")]["product"].unique()),
                          index=2)
    multi_az = c2.toggle("Multi-AZ", True)
    rcount = c3.number_input("Instances", 1, 100, 1, key="rds_count")
    rutil = c4.slider("Utilisation %", 5, 100, 100, 5, key="rds_util")
    show_compute(M.rds_models(catalog, rclass, multi_az, region), rcount, rutil, 12, rclass)

with tab_s3:
    st.caption("Storage pricing tiers: the same data stored in different S3 classes. Retrieval fees and "
               "minimum storage durations decide which class is actually cheaper.")
    c1, c2, c3 = st.columns(3)
    gb = c1.number_input("Data stored (GB)", 1.0, 10_000_000.0, 1000.0, step=100.0)
    rpct = c2.slider("Data retrieved per month (% of stored)", 0, 200, 5,
                     help="High values show how retrieval fees erase archive-tier savings.")
    smonths = c3.number_input("Months", 1, 36, 12, key="s3_months")
    sdf = M.compare_storage(catalog, gb, rpct, region, smonths)
    ui.source_badges(sdf)
    best = sdf.sort_values("monthly_usd").iloc[0]
    k1, k2, k3 = st.columns(3)
    k1.metric("S3 Standard monthly", ui.money(sdf.iloc[0].monthly_usd))
    k2.metric("Cheapest tier", best.tier)
    k3.metric("Annual savings vs Standard", ui.money(best.savings_month_usd * 12, 0), f"{best.savings_pct:.1f}%")
    st.dataframe(sdf[["tier", "storage_price_gb", "retrieval_price_gb", "storage_usd", "retrieval_usd",
                      "monthly_usd", "annual_usd", "savings_pct", "retrieval_latency", "min_storage_days",
                      "best_for", "source"]], hide_index=True, width="stretch", column_config=MONEY)
    st.plotly_chart(px.bar(sdf, x="tier", y=["storage_usd", "retrieval_usd"], barmode="stack",
                           title=f"Monthly cost for {gb:,.0f} GB with {rpct}% retrieved each month",
                           labels={"value": "Monthly USD", "tier": "", "variable": "Component"}),
                    width="stretch")
    st.info("Archive tiers suit data such as historical reports or old logs **only if** their retrieval "
            "latency and minimum storage duration meet business requirements. Deleting data early incurs "
            "a pro-rated charge for the remaining minimum days.", icon=":material/info:")

ui.assumptions_panel({
    "Reserved 1yr (EC2)": "Effective hourly from ec2_instances.csv where present, else "
                          f"{A.RESERVED_1YR_NO_UPFRONT_DISCOUNT:.0%} discount",
    "Reserved 3yr All Upfront": f"{A.RESERVED_3YR_ALL_UPFRONT_DISCOUNT:.0%} discount (assumed)",
    "Savings Plans": f"1yr {A.SAVINGS_PLAN_1YR_DISCOUNT:.0%}, 3yr {A.SAVINGS_PLAN_3YR_DISCOUNT:.0%} "
                     "discount (assumed; Floci has no Savings Plans pricing API)",
    "Spot": "Minimum observed spot price from ec2_instances.csv, else "
            f"{A.SPOT_DEFAULT_DISCOUNT:.0%} discount; actual spot prices fluctuate",
    "RDS Reserved 1yr": f"{A.RDS_RESERVED_1YR_DISCOUNT:.0%} discount (assumed)",
    "Commitments": "Billed for all 730 h/month regardless of utilisation, and for whole 1- or 3-year terms",
    "3yr All Upfront": "Monthly / annual figures amortise the upfront payment; the Upfront column is the cash paid",
})
