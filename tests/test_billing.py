import datetime as dt

from finops import billing as B

START, END = dt.date(2025, 12, 1), dt.date(2026, 11, 15)


def test_synthetic_is_deterministic_and_labelled():
    a = B.generate_synthetic_billing(START, END, seed=1)
    b = B.generate_synthetic_billing(START, END, seed=1)
    assert a.equals(b)
    assert set(a.source) == {B.SRC_SIM}
    assert set(a.department) == set(B.DEPARTMENTS)


def test_synthetic_trend_increases_and_matches_calibration():
    df = B.generate_synthetic_billing(START, END)
    m = B.monthly(df).set_index("month").cost_usd
    assert m.iloc[-2] > m.iloc[0]                               # spend grows
    target = sum(d["monthly"] for d in B.DEPARTMENTS.values())
    assert abs(m.loc["2026-10-01"] - target) / target < 0.08    # last full month near calibration


def test_compare_periods():
    df = B.generate_synthetic_billing(START, END)
    cmp = B.compare_periods(df, ("2026-09-01", "2026-09-30"), ("2026-10-01", "2026-10-31"))
    assert {"period_1", "period_2", "change_usd", "change_pct"} <= set(cmp.columns)
    assert cmp.change_usd.is_monotonic_decreasing


def test_ce_has_data():
    import pandas as pd
    assert not B.ce_has_data(pd.DataFrame({"cost_usd": [0.0, 0.0]}))
    assert B.ce_has_data(pd.DataFrame({"cost_usd": [0.0, 1.5]}))


def test_regenerate_reproduces_saved_dataset(tmp_path, monkeypatch):
    path = tmp_path / "billing.csv"
    monkeypatch.setattr(B.A, "SYNTHETIC_BILLING_CSV", path)
    B.generate_synthetic_billing(dt.date(2026, 1, 1), dt.date(2026, 3, 31)).to_csv(path, index=False)
    before = path.read_bytes()
    df = B.load_synthetic_billing(regenerate=True)
    assert path.read_bytes() == before
    assert df.date.max().date() == dt.date(2026, 3, 31)
