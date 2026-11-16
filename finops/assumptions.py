"""Central place for every documented cost-calculation assumption.

Every number here is an assumption, not a measurement. The UI shows these
values on the Cost Estimator and Pricing Comparison pages so a reader can
check how each figure was produced.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
REFERENCE_DIR = DATA_DIR / "reference"
PRICING_CACHE_DIR = DATA_DIR / "pricing_cache"
SCENARIO_DIR = DATA_DIR / "scenarios"
SYNTHETIC_BILLING_CSV = DATA_DIR / "synthetic_billing.csv"

# ---------------------------------------------------------------- time
HOURS_PER_MONTH = 730          # AWS convention: 8,760 h / 12
DAYS_PER_MONTH = 30.42         # 365 / 12
MONTHS_PER_YEAR = 12
HOURS_PER_YEAR = HOURS_PER_MONTH * MONTHS_PER_YEAR

# ---------------------------------------------------------------- regions
# Floci's Pricing API (and the reference catalog) only carry us-east-1 prices.
# Other regions are derived with these multipliers. They approximate the
# typical public-price premium per region. They are NOT retrieved prices.
REGIONS = {
    "us-east-1": "US East (N. Virginia)",
    "us-east-2": "US East (Ohio)",
    "us-west-2": "US West (Oregon)",
    "ca-central-1": "Canada (Central)",
    "eu-west-1": "EU (Ireland)",
    "eu-central-1": "EU (Frankfurt)",
    "ap-southeast-1": "Asia Pacific (Singapore)",
}
LOCATION_TO_REGION = {v: k for k, v in REGIONS.items()}

REGION_PRICE_MULTIPLIER = {
    "us-east-1": 1.00,
    "us-east-2": 1.00,
    "us-west-2": 1.00,
    "ca-central-1": 1.10,
    "eu-west-1": 1.07,
    "eu-central-1": 1.15,
    "ap-southeast-1": 1.20,
}
BASE_REGION = "us-east-1"

# ---------------------------------------------------------------- pricing models
# Used only when the Pricing API / reference data has no explicit rate.
RESERVED_1YR_NO_UPFRONT_DISCOUNT = 0.36    # vs On-Demand, if not in dataset
RESERVED_3YR_ALL_UPFRONT_DISCOUNT = 0.60
SAVINGS_PLAN_1YR_DISCOUNT = 0.28           # Compute Savings Plan, no upfront
SAVINGS_PLAN_3YR_DISCOUNT = 0.50
SPOT_DEFAULT_DISCOUNT = 0.70               # if no spot price in dataset
RDS_RESERVED_1YR_DISCOUNT = 0.35
RDS_MULTI_AZ_FACTOR = 2.0                  # standby doubles instance + storage

# ---------------------------------------------------------------- exclusions
EXCLUSIONS = [
    "Data transfer out / inter-AZ / inter-region traffic",
    "AWS Free Tier allowances",
    "Taxes, credits, enterprise discounts",
    "Support plans",
    "Snapshot and request charges not entered in the configuration",
]

GENERAL_ASSUMPTIONS = {
    "Hours per month": f"{HOURS_PER_MONTH} (8,760 h / 12)",
    "Days per month": f"{DAYS_PER_MONTH} (365 / 12)",
    "Annual cost": "Monthly cost x 12",
    "Base pricing region": "us-east-1 (other regions = base x region multiplier)",
    "Currency": "USD",
    "Default pricing model": "On-Demand",
}
