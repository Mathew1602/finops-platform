import pytest

from finops import pricing_models as M


def test_full_utilisation_savings(tiny_catalog):
    df = M.compare(M.ec2_models(tiny_catalog, "x.test", "Linux", "us-east-1"), count=5)
    od = df.set_index("model").loc["On-Demand"]
    ri = df.set_index("model").loc["Reserved 1yr (No Upfront)"]
    assert od.monthly_usd == pytest.approx(5 * 0.05 * 730)
    assert ri.monthly_usd == pytest.approx(5 * 0.035 * 730)
    assert ri.savings_pct == pytest.approx(30.0)
    assert ri.breakeven_utilisation_pct == pytest.approx(70.0)


def test_commitment_loses_at_low_utilisation(tiny_catalog):
    df = M.compare(M.ec2_models(tiny_catalog, "x.test", "Linux", "us-east-1"), count=1, utilisation=0.5)
    ri = df.set_index("model").loc["Reserved 1yr (No Upfront)"]
    assert ri.savings_pct < 0          # 0.035 * 730 > 0.05 * 365


def test_spot_falls_back_to_assumed_discount(tiny_catalog):
    spot = [m for m in M.ec2_models(tiny_catalog, "x.test", "Linux", "us-east-1") if m.name == "Spot"][0]
    assert spot.hourly_rate == pytest.approx(0.05 * 0.30)


def test_storage_tiers(ref_catalog):
    df = M.compare_storage(ref_catalog, gb=1000, retrieval_pct=0, region="us-east-1").set_index("storage_class")
    assert df.loc["STANDARD", "monthly_usd"] == pytest.approx(23.0)
    assert df.loc["DEEP_ARCHIVE", "monthly_usd"] == pytest.approx(0.99)
    # Heavy retrieval makes Standard-IA more expensive than Standard.
    heavy = M.compare_storage(ref_catalog, gb=1000, retrieval_pct=150, region="us-east-1").set_index("storage_class")
    assert heavy.loc["STANDARD_IA", "monthly_usd"] > heavy.loc["STANDARD", "monthly_usd"]


def test_commitments_are_billed_for_whole_terms(tiny_catalog):
    df = M.compare(M.ec2_models(tiny_catalog, "x.test", "Linux", "us-east-1"), count=1, months=6)
    df = df.set_index("model")
    assert df.loc["On-Demand", "period_usd"] == pytest.approx(6 * 0.05 * 730)
    assert df.loc["Reserved 1yr (No Upfront)", "paid_months"] == 12
    assert df.loc["Reserved 1yr (No Upfront)", "period_usd"] == pytest.approx(12 * 0.035 * 730)
    assert df.loc["Reserved 3yr (All Upfront)", "paid_months"] == 36
    assert df.loc["Reserved 1yr (No Upfront)", "period_savings_usd"] < 0    # 6-month need: RI loses
