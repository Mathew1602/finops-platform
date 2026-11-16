"""Module 3: hypothetical infrastructure scenarios (save / load as JSON).

A scenario looks like:
    {"name": "...", "description": "...", "region": "us-east-1",
     "created": iso, "updated": iso,
     "resources": {"ec2": [{...}, ...], "s3": [...], ...}}

RESOURCE_SPECS defines the fields for each resource type. The builder UI and
the cost estimator both read it, so they stay in sync.
"""

from __future__ import annotations

import datetime as dt
import json
import re

from finops import assumptions as A

DEPARTMENTS = ["Development", "E-commerce", "Analytics", "Customer Services", "IT Operations"]
EBS_TYPES = ["gp3", "gp2", "io1", "st1", "sc1"]
S3_CLASSES = ["STANDARD", "STANDARD_IA", "INTELLIGENT_TIERING", "GLACIER_IR", "GLACIER", "DEEP_ARCHIVE"]
RDS_CLASSES = ["db.t3.micro", "db.t3.small", "db.t3.medium", "db.t3.large",
               "db.m5.large", "db.m5.xlarge", "db.r5.large", "db.r5.xlarge"]

# field -> (kind, default, options-or-(min,max), help)
RESOURCE_SPECS: dict[str, dict] = {
    "ec2": {
        "label": "EC2 instances", "service": "AmazonEC2",
        "fields": {
            "name": ("text", "web-server", None, "Resource name"),
            "department": ("select", "Development", DEPARTMENTS, "Cost-allocation tag"),
            "instance_type": ("select", "t3.small", "EC2_TYPES", "Instance type"),
            "os": ("select", "Linux", ["Linux", "Windows"], "Operating system"),
            "count": ("int", 1, (0, 1000), "Number of instances"),
            "hours_per_month": ("int", A.HOURS_PER_MONTH, (0, A.HOURS_PER_MONTH), "Running hours per month"),
            "ebs_type": ("select", "gp3", EBS_TYPES, "EBS volume type"),
            "ebs_gb": ("int", 30, (0, 64000), "EBS GB per instance"),
        },
    },
    "s3": {
        "label": "S3 storage", "service": "AmazonS3",
        "fields": {
            "name": ("text", "app-bucket", None, "Bucket name"),
            "department": ("select", "Development", DEPARTMENTS, "Cost-allocation tag"),
            "storage_class": ("select", "STANDARD", S3_CLASSES, "Storage class"),
            "storage_gb": ("float", 100.0, (0, 10_000_000), "Average GB stored"),
            "put_requests_k": ("float", 10.0, (0, 1e9), "PUT/LIST requests (thousands / month)"),
            "get_requests_k": ("float", 100.0, (0, 1e9), "GET requests (thousands / month)"),
            "retrieval_gb": ("float", 0.0, (0, 1e9), "GB retrieved per month (IA/Glacier)"),
        },
    },
    "rds": {
        "label": "RDS databases", "service": "AmazonRDS",
        "fields": {
            "name": ("text", "app-db", None, "DB identifier"),
            "department": ("select", "E-commerce", DEPARTMENTS, "Cost-allocation tag"),
            "instance_class": ("select", "db.t3.medium", RDS_CLASSES, "DB instance class"),
            "engine": ("select", "MySQL", ["MySQL", "PostgreSQL"], "Engine"),
            "multi_az": ("bool", False, None, "Multi-AZ deployment"),
            "count": ("int", 1, (0, 100), "Number of DB instances"),
            "hours_per_month": ("int", A.HOURS_PER_MONTH, (0, A.HOURS_PER_MONTH), "Running hours per month"),
            "storage_gb": ("int", 20, (20, 64000), "Allocated storage GB"),
        },
    },
    "dynamodb": {
        "label": "DynamoDB tables (on-demand)", "service": "AmazonDynamoDB",
        "fields": {
            "name": ("text", "sessions", None, "Table name"),
            "department": ("select", "Customer Services", DEPARTMENTS, "Cost-allocation tag"),
            "read_requests_m": ("float", 1.0, (0, 1e6), "Read request units (millions / month)"),
            "write_requests_m": ("float", 0.5, (0, 1e6), "Write request units (millions / month)"),
            "storage_gb": ("float", 10.0, (0, 1e6), "Table storage GB"),
        },
    },
    "lambda": {
        "label": "Lambda functions", "service": "AWSLambda",
        "fields": {
            "name": ("text", "api-handler", None, "Function name"),
            "department": ("select", "Customer Services", DEPARTMENTS, "Cost-allocation tag"),
            "invocations_m": ("float", 2.0, (0, 1e6), "Invocations (millions / month)"),
            "memory_mb": ("int", 512, (128, 10240), "Memory MB"),
            "avg_duration_ms": ("int", 200, (1, 900_000), "Average duration ms"),
        },
    },
    "elb": {
        "label": "Load balancers", "service": "AWSELB",
        "fields": {
            "name": ("text", "web-alb", None, "Load balancer name"),
            "department": ("select", "E-commerce", DEPARTMENTS, "Cost-allocation tag"),
            "lb_type": ("select", "application", ["application", "network"], "Load balancer type"),
            "count": ("int", 1, (0, 100), "Number of load balancers"),
            "hours_per_month": ("int", A.HOURS_PER_MONTH, (0, A.HOURS_PER_MONTH), "Hours per month"),
            "avg_lcu": ("float", 1.0, (0, 10000), "Average capacity units consumed per hour"),
        },
    },
    "backup": {
        "label": "AWS Backup", "service": "AWSBackup",
        "fields": {
            "name": ("text", "nightly-backups", None, "Backup plan"),
            "department": ("select", "IT Operations", DEPARTMENTS, "Cost-allocation tag"),
            "resource_type": ("select", "EBS", ["EBS", "S3", "RDS", "DynamoDB"], "Protected resource type"),
            "storage_gb": ("float", 200.0, (0, 1e7), "Backup storage GB (warm)"),
        },
    },
}


def default_row(rtype: str) -> dict:
    return {f: spec[1] for f, spec in RESOURCE_SPECS[rtype]["fields"].items()}


def normalise_rows(rtype: str, rows: list[dict]) -> list[dict]:
    """Fill missing / NaN fields with defaults and drop blank rows."""
    out = []
    fields = RESOURCE_SPECS[rtype]["fields"]
    for row in rows:
        clean = {}
        for f, (kind, default, _, _) in fields.items():
            v = row.get(f, default)
            if v is None or (isinstance(v, float) and v != v):  # NaN
                v = default
            if kind == "int":
                v = int(v)
            elif kind == "float":
                v = float(v)
            elif kind == "bool":
                v = bool(v)
            clean[f] = v
        if str(clean.get("name", "")).strip():
            out.append(clean)
    return out


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "scenario"


def _path(name: str):
    return A.SCENARIO_DIR / f"{slugify(name)}.json"


def new_scenario(name: str, region: str = A.BASE_REGION, description: str = "") -> dict:
    now = dt.datetime.now().isoformat(timespec="seconds")
    return {"name": name, "description": description, "region": region,
            "created": now, "updated": now, "resources": {k: [] for k in RESOURCE_SPECS}}


def save_scenario(scn: dict) -> str:
    A.SCENARIO_DIR.mkdir(parents=True, exist_ok=True)
    scn = {**scn, "updated": dt.datetime.now().isoformat(timespec="seconds")}
    scn["resources"] = {k: normalise_rows(k, scn["resources"].get(k, [])) for k in RESOURCE_SPECS}
    path = _path(scn["name"])
    path.write_text(json.dumps(scn, indent=2))
    return str(path)


def load_scenario(name: str) -> dict:
    scn = json.loads(_path(name).read_text())
    scn.setdefault("resources", {})
    for k in RESOURCE_SPECS:
        scn["resources"].setdefault(k, [])
    return scn


def delete_scenario(name: str) -> None:
    _path(name).unlink(missing_ok=True)


def list_scenarios() -> list[str]:
    ensure_examples()
    names = []
    for p in sorted(A.SCENARIO_DIR.glob("*.json")):
        try:
            names.append(json.loads(p.read_text())["name"])
        except (json.JSONDecodeError, KeyError):
            continue
    return names


def scenario_summary(scn: dict) -> dict:
    return {k: len(v) for k, v in scn["resources"].items() if v}


# ------------------------------------------------------------------ examples

def example_scenarios() -> list[dict]:
    doc = new_scenario("Brief example", "us-east-1",
                       "Example configuration from the project brief (Module 3 table). "
                       "Storage 100 GB is interpreted as EBS per EC2 instance.")
    doc["resources"].update({
        "ec2": [{**default_row("ec2"), "name": "app-server", "instance_type": "t3.small", "count": 3, "ebs_gb": 100}],
        "s3": [{**default_row("s3"), "name": "app-files", "storage_gb": 500}],
        "dynamodb": [{**default_row("dynamodb"), "name": "orders", "read_requests_m": 1.0, "write_requests_m": 0.0,
                      "storage_gb": 5}],
        "lambda": [{**default_row("lambda"), "name": "api-handler", "invocations_m": 2.0}],
        "rds": [{**default_row("rds"), "name": "app-db", "instance_class": "db.t3.medium"}],
    })

    ecom = new_scenario("E-commerce production", "us-east-1",
                        "Online shopping platform: EC2 web tier behind an ALB, Multi-AZ RDS, S3 media.")
    ecom["resources"].update({
        "ec2": [{**default_row("ec2"), "name": "web-tier", "department": "E-commerce", "instance_type": "m5.large",
                 "count": 4, "ebs_gb": 50},
                {**default_row("ec2"), "name": "worker", "department": "E-commerce", "instance_type": "c5.large",
                 "count": 2, "ebs_gb": 50}],
        "rds": [{**default_row("rds"), "name": "orders-db", "instance_class": "db.m5.large", "multi_az": True,
                 "storage_gb": 200}],
        "s3": [{**default_row("s3"), "name": "product-media", "department": "E-commerce", "storage_gb": 800,
                "get_requests_k": 5000, "put_requests_k": 200},
               {**default_row("s3"), "name": "order-archive", "department": "E-commerce",
                "storage_class": "STANDARD_IA", "storage_gb": 1500, "retrieval_gb": 50}],
        "elb": [{**default_row("elb"), "name": "shop-alb", "avg_lcu": 4.0}],
        "backup": [{**default_row("backup"), "name": "rds-backups", "department": "E-commerce",
                    "resource_type": "RDS", "storage_gb": 600}],
    })

    dev = new_scenario("Development small", "us-east-1",
                       "Dev environment running office hours only (about 220 h/month).")
    dev["resources"].update({
        "ec2": [{**default_row("ec2"), "name": "dev-box", "instance_type": "t3.medium", "count": 5,
                 "hours_per_month": 220, "ebs_gb": 40}],
        "s3": [{**default_row("s3"), "name": "build-artifacts", "storage_gb": 250}],
    })
    return [doc, ecom, dev]


def ensure_examples() -> None:
    """Write the example scenarios on first run so the demo works immediately."""
    A.SCENARIO_DIR.mkdir(parents=True, exist_ok=True)
    if not any(A.SCENARIO_DIR.glob("*.json")):
        for scn in example_scenarios():
            save_scenario(scn)
