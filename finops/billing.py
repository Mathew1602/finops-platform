"""Module 2: Cost Explorer data access, synthetic billing, and cost analysis.

Data sources:
  * floci_api  : Floci Cost Explorer `get_cost_and_usage` (actual API response)
  * simulated  : deterministic synthetic billing dataset (data/synthetic_billing.csv)

Floci emulates the Cost Explorer API but does not generate billing records
(every amount comes back $0). The project brief anticipates this, so the app
falls back to the synthetic dataset and labels it SIMULATED everywhere.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from finops import assumptions as A
from finops.aws_client import get_client

SRC_API = "floci_api"
SRC_SIM = "simulated"

# ============================================================ Floci Cost Explorer

def query_ce(start: dt.date, end: dt.date, granularity: str = "DAILY",
             group_by: tuple[str, ...] = ("SERVICE", "REGION"),
             metric: str = "UnblendedCost") -> pd.DataFrame:
    """Call get_cost_and_usage (paginated) and return tidy rows.

    Columns: date, <one column per group-by dimension, lowercased>, cost_usd, source
    """
    client = get_client("ce")
    kw = {"TimePeriod": {"Start": str(start), "End": str(end)}, "Granularity": granularity,
          "Metrics": [metric], "GroupBy": [{"Type": "DIMENSION", "Key": k} for k in group_by]}
    rows, token = [], None
    while True:
        resp = client.get_cost_and_usage(**kw, **({"NextPageToken": token} if token else {}))
        for period in resp.get("ResultsByTime", []):
            day = pd.to_datetime(period["TimePeriod"]["Start"][:10])
            for g in period.get("Groups", []):
                row = {"date": day, "cost_usd": float(g["Metrics"][metric]["Amount"])}
                row.update({k.lower(): v for k, v in zip(group_by, g["Keys"])})
                rows.append(row)
            if not period.get("Groups"):
                rows.append({"date": day, "cost_usd": float(period["Total"][metric]["Amount"])})
        token = resp.get("NextPageToken")
        if not token:
            break
    df = pd.DataFrame(rows)
    if not df.empty:
        df["source"] = SRC_API
    return df


def ce_has_data(df: pd.DataFrame) -> bool:
    """True when the API returned real (non-zero) cost records."""
    return not df.empty and float(df["cost_usd"].sum()) > 0


# ============================================================ synthetic billing
# Monthly spend per department at the END of the dataset. Total is about
# $5,600/month, over the company-wide $5,000 budget in the final-demo scenario.
DEPARTMENTS = {
    "Development": {
        "monthly": 950, "project": "DevPlatform", "account": "222222222222",
        "services": {"EC2": 0.75, "S3": 0.25},
        "regions": {"us-east-1": 1.0}, "envs": {"Development": 1.0},
        "weekend": 0.55,          # dev boxes idle at weekends (if scheduled)
    },
    "E-commerce": {
        "monthly": 2400, "project": "ECommerce", "account": "111111111111",
        "services": {"EC2": 0.45, "RDS": 0.30, "S3": 0.10, "ELB": 0.15},
        "regions": {"us-east-1": 0.7, "eu-west-1": 0.3}, "envs": {"Production": 0.85, "Staging": 0.15},
        "weekend": 1.15,          # shoppers peak at weekends
    },
    "Analytics": {
        "monthly": 1150, "project": "DataLake", "account": "333333333333",
        "services": {"EC2": 0.55, "S3": 0.25, "Athena": 0.20},
        "regions": {"us-west-2": 1.0}, "envs": {"Production": 0.7, "Development": 0.3},
        "weekend": 0.8,
    },
    "Customer Services": {
        "monthly": 500, "project": "SupportDesk", "account": "111111111111",
        "services": {"Lambda": 0.35, "DynamoDB": 0.45, "S3": 0.20},
        "regions": {"us-east-1": 1.0}, "envs": {"Production": 1.0},
        "weekend": 0.7,
    },
    "IT Operations": {
        "monthly": 600, "project": "Operations", "account": "111111111111",
        "services": {"CloudWatch": 0.40, "AWS Backup": 0.60},
        "regions": {"us-east-1": 1.0}, "envs": {"Production": 1.0},
        "weekend": 1.0,
    },
}

# Monthly growth per service. Storage and backup grow fastest (from the brief).
SERVICE_GROWTH = {"EC2": 0.025, "RDS": 0.02, "S3": 0.045, "ELB": 0.02, "Athena": 0.035,
                  "Lambda": 0.03, "DynamoDB": 0.03, "CloudWatch": 0.02, "AWS Backup": 0.06}

# (service code, usage type, unit price used to back out a usage quantity, unit)
SERVICE_USAGE = {
    "EC2": ("AmazonEC2", "BoxUsage:t3.medium", 0.0416, "Hrs"),
    "RDS": ("AmazonRDS", "InstanceUsage:db.t3.medium", 0.068, "Hrs"),
    "S3": ("AmazonS3", "TimedStorage-ByteHrs", 0.023 / A.DAYS_PER_MONTH, "GB-Day"),
    "ELB": ("AWSELB", "LoadBalancerUsage", 0.0225, "Hrs"),
    "Athena": ("AmazonAthena", "DataScannedInTB", 5.0, "TB"),
    "Lambda": ("AWSLambda", "Lambda-GB-Second", 0.0000166667, "GB-Second"),
    "DynamoDB": ("AmazonDynamoDB", "ReadRequestUnits", 0.125, "1M RRU"),
    "CloudWatch": ("AmazonCloudWatch", "MetricMonitorUsage", 0.30 / A.DAYS_PER_MONTH, "Metric-Day"),
    "AWS Backup": ("AWSBackup", "WarmStorage-ByteHrs", 0.05 / A.DAYS_PER_MONTH, "GB-Day"),
}


def default_period(today: dt.date | None = None) -> tuple[dt.date, dt.date]:
    """12 calendar months ending yesterday (current month is partial)."""
    today = today or dt.date.today()
    first_this_month = today.replace(day=1)
    start = (pd.Timestamp(first_this_month) - pd.DateOffset(months=11)).date()
    return start, today - dt.timedelta(days=1)


def generate_synthetic_billing(start: dt.date | None = None, end: dt.date | None = None,
                               seed: int = 42) -> pd.DataFrame:
    """Daily cost records per department x service x region x environment.

    Trend: each service grows at SERVICE_GROWTH per month, so spend at `end`
    equals the DEPARTMENTS monthly level. Noise: weekday pattern,
    lognormal day-to-day noise, and a few injected cost spikes (anomalies).
    """
    if start is None or end is None:
        start, end = default_period()
    rng = np.random.default_rng(seed)
    days = pd.date_range(start, end, freq="D")
    months_before_end = np.asarray((pd.Timestamp(end) - days).days) / A.DAYS_PER_MONTH
    weekend = np.asarray(days.dayofweek >= 5)

    frames = []
    for dept, cfg in DEPARTMENTS.items():
        weekday_factor = np.where(weekend, cfg["weekend"], 1.0)
        # Normalise so the average day matches monthly / days-per-month.
        weekday_factor = weekday_factor / (5 / 7 + 2 / 7 * cfg["weekend"])
        for svc, s_share in cfg["services"].items():
            level = cfg["monthly"] * s_share / (1 + SERVICE_GROWTH[svc]) ** months_before_end
            for region, r_share in cfg["regions"].items():
                for env, e_share in cfg["envs"].items():
                    noise = rng.lognormal(0, 0.06, len(days))
                    cost = level / A.DAYS_PER_MONTH * weekday_factor * noise * r_share * e_share
                    code, usage_type, unit_price, unit = SERVICE_USAGE[svc]
                    frames.append(pd.DataFrame({
                        "date": days, "account_id": cfg["account"], "department": dept,
                        "project": cfg["project"], "environment": env, "service": svc,
                        "service_code": code, "region": region, "usage_type": usage_type,
                        "usage_unit": unit, "cost_usd": cost,
                    }))
    df = pd.concat(frames, ignore_index=True)

    # Inject cost spikes: a runaway job, a promo, and a backup misconfiguration.
    spikes = [("Analytics", "Athena", 3.5), ("E-commerce", "EC2", 2.2), ("IT Operations", "AWS Backup", 2.8)]
    for dept, svc, factor in spikes:
        day = days[rng.integers(len(days) // 3, len(days) - 3)]
        mask = (df.department == dept) & (df.service == svc) & (df.date == day)
        df.loc[mask, "cost_usd"] *= factor

    unit_prices = {k: v[2] for k, v in SERVICE_USAGE.items()}
    df["usage_qty"] = (df.cost_usd / df.service.map(unit_prices)).round(3)
    df["cost_usd"] = df.cost_usd.round(4)
    df["source"] = SRC_SIM
    return df


def load_synthetic_billing(regenerate: bool = False) -> pd.DataFrame:
    """Load the saved synthetic dataset (generate + save it on first use)."""
    path = A.SYNTHETIC_BILLING_CSV
    if regenerate or not path.exists():
        df = generate_synthetic_billing()
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
    return pd.read_csv(path, parse_dates=["date"], dtype={"account_id": str})


# ============================================================ analysis helpers

def filter_period(df: pd.DataFrame, start, end) -> pd.DataFrame:
    return df[(df.date >= pd.Timestamp(start)) & (df.date <= pd.Timestamp(end))]


def monthly(df: pd.DataFrame, by: str | None = None) -> pd.DataFrame:
    keys = [df.date.dt.to_period("M").dt.to_timestamp().rename("month")] + ([df[by]] if by else [])
    return df.groupby(keys)["cost_usd"].sum().reset_index()


def by_dimension(df: pd.DataFrame, dim: str) -> pd.DataFrame:
    out = df.groupby(dim)["cost_usd"].sum().sort_values(ascending=False).reset_index()
    out["share_pct"] = 100 * out.cost_usd / out.cost_usd.sum() if out.cost_usd.sum() else 0
    return out


def daily(df: pd.DataFrame, window: int = 7) -> pd.DataFrame:
    d = df.groupby("date")["cost_usd"].sum().reset_index()
    d[f"{window}d_avg"] = d.cost_usd.rolling(window, min_periods=1).mean()
    return d


def compare_periods(df: pd.DataFrame, p1: tuple, p2: tuple, dim: str = "service") -> pd.DataFrame:
    """Cost per `dim` in period 1 vs period 2, sorted by largest increase."""
    a = filter_period(df, *p1).groupby(dim)["cost_usd"].sum().rename("period_1")
    b = filter_period(df, *p2).groupby(dim)["cost_usd"].sum().rename("period_2")
    out = pd.concat([a, b], axis=1).fillna(0)
    out["change_usd"] = out.period_2 - out.period_1
    out["change_pct"] = np.where(out.period_1 > 0, 100 * out.change_usd / out.period_1, np.nan)
    return out.sort_values("change_usd", ascending=False).reset_index()


def full_months(df: pd.DataFrame) -> list[pd.Timestamp]:
    """Months whose every day is present in the data."""
    m = df.groupby(df.date.dt.to_period("M"))["date"].nunique()
    return [p.to_timestamp() for p, n in m.items() if n == p.days_in_month]


def month_bounds(month: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    return month, month + pd.offsets.MonthEnd(0)


def insights(df: pd.DataFrame) -> dict:
    """Answers to the brief's example questions for the given data."""
    months = full_months(df)
    out = {"months_available": len(months)}
    svc = by_dimension(df, "service")
    reg = by_dimension(df, "region")
    out["top_service"] = (svc.iloc[0].service, svc.iloc[0].cost_usd) if not svc.empty else None
    out["top_region"] = (reg.iloc[0].region, reg.iloc[0].cost_usd) if not reg.empty else None
    if len(months) >= 2:
        last, prev = months[-1], months[-2]
        cmp = compare_periods(df, month_bounds(prev), month_bounds(last))
        out["last_month"] = (last, cmp.period_2.sum())
        out["prev_month"] = (prev, cmp.period_1.sum())
        out["mom_pct"] = 100 * (cmp.period_2.sum() / cmp.period_1.sum() - 1) if cmp.period_1.sum() else None
        out["increase_drivers"] = cmp[cmp.change_usd > 0].head(3)
        m = monthly(df)
        m = m[m.month.isin(months)]
        slope = np.polyfit(np.arange(len(m)), m.cost_usd, 1)[0] if len(m) >= 3 else 0
        out["trend_per_month"] = slope
    return out
