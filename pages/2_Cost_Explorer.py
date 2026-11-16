"""Module 2: Cloud Cost Explorer."""

import datetime as dt
import io
import zipfile

import pandas as pd
import plotly.express as px
import streamlit as st

from finops import billing as B
from finops import ui

ui.page_setup("Cost Explorer", ":material/query_stats:")
st.title("Cloud Cost Explorer")
st.caption("Module 2: analyse cloud expenditure from the Floci Cost Explorer API, "
           "or from a synthetic billing dataset when Floci has no billing records.")


@st.cache_data(ttl=120, show_spinner="Querying Floci Cost Explorer...")
def load_api(start, end):
    try:
        return B.query_ce(start, end, "DAILY", ("SERVICE", "REGION")), None
    except Exception as exc:  # noqa: BLE001
        return pd.DataFrame(), str(exc)


@st.cache_data(show_spinner="Loading synthetic billing dataset...")
def load_sim():
    return B.load_synthetic_billing()


# ------------------------------------------------------------------ source selection
sim_all = load_sim()
period_start, period_end = sim_all.date.min().date(), sim_all.date.max().date()
api_df, api_err = load_api(period_start, period_end + dt.timedelta(days=1))
api_ok = B.ce_has_data(api_df)

with st.sidebar:
    st.subheader("Data source")
    mode = st.radio("Cost data", ["Auto", "Floci Cost Explorer API", "Simulated billing dataset"],
                    help="Auto uses the API when it returns non-zero costs, otherwise the simulated dataset.")
    extend = st.checkbox("Extend to yesterday", help="Off: rebuild the same dataset over the same dates "
                         "(reproducible). On: move it to the 12 months ending yesterday, which changes the figures.")
    if st.button("Regenerate simulated dataset", icon=":material/restart_alt:"):
        B.load_synthetic_billing(regenerate=True, extend_to_today=extend)
        st.cache_data.clear()
        st.rerun()

with st.expander("Floci Cost Explorer API check", icon=":material/fact_check:", expanded=not api_ok):
    if api_err:
        st.error(f"`get_cost_and_usage` failed: {api_err}")
    else:
        st.write(f"`get_cost_and_usage` ({period_start} → {period_end}, DAILY, grouped by SERVICE + REGION) "
                 f"returned **{len(api_df):,} rows** across **{api_df['service'].nunique() if not api_df.empty else 0} "
                 f"services**, total **{ui.money(api_df.cost_usd.sum() if not api_df.empty else 0)}**.")
        st.dataframe(api_df.head(50), hide_index=True, width="stretch")

if mode == "Floci Cost Explorer API" or (mode == "Auto" and api_ok):
    data, source = api_df, B.SRC_API
    if not api_ok:
        st.error("Floci Cost Explorer returned no non-zero cost records. Switch to *Auto* or *Simulated*.")
else:
    data, source = sim_all, B.SRC_SIM

if source == B.SRC_SIM:
    st.error("**SIMULATED BILLING DATA.** These figures come from a generated dataset "
             "(`data/synthetic_billing.csv`) and are not actual AWS expenditure.", icon=":material/science:")
else:
    st.success("**Actual Floci Cost Explorer API response.**", icon=":material/verified:")

if data.empty:
    st.stop()

# ------------------------------------------------------------------ filters
f1, f2, f3 = st.columns([2, 2, 2])
rng = f1.date_input("Date range", (data.date.min().date(), data.date.max().date()),
                    min_value=data.date.min().date(), max_value=data.date.max().date())
start, end = (rng if isinstance(rng, tuple) and len(rng) == 2 else (data.date.min(), data.date.max()))
depts = sorted(data.department.unique()) if "department" in data else []
sel_depts = f2.multiselect("Departments", depts, default=depts) if depts else []
regions = sorted(data.region.dropna().unique())
sel_regions = f3.multiselect("Regions", regions, default=regions)

df = B.filter_period(data, start, end)
if sel_depts:
    df = df[df.department.isin(sel_depts)]
df = df[df.region.isin(sel_regions)]
if df.empty:
    st.warning("No data for the selected filters.")
    st.stop()

ins = B.insights(df)

# ------------------------------------------------------------------ KPIs
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Total expenditure", ui.money(df.cost_usd.sum(), 0), help=f"{start} → {end}")
if "last_month" in ins:
    lm, lv = ins["last_month"]
    pm, pv = ins["prev_month"]
    k2.metric(f"Last full month ({lm:%b %Y})", ui.money(lv, 0),
              f"{ins['mom_pct']:+.1f}% vs {pm:%b}" if ins["mom_pct"] is not None else None,
              delta_color="inverse")
else:
    k2.metric("Last full month", "n/a")
days = max((pd.Timestamp(end) - pd.Timestamp(start)).days + 1, 1)
k3.metric("Average daily spend", ui.money(df.cost_usd.sum() / days))
if ins.get("top_service"):
    k4.metric("Top service", ins["top_service"][0], ui.money(ins["top_service"][1], 0), delta_color="off")
if ins.get("top_region"):
    k5.metric("Top region", ins["top_region"][0], ui.money(ins["top_region"][1], 0), delta_color="off")

# ------------------------------------------------------------------ insights
with st.container(border=True):
    st.markdown("#### Key findings")
    lines = []
    if ins.get("top_service"):
        lines.append(f"**Highest-cost service:** {ins['top_service'][0]} "
                     f"({ui.money(ins['top_service'][1], 0)} in the selected period).")
    if "last_month" in ins:
        lines.append(f"**Previous month ({ins['last_month'][0]:%B %Y}):** {ui.money(ins['last_month'][1])}.")
    if ins.get("top_region"):
        lines.append(f"**Most expensive region:** {ins['top_region'][0]}.")
    if "trend_per_month" in ins:
        t = ins["trend_per_month"]
        lines.append(f"**Is expenditure increasing?** {'Yes' if t > 0 else 'No'}: the linear trend across full "
                     f"months is {t:+,.0f} USD/month ({t * 12:+,.0f} USD/year).")
    if "increase_drivers" in ins and not ins["increase_drivers"].empty:
        drv = ", ".join(f"{r.service} (+{ui.money(r.change_usd, 0)})" for r in ins["increase_drivers"].itertuples())
        lines.append(f"**Largest contributors to the last month-over-month increase:** {drv}.")
    st.markdown("\n".join(f"- {line}" for line in lines))

# ------------------------------------------------------------------ charts
st.subheader("Monthly expenditure")
color_by = st.segmented_control("Colour by", ["service", "region"] + (["department"] if depts else []),
                                default="service")
mdf = B.monthly(df, color_by or "service")
st.plotly_chart(px.bar(mdf, x="month", y="cost_usd", color=color_by or "service",
                       labels={"cost_usd": "Cost (USD)", "month": ""}), width="stretch")
st.caption("The final month may be partial.")

c1, c2 = st.columns(2)
with c1:
    st.subheader("Service breakdown")
    svc = B.by_dimension(df, "service")
    st.plotly_chart(px.pie(svc, names="service", values="cost_usd", hole=0.45), width="stretch")
with c2:
    st.subheader("Regional breakdown")
    reg = B.by_dimension(df, "region")
    st.plotly_chart(px.bar(reg, x="region", y="cost_usd", text_auto=".3s",
                           labels={"cost_usd": "Cost (USD)"}), width="stretch")

st.subheader("Daily cost trend")
d = B.daily(df)
fig = px.line(d, x="date", y=["cost_usd", "7d_avg"], labels={"value": "Cost (USD)", "variable": ""})
st.plotly_chart(fig, width="stretch")

st.subheader("Top expensive services")
# st.slider needs min < max, so only offer it when there are more than 3 services.
n = st.slider("Show top N", 3, len(svc), min(5, len(svc))) if len(svc) > 3 else len(svc)
top = svc.head(n)
st.plotly_chart(px.bar(top.iloc[::-1], x="cost_usd", y="service", orientation="h", text_auto=".3s",
                       labels={"cost_usd": "Cost (USD)", "service": ""}), width="stretch")

# ------------------------------------------------------------------ period comparison
st.subheader("Compare two periods")
months = B.full_months(df)
default_p2 = B.month_bounds(months[-1]) if months else (pd.Timestamp(start), pd.Timestamp(end))
default_p1 = B.month_bounds(months[-2]) if len(months) >= 2 else default_p2
c1, c2, c3 = st.columns([2, 2, 1])
p1 = c1.date_input("Period 1", (default_p1[0].date(), default_p1[1].date()), key="p1")
p2 = c2.date_input("Period 2", (default_p2[0].date(), default_p2[1].date()), key="p2")
dim = c3.selectbox("Group by", ["service", "region"] + (["department"] if depts else []))
if isinstance(p1, tuple) and len(p1) == 2 and isinstance(p2, tuple) and len(p2) == 2:
    cmp = B.compare_periods(df, p1, p2, dim)
    t1, t2 = cmp.period_1.sum(), cmp.period_2.sum()
    m1, m2, m3 = st.columns(3)
    m1.metric("Period 1 total", ui.money(t1, 0))
    m2.metric("Period 2 total", ui.money(t2, 0))
    m3.metric("Change", ui.money(t2 - t1, 0), f"{100 * (t2 / t1 - 1):+.1f}%" if t1 else None, delta_color="inverse")
    st.dataframe(cmp, hide_index=True, width="stretch", column_config={
        "period_1": st.column_config.NumberColumn("Period 1", format="$%.2f"),
        "period_2": st.column_config.NumberColumn("Period 2", format="$%.2f"),
        "change_usd": st.column_config.NumberColumn("Change", format="$%.2f"),
        "change_pct": st.column_config.NumberColumn("Change %", format="%.1f%%"),
    })
    st.plotly_chart(px.bar(cmp, x=dim, y="change_usd", color="change_usd", color_continuous_scale="RdYlGn_r",
                           labels={"change_usd": "Change (USD)"}), width="stretch")
else:
    cmp = pd.DataFrame()

# ------------------------------------------------------------------ export
st.subheader("Export")
label = "SIMULATED" if source == B.SRC_SIM else "FLOCI_API"
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("README.txt", f"Data source: {label}\nPeriod: {start} to {end}\n"
               + ("Simulated billing records, NOT actual AWS expenditure.\n" if source == B.SRC_SIM else ""))
    for name, frame in [("filtered_records", df), ("monthly_by_service", B.monthly(df, "service")),
                        ("service_breakdown", svc), ("region_breakdown", reg), ("daily_trend", d),
                        ("period_comparison", cmp)]:
        z.writestr(f"{name}.csv", frame.to_csv(index=False))
c1, c2 = st.columns(2)
c1.download_button("Download cost report (ZIP of CSVs)", buf.getvalue(), f"cost_report_{label.lower()}.zip",
                   mime="application/zip", icon=":material/folder_zip:", type="primary")
with c2:
    ui.download_csv(df, f"cost_records_{label.lower()}.csv", "Download filtered records (CSV)")
