from finops import config_store as C
from finops import estimator as E


def _scn(**ec2):
    s = C.new_scenario("t")
    s["resources"]["ec2"] = [{**C.default_row("ec2"), "instance_type": "x.test", "ebs_gb": 0, **ec2}]
    return s


def test_brief_example_ec2_monthly(tiny_catalog):
    # Brief: 3 x $0.05 x 730 = $109.50
    lines, missing = E.estimate(_scn(count=3), tiny_catalog)
    assert not missing
    t = E.totals(lines)
    assert round(t["monthly"], 2) == 109.50
    assert round(t["annual"], 2) == 1314.00
    assert round(t["hourly"], 4) == 0.15


def test_partial_hours(tiny_catalog):
    lines, _ = E.estimate(_scn(count=2, hours_per_month=200), tiny_catalog)
    assert round(lines.monthly_usd.sum(), 2) == 20.00


def test_missing_price_reported(tiny_catalog):
    lines, missing = E.estimate(_scn(count=1, ebs_gb=10), tiny_catalog)
    assert missing == ["AmazonEBS gp3/storage"]


def test_lambda_and_rds_multi_az(ref_catalog):
    s = C.new_scenario("t")
    s["resources"]["lambda"] = [{**C.default_row("lambda"), "invocations_m": 1, "memory_mb": 1024,
                                 "avg_duration_ms": 1000}]
    s["resources"]["rds"] = [{**C.default_row("rds"), "instance_class": "db.t3.medium", "multi_az": True,
                              "storage_gb": 100}]
    lines, missing = E.estimate(s, ref_catalog)
    assert not missing
    lam = lines[lines.service == "Lambda"].monthly_usd.sum()
    assert abs(lam - (1e6 * 0.0000002 + 1e6 * 1.0 * 1.0 * 0.0000166667)) < 1e-6
    rds = lines[lines.service == "RDS"].monthly_usd.sum()
    assert abs(rds - (0.068 * 730 * 2 + 100 * 0.115 * 2)) < 1e-6


def test_example_scenarios_fully_priced(ref_catalog):
    for scn in C.example_scenarios():
        lines, missing = E.estimate(scn, ref_catalog)
        assert not missing, scn["name"]
        assert lines.monthly_usd.sum() > 0
