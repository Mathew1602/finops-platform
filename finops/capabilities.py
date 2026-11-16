"""Probe which Pricing / Cost Explorer operations the installed Floci supports.

The project spec requires checking supported operations before relying on
them, so the result is shown on the Home page. Run as a script:
    python -m finops.capabilities
"""

import datetime as dt

import pandas as pd

from finops.aws_client import FLOCI_ENDPOINT, get_client


def _period(days_back: int = 90):
    end = dt.date.today()
    return {"Start": str(end - dt.timedelta(days=days_back)), "End": str(end)}


def _future_period():
    start = dt.date.today() + dt.timedelta(days=1)
    return {"Start": str(start), "End": str(start + dt.timedelta(days=30))}


PROBES = [
    ("pricing", "describe_services", lambda c: c.describe_services(MaxResults=100),
     lambda r: f"{len(r.get('Services', []))} services"),
    ("pricing", "get_attribute_values", lambda c: c.get_attribute_values(
        ServiceCode="AmazonEC2", AttributeName="instanceType"),
     lambda r: f"{len(r.get('AttributeValues', []))} EC2 instance types"),
    ("pricing", "get_products", lambda c: c.get_products(ServiceCode="AmazonEC2", MaxResults=100),
     lambda r: f"{len(r.get('PriceList', []))} EC2 price items"),
    ("ce", "get_cost_and_usage", lambda c: c.get_cost_and_usage(
        TimePeriod=_period(), Granularity="MONTHLY", Metrics=["UnblendedCost"]),
     lambda r: "total $" + format(sum(float(x["Total"]["UnblendedCost"]["Amount"])
                                       for x in r.get("ResultsByTime", [])), ",.2f")),
    ("ce", "get_dimension_values", lambda c: c.get_dimension_values(
        TimePeriod=_period(), Dimension="SERVICE"),
     lambda r: f"{len(r.get('DimensionValues', []))} services"),
    ("ce", "get_cost_forecast", lambda c: c.get_cost_forecast(
        TimePeriod=_future_period(), Metric="UNBLENDED_COST", Granularity="MONTHLY"),
     lambda r: "forecast returned"),
    ("ce", "get_tags", lambda c: c.get_tags(TimePeriod=_period()),
     lambda r: f"{len(r.get('Tags', []))} tag keys"),
]


def probe() -> pd.DataFrame:
    """Call each operation once and record supported / empty / error."""
    rows = []
    for service, op, call, summarize in PROBES:
        try:
            resp = call(get_client(service))
            detail = summarize(resp)
            status = "supported"
            if detail.startswith("0 ") or detail == "total $0.00":
                status = "supported (no data)"
        except Exception as exc:  # noqa: BLE001 - report every failure type
            msg = str(exc)
            status = "unsupported" if "Unknown operation" in msg or "not implemented" in msg.lower() else "error"
            detail = msg[:120]
        rows.append({"service": service, "operation": op, "status": status, "detail": detail})
    return pd.DataFrame(rows)


def floci_reachable() -> bool:
    try:
        get_client("pricing").describe_services(MaxResults=1)
        return True
    except Exception:  # noqa: BLE001
        return False


if __name__ == "__main__":
    print(f"Floci endpoint: {FLOCI_ENDPOINT}")
    print(probe().to_string(index=False))
