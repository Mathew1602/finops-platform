"""Module 4: infrastructure cost estimation from a Module 3 scenario.

Each resource produces one or more line items (compute, storage, requests...).
Monthly cost is calculated from the unit price and usage; the other periods
are derived from it:
    hourly = monthly / 730    daily = monthly / 30.42    annual = monthly x 12
"""

from __future__ import annotations

import pandas as pd

from finops import assumptions as A
from finops import pricing as P

LINE_COLUMNS = ["resource", "resource_type", "service", "department", "component", "quantity",
                "unit", "unit_price", "monthly_usd", "price_source", "formula"]


class _Lines:
    def __init__(self, catalog: pd.DataFrame, region: str):
        self.catalog, self.region, self.rows, self.missing = catalog, region, [], []

    def add(self, row: dict, rtype: str, service_label: str, component: str, service_code: str,
            product: str, variant: str, quantity: float, formula: str, multiplier: float = 1.0) -> None:
        q = P.get_price(self.catalog, service_code, product, variant, P.TERM_OD, self.region)
        if q is None:
            self.missing.append(f"{service_code} {product}/{variant}")
            price, unit, source = 0.0, "?", "missing"
        else:
            price, unit, source = q.price, q.unit, q.source
        self.rows.append({
            "resource": row["name"], "resource_type": rtype, "service": service_label,
            "department": row.get("department", ""), "component": component,
            "quantity": quantity, "unit": unit, "unit_price": price,
            "monthly_usd": quantity * price * multiplier, "price_source": source,
            "formula": formula.format(q=quantity, p=price, m=multiplier, u=unit),
        })


def estimate(scenario: dict, catalog: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Return (line items, list of resources with no price found)."""
    L = _Lines(catalog, scenario.get("region", A.BASE_REGION))
    res = scenario["resources"]

    for r in res.get("ec2", []):
        hrs = r["count"] * r["hours_per_month"]
        L.add(r, "ec2", "EC2", f"Compute {r['instance_type']} {r['os']}", "AmazonEC2",
              r["instance_type"], r["os"], hrs,
              f"{r['count']} inst x {r['hours_per_month']} h x ${{p:.4f}}/h")
        if r["ebs_gb"]:
            gb = r["count"] * r["ebs_gb"]
            L.add(r, "ec2", "EBS", f"EBS {r['ebs_type']}", "AmazonEBS", r["ebs_type"], "storage", gb,
                  f"{r['count']} x {r['ebs_gb']} GB x ${{p:.4f}}/GB-Mo")

    for r in res.get("s3", []):
        L.add(r, "s3", "S3", f"Storage {r['storage_class']}", "AmazonS3", r["storage_class"], "storage",
              r["storage_gb"], "{q:,.0f} GB x ${p:.5f}/GB-Mo")
        if r["put_requests_k"]:
            L.add(r, "s3", "S3", "PUT/LIST requests", "AmazonS3", "REQUESTS", "put", r["put_requests_k"],
                  "{q:,.0f}K requests x ${p}/1K")
        if r["get_requests_k"]:
            L.add(r, "s3", "S3", "GET requests", "AmazonS3", "REQUESTS", "get", r["get_requests_k"],
                  "{q:,.0f}K requests x ${p}/1K")
        if r["retrieval_gb"]:
            L.add(r, "s3", "S3", "Data retrieval", "AmazonS3", r["storage_class"], "retrieval", r["retrieval_gb"],
                  "{q:,.0f} GB x ${p}/GB")

    for r in res.get("rds", []):
        az = A.RDS_MULTI_AZ_FACTOR if r["multi_az"] else 1.0
        az_txt = " x 2 (Multi-AZ)" if r["multi_az"] else ""
        L.add(r, "rds", "RDS", f"Instance {r['instance_class']} {r['engine']}", "AmazonRDS",
              r["instance_class"], "MySQL", r["count"] * r["hours_per_month"],
              f"{r['count']} x {r['hours_per_month']} h x ${{p:.4f}}/h{az_txt}", az)
        L.add(r, "rds", "RDS", "Storage gp2", "AmazonRDS", "storage", "gp2", r["count"] * r["storage_gb"],
              f"{{q:,.0f}} GB x ${{p}}/GB-Mo{az_txt}", az)

    for r in res.get("dynamodb", []):
        if r["read_requests_m"]:
            L.add(r, "dynamodb", "DynamoDB", "Read request units", "AmazonDynamoDB", "on_demand", "read",
                  r["read_requests_m"], "{q:,.2f}M RRU x ${p}/M")
        if r["write_requests_m"]:
            L.add(r, "dynamodb", "DynamoDB", "Write request units", "AmazonDynamoDB", "on_demand", "write",
                  r["write_requests_m"], "{q:,.2f}M WRU x ${p}/M")
        if r["storage_gb"]:
            L.add(r, "dynamodb", "DynamoDB", "Storage", "AmazonDynamoDB", "storage", "default",
                  r["storage_gb"], "{q:,.1f} GB x ${p}/GB-Mo")

    for r in res.get("lambda", []):
        inv = r["invocations_m"] * 1_000_000
        gb_s = inv * (r["avg_duration_ms"] / 1000) * (r["memory_mb"] / 1024)
        L.add(r, "lambda", "Lambda", "Requests", "AWSLambda", "requests", "default", inv,
              "{q:,.0f} requests x ${p:.7f}")
        L.add(r, "lambda", "Lambda", "Compute (GB-s)", "AWSLambda", "compute", "default", gb_s,
              f"{inv:,.0f} x {r['avg_duration_ms']} ms x {r['memory_mb']} MB = {{q:,.0f}} GB-s x ${{p:.10f}}")

    for r in res.get("elb", []):
        hrs = r["count"] * r["hours_per_month"]
        L.add(r, "elb", "ELB", f"{r['lb_type'].title()} LB hours", "AWSELB", r["lb_type"], "hours", hrs,
              "{q:,.0f} h x ${p}/h")
        if r["avg_lcu"]:
            L.add(r, "elb", "ELB", "Capacity units", "AWSELB", r["lb_type"], "lcu", hrs * r["avg_lcu"],
                  f"{hrs:,.0f} h x {r['avg_lcu']} LCU x ${{p}}/LCU-h")

    for r in res.get("backup", []):
        L.add(r, "backup", "AWS Backup", f"Warm storage ({r['resource_type']})", "AWSBackup", "warm_storage",
              r["resource_type"], r["storage_gb"], "{q:,.0f} GB x ${p}/GB-Mo")

    df = pd.DataFrame(L.rows, columns=LINE_COLUMNS)
    if not df.empty:
        df = add_periods(df)
    return df, sorted(set(L.missing))


def add_periods(df: pd.DataFrame, monthly_col: str = "monthly_usd") -> pd.DataFrame:
    df = df.copy()
    df["hourly_usd"] = df[monthly_col] / A.HOURS_PER_MONTH
    df["daily_usd"] = df[monthly_col] / A.DAYS_PER_MONTH
    df["annual_usd"] = df[monthly_col] * A.MONTHS_PER_YEAR
    return df


def summarise(lines: pd.DataFrame, by: str) -> pd.DataFrame:
    cols = ["hourly_usd", "daily_usd", "monthly_usd", "annual_usd"]
    out = lines.groupby(by)[cols].sum().sort_values("monthly_usd", ascending=False).reset_index()
    out["share_pct"] = 100 * out.monthly_usd / out.monthly_usd.sum() if out.monthly_usd.sum() else 0
    return out


def totals(lines: pd.DataFrame) -> dict:
    m = float(lines.monthly_usd.sum()) if not lines.empty else 0.0
    return {"hourly": m / A.HOURS_PER_MONTH, "daily": m / A.DAYS_PER_MONTH, "monthly": m,
            "annual": m * A.MONTHS_PER_YEAR}
