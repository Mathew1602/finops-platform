"""Module 1: retrieve, normalise, cache and look up cloud service prices.

Price sources, in priority order:
  1. floci_api: Floci Pricing API (`get_products`)
  2. reference_assumption: data/reference/*.{csv,yaml}, hand-documented list prices
  3. region_derived: a us-east-1 price x REGION_PRICE_MULTIPLIER

All of them are normalised into one "catalog" DataFrame with the columns in
CATALOG_COLUMNS, so the Cost Estimator and Pricing Comparison need only one
lookup function: `get_price()`.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

from finops import assumptions as A
from finops.aws_client import get_client

CATALOG_COLUMNS = ["service", "product", "variant", "region", "term",
                   "unit", "price_usd", "source", "description"]

SRC_API = "floci_api"
SRC_REF = "reference_assumption"
SRC_DERIVED = "region_derived"

TERM_OD = "OnDemand"
TERM_RI_1YR = "Reserved-1yr"
TERM_SPOT = "Spot"

# Services from the project brief, mapped to AWS Pricing service codes.
SERVICE_CATALOG = {
    "Compute": {"EC2": "AmazonEC2", "Lambda": "AWSLambda", "ECS (Fargate)": "AmazonECS", "EKS": "AmazonEKS"},
    "Storage": {"S3": "AmazonS3", "EBS": "AmazonEBS", "EFS": "AmazonEFS"},
    "Databases": {"DynamoDB": "AmazonDynamoDB", "RDS": "AmazonRDS", "ElastiCache": "AmazonElastiCache"},
    "Networking": {"CloudFront": "AmazonCloudFront", "Route 53": "AmazonRoute53", "ELB": "AWSELB"},
    "Messaging": {"SQS": "AmazonSQS", "SNS": "AmazonSNS"},
    "Analytics": {"Athena": "AmazonAthena", "Glue": "AWSGlue"},
    "Backup / Monitoring": {"AWS Backup": "AWSBackup", "CloudWatch": "AmazonCloudWatch"},
}
SERVICE_CODES = {name: code for group in SERVICE_CATALOG.values() for name, code in group.items()}

# Floci S3 storageClass attribute -> reference catalog product key
_S3_CLASS_MAP = {
    "General Purpose": "STANDARD",
    "Infrequent Access": "STANDARD_IA",
    "Archive": "GLACIER",
    "Intelligent-Tiering": "INTELLIGENT_TIERING",
}
_LAMBDA_GROUP_MAP = {
    "AWS-Lambda-Requests": ("requests", "default"),
    "AWS-Lambda-Duration": ("compute", "default"),
}


@dataclass(frozen=True)
class PriceQuote:
    price: float
    unit: str
    source: str
    description: str
    region: str

    def label(self) -> str:
        return f"${self.price:,.6g}/{self.unit} ({self.source})"


# ============================================================ Floci Pricing API

def list_api_services() -> pd.DataFrame:
    """Services and filterable attributes that the Floci Pricing API exposes."""
    client = get_client("pricing")
    rows, token = [], None
    while True:
        kw = {"MaxResults": 100, **({"NextToken": token} if token else {})}
        resp = client.describe_services(**kw)
        for svc in resp.get("Services", []):
            rows.append({"service_code": svc["ServiceCode"], "attributes": svc.get("AttributeNames", [])})
        token = resp.get("NextToken")
        if not token:
            break
    return pd.DataFrame(rows)


def get_attribute_values(service_code: str, attribute: str) -> list[str]:
    client = get_client("pricing")
    values, token = [], None
    while True:
        kw = {"ServiceCode": service_code, "AttributeName": attribute, "MaxResults": 100,
              **({"NextToken": token} if token else {})}
        resp = client.get_attribute_values(**kw)
        values += [v["Value"] for v in resp.get("AttributeValues", [])]
        token = resp.get("NextToken")
        if not token:
            break
    return values


def get_products(service_code: str, filters: dict[str, str] | None = None) -> list[dict]:
    """Return parsed price-list documents (paginated) from Floci."""
    client = get_client("pricing")
    api_filters = [{"Type": "TERM_MATCH", "Field": k, "Value": v} for k, v in (filters or {}).items() if v]
    items, token = [], None
    while True:
        kw = {"ServiceCode": service_code, "Filters": api_filters, "MaxResults": 100,
              **({"NextToken": token} if token else {})}
        resp = client.get_products(**kw)
        items += [json.loads(p) if isinstance(p, str) else p for p in resp.get("PriceList", [])]
        token = resp.get("NextToken")
        if not token:
            break
    return items


def _term_name(term_type: str, attrs: dict) -> str:
    if term_type == "OnDemand":
        return TERM_OD
    lease = attrs.get("LeaseContractLength", "")
    option = attrs.get("PurchaseOption", "")
    return f"Reserved-{lease}-{option}".replace(" ", "")


def flatten_price_list(items: list[dict]) -> pd.DataFrame:
    """Flatten Pricing API documents into one row per price dimension.

    For Reserved terms, the upfront fee (unit "Quantity") is amortised over the
    lease into `effective_hourly`, so it can be compared with On-Demand.
    """
    rows = []
    for doc in items:
        product = doc.get("product", {})
        attrs = product.get("attributes", {})
        for term_type, terms in doc.get("terms", {}).items():
            for term in terms.values():
                term_attrs = term.get("termAttributes", {})
                dims = list(term.get("priceDimensions", {}).values())
                upfront = sum(float(d["pricePerUnit"].get("USD", 0)) for d in dims if d.get("unit") == "Quantity")
                years = 3 if "3" in term_attrs.get("LeaseContractLength", "") else 1
                for dim in dims:
                    if dim.get("unit") == "Quantity":
                        continue
                    price = float(dim["pricePerUnit"].get("USD", 0))
                    eff = price + (upfront / (years * A.HOURS_PER_YEAR) if upfront and dim.get("unit") == "Hrs" else 0)
                    rows.append({
                        "sku": product.get("sku"),
                        "product_family": product.get("productFamily"),
                        "region": attrs.get("regionCode") or A.LOCATION_TO_REGION.get(attrs.get("location"), ""),
                        "term": _term_name(term_type, term_attrs),
                        "unit": dim.get("unit"),
                        "price_usd": price,
                        "upfront_usd": upfront,
                        "effective_hourly": eff if dim.get("unit") == "Hrs" else None,
                        "begin_range": dim.get("beginRange"),
                        "end_range": dim.get("endRange"),
                        "description": dim.get("description"),
                        **{f"attr.{k}": v for k, v in attrs.items()},
                        "source": SRC_API,
                    })
    return pd.DataFrame(rows)


def _api_rows_to_catalog(service_code: str, flat: pd.DataFrame) -> list[dict]:
    """Map flattened API rows onto catalog keys (service/product/variant)."""
    out = []
    for _, r in flat.iterrows():
        product = variant = None
        if service_code == "AmazonEC2" and r.get("attr.instanceType"):
            product, variant = r["attr.instanceType"], r.get("attr.operatingSystem", "Linux")
        elif service_code == "AmazonS3" and r.get("attr.storageClass") in _S3_CLASS_MAP:
            if str(r.get("attr.usagetype", "")).startswith("TimedStorage") or r["unit"] == "GB-Mo":
                product, variant = _S3_CLASS_MAP[r["attr.storageClass"]], "storage"
        elif service_code == "AWSLambda" and r.get("attr.group") in _LAMBDA_GROUP_MAP:
            product, variant = _LAMBDA_GROUP_MAP[r["attr.group"]]
        if product is None:
            continue
        # Tiered prices: keep only the first tier (begin_range 0) for the catalog.
        if str(r.get("begin_range", "0")) not in ("0", "0.0", "None", "nan"):
            continue
        out.append({
            "service": service_code, "product": product, "variant": variant,
            "region": r["region"] or A.BASE_REGION,
            "term": TERM_RI_1YR if r["term"] == "Reserved-1yr-NoUpfront" else r["term"], "unit": r["unit"],
            "price_usd": r["effective_hourly"] if pd.notna(r.get("effective_hourly")) else r["price_usd"],
            "source": SRC_API, "description": r["description"],
        })
    return out


def fetch_api_catalog() -> pd.DataFrame:
    """Everything the Floci Pricing API offers, mapped to catalog rows."""
    rows = []
    for code in list_api_services()["service_code"]:
        flat = flatten_price_list(get_products(code))
        if not flat.empty:
            rows += _api_rows_to_catalog(code, flat)
    return pd.DataFrame(rows, columns=CATALOG_COLUMNS)


# ============================================================ reference data

def _clean_price(value) -> float | None:
    """'$0.0104 hourly' -> 0.0104 ; 'unavailable' -> None (from ec2-eda-dashboard)."""
    if pd.isna(value):
        return None
    value = str(value)
    if "unavailable" in value.lower():
        return None
    try:
        return float(value.replace("$", "").replace("hourly", "").strip())
    except ValueError:
        return None


def load_ec2_reference() -> pd.DataFrame:
    """EC2 instance specs and prices from the course dataset (us-east-1)."""
    df = pd.read_csv(A.REFERENCE_DIR / "ec2_instances.csv")
    out = pd.DataFrame({
        "instance_type": df["API Name"],
        "name": df["Name"],
        "vcpus": df["vCPUs"].str.extract(r"(\d+)", expand=False).astype(float),
        "memory_gib": df["Instance Memory"].str.extract(r"([\d.]+)", expand=False).astype(float),
        "network": df["Network Performance"],
        "od_linux": df["On Demand"].map(_clean_price),
        "ri_linux": df["Linux Reserved cost"].map(_clean_price),
        "spot_linux": df["Linux Spot Minimum cost"].map(_clean_price),
        "od_windows": df["Windows On Demand cost"].map(_clean_price),
        "ri_windows": df["Windows Reserved cost"].map(_clean_price),
    })
    out["family"] = out["instance_type"].str.split(".").str[0]
    return out.dropna(subset=["od_linux"]).reset_index(drop=True)


def _reference_catalog() -> pd.DataFrame:
    rows = []
    desc = "ec2_instances.csv course dataset"
    for _, r in load_ec2_reference().iterrows():
        for os_name, od, ri, spot in [("Linux", r.od_linux, r.ri_linux, r.spot_linux),
                                      ("Windows", r.od_windows, r.ri_windows, None)]:
            for term, price in [(TERM_OD, od), (TERM_RI_1YR, ri), (TERM_SPOT, spot)]:
                if price is not None and pd.notna(price):
                    rows.append(["AmazonEC2", r.instance_type, os_name, A.BASE_REGION, term,
                                 "Hrs", price, SRC_REF, f"{term} {os_name} {r.instance_type} ({desc})"])
    ref = yaml.safe_load((A.REFERENCE_DIR / "reference_prices.yaml").read_text())
    for service, products in ref.items():
        for product, variants in products.items():
            for variant, info in variants.items():
                rows.append([service, product, variant, A.BASE_REGION, TERM_OD,
                             info["unit"], float(info["price"]), SRC_REF, info["description"]])
    return pd.DataFrame(rows, columns=CATALOG_COLUMNS)


def build_catalog(use_api: bool = True) -> tuple[pd.DataFrame, str | None]:
    """Merged catalog, preferring Floci API prices over reference prices.

    Returns (catalog, api_error). api_error is None when Floci answered.
    """
    frames, api_error = [], None
    if use_api:
        try:
            frames.append(fetch_api_catalog())
        except Exception as exc:  # noqa: BLE001
            api_error = str(exc)
    frames.append(_reference_catalog())
    cat = pd.concat([f for f in frames if not f.empty], ignore_index=True)
    cat["_prio"] = (cat["source"] != SRC_API).astype(int)
    key = ["service", "product", "variant", "region", "term"]
    cat = cat.sort_values("_prio").drop_duplicates(key).drop(columns="_prio")
    return cat.reset_index(drop=True), api_error


def get_price(catalog: pd.DataFrame, service: str, product: str, variant: str = "default",
              term: str = TERM_OD, region: str = A.BASE_REGION) -> PriceQuote | None:
    """Look up one rate. Falls back to the us-east-1 rate x region multiplier."""
    m = catalog[(catalog.service == service) & (catalog["product"] == product)
                & (catalog.variant == variant) & (catalog.term == term)]
    if m.empty:
        return None
    exact = m[m.region == region]
    if not exact.empty:
        r = exact.iloc[0]
        return PriceQuote(float(r.price_usd), r.unit, r.source, r.description, region)
    base = m[m.region == A.BASE_REGION]
    if base.empty:
        return None
    r = base.iloc[0]
    mult = A.REGION_PRICE_MULTIPLIER.get(region, 1.0)
    return PriceQuote(float(r.price_usd) * mult, r.unit, SRC_DERIVED,
                      f"{r.description} (us-east-1 x {mult:.2f} {region} multiplier, base from {r.source})",
                      region)


def catalog_for_region(catalog: pd.DataFrame, service: str, region: str) -> pd.DataFrame:
    """All catalog rows for a service, priced for `region`."""
    rows = []
    sub = catalog[catalog.service == service]
    for (product, variant, term), _ in sub.groupby(["product", "variant", "term"]):
        q = get_price(catalog, service, product, variant, term, region)
        if q:
            rows.append({"service": service, "product": product, "variant": variant, "term": term,
                         "region": region, "unit": q.unit, "price_usd": q.price,
                         "source": q.source, "description": q.description})
    return pd.DataFrame(rows)


# ============================================================ local cache

def save_to_cache(df: pd.DataFrame, name: str) -> str:
    """Persist retrieved prices for later analysis. Returns the file path."""
    A.PRICING_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = A.PRICING_CACHE_DIR / f"{name}_{stamp}.csv"
    df.assign(retrieved_at=dt.datetime.now().isoformat(timespec="seconds")).to_csv(path, index=False)
    return str(path)


def load_cache(filename: str) -> pd.DataFrame:
    """Read back a price file written by `save_to_cache`."""
    return pd.read_csv(A.PRICING_CACHE_DIR / Path(filename).name)


def delete_cache(filename: str) -> None:
    (A.PRICING_CACHE_DIR / Path(filename).name).unlink(missing_ok=True)


def list_cache() -> pd.DataFrame:
    files = sorted(A.PRICING_CACHE_DIR.glob("*.csv"), reverse=True)
    return pd.DataFrame([{"file": f.name, "size_kb": round(f.stat().st_size / 1024, 1),
                          "modified": dt.datetime.fromtimestamp(f.stat().st_mtime)} for f in files])
