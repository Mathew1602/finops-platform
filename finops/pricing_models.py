"""Module 5: compare On-Demand, Reserved, Savings Plans, Spot and storage tiers.

Key idea: commitment models (Reserved, Savings Plans) bill every hour of the
term whether or not the instance runs. On-Demand and Spot bill only the hours
used. So the cheapest model depends on utilisation; `breakeven_utilisation`
shows where a commitment starts to pay off.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from finops import assumptions as A
from finops import pricing as P


@dataclass
class Model:
    name: str
    hourly_rate: float          # effective $/h per instance (upfront amortised)
    committed: bool             # bills all hours in the term regardless of use
    term_years: int
    upfront_per_unit: float
    source: str
    basis: str
    conditions: str


CONDITIONS = {
    "On-Demand": "No commitment; pay per second/hour used. Most flexible, highest unit price. "
                 "Best for short-lived, unpredictable or new workloads.",
    "Reserved 1yr (No Upfront)": "1-year commitment to a specific instance family, region and OS. "
                                 "Billed every hour of the term even if the instance is stopped.",
    "Reserved 3yr (All Upfront)": "3-year commitment paid upfront. Largest discount, but capital is locked in and "
                                  "the configuration may become obsolete.",
    "Savings Plan 1yr (Compute)": "Commit to a $/hour spend for 1 year. Applies across instance families, sizes, "
                                  "regions and Fargate/Lambda, so it is more flexible than RIs.",
    "Savings Plan 3yr (Compute)": "As the 1-year plan, with a deeper discount for a 3-year term.",
    "Spot": "Uses spare capacity; AWS can interrupt with 2 minutes' notice. Only for fault-tolerant, "
            "stateless, flexible workloads (batch, CI, analytics). Price fluctuates.",
}


def ec2_models(catalog: pd.DataFrame, instance_type: str, os_name: str, region: str) -> list[Model]:
    od = P.get_price(catalog, "AmazonEC2", instance_type, os_name, P.TERM_OD, region)
    if od is None:
        return []
    models = [Model("On-Demand", od.price, False, 1, 0.0, od.source, od.description, CONDITIONS["On-Demand"])]

    ri = P.get_price(catalog, "AmazonEC2", instance_type, os_name, P.TERM_RI_1YR, region)
    if ri:
        models.append(Model("Reserved 1yr (No Upfront)", ri.price, True, 1, 0.0, ri.source,
                            ri.description, CONDITIONS["Reserved 1yr (No Upfront)"]))
    else:
        d = A.RESERVED_1YR_NO_UPFRONT_DISCOUNT
        models.append(Model("Reserved 1yr (No Upfront)", od.price * (1 - d), True, 1, 0.0, P.SRC_REF,
                            f"On-Demand x (1 - {d:.0%}) assumed discount", CONDITIONS["Reserved 1yr (No Upfront)"]))

    d3 = A.RESERVED_3YR_ALL_UPFRONT_DISCOUNT
    rate3 = od.price * (1 - d3)
    models.append(Model("Reserved 3yr (All Upfront)", rate3, True, 3, rate3 * A.HOURS_PER_YEAR * 3, P.SRC_REF,
                        f"On-Demand x (1 - {d3:.0%}) assumed; upfront = rate x 26,280 h",
                        CONDITIONS["Reserved 3yr (All Upfront)"]))
    for years, d in [(1, A.SAVINGS_PLAN_1YR_DISCOUNT), (3, A.SAVINGS_PLAN_3YR_DISCOUNT)]:
        name = f"Savings Plan {years}yr (Compute)"
        models.append(Model(name, od.price * (1 - d), True, years, 0.0, P.SRC_REF,
                            f"On-Demand x (1 - {d:.0%}) assumed discount", CONDITIONS[name]))

    spot = P.get_price(catalog, "AmazonEC2", instance_type, os_name, P.TERM_SPOT, region)
    if spot:
        models.append(Model("Spot", spot.price, False, 1, 0.0, spot.source,
                            spot.description + " (minimum observed spot price)", CONDITIONS["Spot"]))
    else:
        d = A.SPOT_DEFAULT_DISCOUNT
        models.append(Model("Spot", od.price * (1 - d), False, 1, 0.0, P.SRC_REF,
                            f"On-Demand x (1 - {d:.0%}) assumed discount", CONDITIONS["Spot"]))
    return models


def rds_models(catalog: pd.DataFrame, instance_class: str, multi_az: bool, region: str) -> list[Model]:
    od = P.get_price(catalog, "AmazonRDS", instance_class, "MySQL", P.TERM_OD, region)
    if od is None:
        return []
    f = A.RDS_MULTI_AZ_FACTOR if multi_az else 1.0
    d = A.RDS_RESERVED_1YR_DISCOUNT
    return [
        Model("On-Demand", od.price * f, False, 1, 0.0, od.source, od.description, CONDITIONS["On-Demand"]),
        Model("Reserved 1yr (No Upfront)", od.price * f * (1 - d), True, 1, 0.0, P.SRC_REF,
              f"On-Demand x (1 - {d:.0%}) assumed discount",
              "1-year DB instance reservation; billed every hour of the term. Spot and Savings Plans "
              "do not apply to RDS."),
    ]


def compare(models: list[Model], count: int, utilisation: float = 1.0, months: int = 12) -> pd.DataFrame:
    """Cost of running `count` units for `months` at `utilisation` (0-1) under each model."""
    if not models:
        return pd.DataFrame()
    used_hours = A.HOURS_PER_MONTH * utilisation
    rows = []
    for m in models:
        billed = A.HOURS_PER_MONTH if m.committed else used_hours
        monthly = m.hourly_rate * billed * count
        rows.append({"model": m.name, "effective_hourly": m.hourly_rate, "billed_hours_month": billed,
                     "monthly_usd": monthly, "annual_usd": monthly * A.MONTHS_PER_YEAR,
                     "period_usd": monthly * months, "upfront_usd": m.upfront_per_unit * count,
                     "term_years": m.term_years, "committed": m.committed, "source": m.source,
                     "basis": m.basis, "conditions": m.conditions})
    df = pd.DataFrame(rows)
    od = df.loc[df.model == "On-Demand", "monthly_usd"].iloc[0]
    df["savings_month_usd"] = (od - df.monthly_usd).round(6)
    df["savings_annual_usd"] = df.savings_month_usd * A.MONTHS_PER_YEAR
    df["savings_pct"] = 100 * df.savings_month_usd / od if od else 0.0
    od_rate = models[0].hourly_rate
    df["breakeven_utilisation_pct"] = [100 * m.hourly_rate / od_rate if m.committed and od_rate else None
                                       for m in models]
    return df


def utilisation_curve(models: list[Model], count: int, steps: int = 21) -> pd.DataFrame:
    rows = []
    for i in range(steps):
        u = i / (steps - 1)
        for _, r in compare(models, count, u).iterrows():
            rows.append({"utilisation_pct": u * 100, "model": r.model, "monthly_usd": r.monthly_usd})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ storage tiers
S3_TIERS = {
    "STANDARD": ("S3 Standard", "milliseconds", 0, "Frequently accessed data"),
    "INTELLIGENT_TIERING": ("S3 Intelligent-Tiering", "milliseconds", 0,
                            "Unknown/changing access; monitoring fee per object excluded"),
    "STANDARD_IA": ("S3 Standard-IA", "milliseconds", 30, "Infrequent access, rapid retrieval needed"),
    "GLACIER_IR": ("S3 Glacier Instant Retrieval", "milliseconds", 90, "Archive accessed about once a quarter"),
    "GLACIER": ("S3 Glacier Flexible Retrieval", "minutes to 12 hours", 90, "Archive, retrieval delays acceptable"),
    "DEEP_ARCHIVE": ("S3 Glacier Deep Archive", "12-48 hours", 180, "Long-term retention / compliance"),
}


def compare_storage(catalog: pd.DataFrame, gb: float, retrieval_pct: float, region: str,
                    months: int = 12) -> pd.DataFrame:
    """Monthly cost of `gb` stored with `retrieval_pct`% of it read back each month."""
    rows = []
    for cls, (label, latency, min_days, use) in S3_TIERS.items():
        s = P.get_price(catalog, "AmazonS3", cls, "storage", P.TERM_OD, region)
        r = P.get_price(catalog, "AmazonS3", cls, "retrieval", P.TERM_OD, region)
        if s is None:
            continue
        storage = gb * s.price
        retrieval = gb * retrieval_pct / 100 * (r.price if r else 0)
        rows.append({"storage_class": cls, "tier": label, "storage_price_gb": s.price,
                     "retrieval_price_gb": r.price if r else 0.0, "storage_usd": storage,
                     "retrieval_usd": retrieval, "monthly_usd": storage + retrieval,
                     "annual_usd": (storage + retrieval) * A.MONTHS_PER_YEAR,
                     "period_usd": (storage + retrieval) * months, "retrieval_latency": latency,
                     "min_storage_days": min_days, "best_for": use, "source": s.source})
    df = pd.DataFrame(rows)
    base = df.loc[df.storage_class == "STANDARD", "monthly_usd"].iloc[0]
    df["savings_month_usd"] = (base - df.monthly_usd).round(6)
    df["savings_pct"] = 100 * df.savings_month_usd / base if base else 0.0
    return df
