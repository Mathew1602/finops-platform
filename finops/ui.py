"""Shared Streamlit helpers: data-source labels, cached loaders, downloads."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from finops import assumptions as A
from finops import pricing as P
from finops.aws_client import FLOCI_ENDPOINT

SOURCE_STYLE = {
    P.SRC_API: ("Floci API (actual response)", "green"),
    P.SRC_REF: ("Reference price / documented assumption", "orange"),
    P.SRC_DERIVED: ("Region-derived from us-east-1", "violet"),
    "simulated": ("SIMULATED data (not actual AWS spend)", "red"),
    "user_defined": ("User-defined hypothetical configuration", "blue"),
}


def page_setup(title: str, icon: str = ":material/cloud:") -> None:
    st.set_page_config(page_title=f"{title} | Cloud FinOps", page_icon=icon, layout="wide")
    sidebar_status()


def source_badges(sources) -> None:
    """Show one coloured badge per data source present in `sources`."""
    if isinstance(sources, pd.DataFrame):
        sources = sources["source"].dropna().unique() if "source" in sources else []
    cols = st.columns(max(len(sources), 1))
    for col, src in zip(cols, sorted(set(sources))):
        label, color = SOURCE_STYLE.get(src, (src, "gray"))
        with col:
            st.badge(label, color=color)


def money(x: float, decimals: int = 2) -> str:
    return f"${x:,.{decimals}f}"


@st.cache_data(ttl=60, show_spinner=False)
def floci_status() -> bool:
    from finops.capabilities import floci_reachable
    return floci_reachable()


@st.cache_data(ttl=300, show_spinner="Loading price catalog...")
def _catalog(use_api: bool):
    return P.build_catalog(use_api=use_api)


def get_catalog(use_api: bool = True):
    """(catalog, api_error). Cached per Floci state, so it refreshes when Floci goes up or down."""
    online = use_api and floci_status()
    catalog, err = _catalog(online)
    if use_api and not online and err is None:
        err = "Floci endpoint unreachable"
    return catalog, err


def sidebar_status() -> None:
    with st.sidebar:
        ok = floci_status()
        st.caption(f"Floci endpoint: `{FLOCI_ENDPOINT}`")
        if ok:
            st.success("Floci reachable", icon=":material/check_circle:")
        else:
            st.warning("Floci offline: using reference / simulated data", icon=":material/cloud_off:")
        if st.button("Refresh data caches", width="stretch"):
            st.cache_data.clear()
            st.rerun()


def download_csv(df: pd.DataFrame, filename: str, label: str = "Download CSV", key: str | None = None) -> None:
    st.download_button(label, df.to_csv(index=False).encode(), file_name=filename,
                       mime="text/csv", icon=":material/download:", key=key)


def assumptions_panel(extra: dict | None = None, expanded: bool = False) -> None:
    with st.expander("Assumptions and exclusions", expanded=expanded, icon=":material/info:"):
        rows = {**A.GENERAL_ASSUMPTIONS, **(extra or {})}
        st.table(pd.DataFrame({"Assumption": rows.keys(), "Value": rows.values()}))
        st.markdown("**Region multipliers (applied to us-east-1 base prices):**")
        st.dataframe(pd.DataFrame(A.REGION_PRICE_MULTIPLIER.items(), columns=["Region", "Multiplier"]),
                     hide_index=True)
        st.markdown("**Excluded from estimates:**\n" + "\n".join(f"- {e}" for e in A.EXCLUSIONS))
        st.caption("An estimate is not an AWS bill. Data transfer, requests, taxes, discounts and "
                   "commitments can change the final amount.")
