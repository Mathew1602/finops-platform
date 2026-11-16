"""Module 1: Cloud Service Pricing Explorer."""

import json

import plotly.express as px
import streamlit as st

from finops import assumptions as A
from finops import pricing as P
from finops import ui

ui.page_setup("Pricing Explorer", ":material/sell:")
st.title("Cloud Service Pricing Explorer")
st.caption("Module 1: retrieve prices through the Floci Pricing API (boto3 `pricing` client), "
           "explore them by service and region, and store them for later analysis.")

region = st.sidebar.selectbox("Region", list(A.REGIONS), format_func=lambda r: f"{r} ({A.REGIONS[r]})")
catalog, api_err = ui.get_catalog()

tab_api, tab_cat, tab_cache = st.tabs([":material/api: Floci Pricing API (live)",
                                       ":material/menu_book: Service price catalog",
                                       ":material/folder: Saved price data"])

# ------------------------------------------------------------------ live API
with tab_api:
    st.subheader("Query the Floci Pricing API")
    try:
        services = P.list_api_services()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not reach the Floci Pricing API: {exc}")
        services = None

    if services is not None and not services.empty:
        st.info(f"Floci exposes **{len(services)}** service codes through `describe_services`: "
                + ", ".join(f"`{s}`" for s in services.service_code), icon=":material/info:")
        code = st.selectbox("Service code", services.service_code)
        attrs = services.set_index("service_code").loc[code, "attributes"]

        st.markdown("**Filters** (`get_attribute_values` → `TERM_MATCH`)")
        filters = {}
        cols = st.columns(min(len(attrs), 4) or 1)
        for i, attr in enumerate(attrs):
            try:
                values = P.get_attribute_values(code, attr)
            except Exception:  # noqa: BLE001
                values = []
            default = A.REGIONS[region] if attr == "location" and A.REGIONS[region] in values else "Any"
            opts = ["Any"] + values
            choice = cols[i % len(cols)].selectbox(attr, opts, index=opts.index(default), key=f"f_{code}_{attr}")
            if choice != "Any":
                filters[attr] = choice

        if st.button("Retrieve prices", type="primary", icon=":material/download:"):
            with st.spinner("Calling get_products..."):
                items = P.get_products(code, filters)
            st.session_state["api_items"] = items
            st.session_state["api_flat"] = P.flatten_price_list(items)
            st.session_state["api_query"] = (code, filters)

        flat = st.session_state.get("api_flat")
        if flat is not None and st.session_state.get("api_query", (None,))[0] == code:
            used = st.session_state["api_query"][1]
            if used != filters:
                st.info("The filters changed after these prices were retrieved. Showing results for: "
                        + (", ".join(f"{k} = {v}" for k, v in used.items()) or "no filters")
                        + ". Click **Retrieve prices** to update.", icon=":material/sync_problem:")
            if flat.empty:
                st.warning("Floci returned **no price items** for these filters. Floci only seeds a "
                           "small set of SKUs; use the *Service price catalog* tab for reference prices.")
            else:
                ui.source_badges(flat)
                show = ["sku", "region", "term", "unit", "price_usd", "description"] + \
                       [c for c in flat.columns if c.startswith("attr.")]
                st.dataframe(flat[show], hide_index=True, width="stretch")
                label_col = next((c for c in ["attr.instanceType", "attr.storageClass", "attr.group"]
                                  if c in flat), "sku")
                st.plotly_chart(px.bar(flat, x=label_col, y="price_usd", color="term",
                                       title=f"{code} prices returned by Floci",
                                       labels={"price_usd": "USD per unit"}), width="stretch")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Save to local price cache", icon=":material/save:"):
                        st.success(f"Saved {P.save_to_cache(flat, f'api_{code}')}")
                with c2:
                    ui.download_csv(flat, f"floci_prices_{code}.csv")
                with st.expander("Raw API response (PriceList JSON)"):
                    st.code(json.dumps(st.session_state["api_items"], indent=1)[:20000], language="json")

# ------------------------------------------------------------------ catalog
with tab_cat:
    st.subheader("Browse prices by service")
    if api_err:
        st.warning(f"Floci unavailable, showing reference prices only. ({api_err[:100]})")
    c1, c2 = st.columns(2)
    category = c1.selectbox("Category", list(P.SERVICE_CATALOG))
    svc_name = c2.selectbox("Service", list(P.SERVICE_CATALOG[category]))
    code = P.SERVICE_CODES[svc_name]
    df = P.catalog_for_region(catalog, code, region)

    if df.empty:
        st.info("No pricing data available for this service.")
    else:
        if code == "AmazonEC2":
            specs = P.load_ec2_reference()[["instance_type", "family", "vcpus", "memory_gib"]]
            df = df.merge(specs, left_on="product", right_on="instance_type", how="left").drop(columns="instance_type")
            f1, f2, f3, f4 = st.columns(4)
            fams = sorted(df.family.dropna().unique())
            fam = f1.multiselect("Family", fams, default=[f for f in ["t3", "m5", "c5", "r5"] if f in fams])
            os_ = f2.selectbox("Operating system", sorted(df.variant.unique()))
            terms = f3.multiselect("Pricing term", sorted(df.term.unique()), default=[P.TERM_OD])
            max_vcpu = f4.slider("Max vCPUs", 1, int(df.vcpus.max()), 16)
            df = df[(df.family.isin(fam) if fam else True) & (df.variant == os_) &
                    (df.term.isin(terms)) & (df.vcpus <= max_vcpu)].copy()
            df["monthly_usd"] = df.price_usd * A.HOURS_PER_MONTH
        ui.source_badges(df)
        st.dataframe(df, hide_index=True, width="stretch",
                     column_config={"price_usd": st.column_config.NumberColumn("Price (USD)", format="$%.5f"),
                                    "monthly_usd": st.column_config.NumberColumn("Monthly @730h", format="$%.2f")})
        if code == "AmazonEC2" and not df.empty:
            top = df.sort_values("price_usd").head(40)
            st.plotly_chart(px.bar(top, x="product", y="price_usd", color="term", barmode="group",
                                   hover_data=["vcpus", "memory_gib", "source"],
                                   title=f"EC2 hourly price ({os_}, {region})",
                                   labels={"price_usd": "USD/hour", "product": "Instance type"}),
                            width="stretch")
            st.plotly_chart(px.scatter(df[df.term == P.TERM_OD] if P.TERM_OD in terms else df,
                                       x="vcpus", y="price_usd", size="memory_gib", color="family",
                                       hover_name="product", title="Price vs vCPU (bubble = memory GiB)"),
                            width="stretch")
        elif not df.empty:
            st.plotly_chart(px.bar(df, x="product", y="price_usd", color="variant", hover_data=["unit", "source"],
                                   title=f"{svc_name} prices ({region})", labels={"price_usd": "USD per unit"}),
                            width="stretch")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Save to local price cache", key="save_cat", icon=":material/save:"):
                st.success(f"Saved {P.save_to_cache(df, f'catalog_{code}_{region}')}")
        with c2:
            ui.download_csv(df, f"prices_{code}_{region}.csv", key="dl_cat")
    st.caption("Non-us-east-1 prices are derived with documented region multipliers (see Cost Estimator "
               "assumptions). Reference prices approximate AWS public list prices; they are not API data.")

# ------------------------------------------------------------------ cache
with tab_cache:
    st.subheader("Stored price data")
    cache = P.list_cache()
    if cache.empty:
        st.info("Nothing saved yet. Use *Save to local price cache* on the other tabs.")
    else:
        st.dataframe(cache, hide_index=True, width="stretch")
        chosen = st.selectbox("Open a saved file", cache.file)
        saved = P.load_cache(chosen)
        ui.source_badges(saved)
        st.dataframe(saved, hide_index=True, width="stretch")
        c1, c2 = st.columns(2)
        with c1:
            ui.download_csv(saved, chosen, key="dl_saved")
        if c2.button("Delete this file", icon=":material/delete:"):
            P.delete_cache(chosen)
            st.rerun()
    st.caption("Saved files are snapshots for later analysis. The Cost Estimator and Pricing Comparison "
               "always use the live merged catalog below, not these files.")
    st.markdown("**Full merged catalog used by the Cost Estimator**")
    st.dataframe(catalog.source.value_counts().rename_axis("source").reset_index(name="price rows"),
                 hide_index=True)
    ui.download_csv(catalog, "price_catalog_full.csv", key="dl_full")
