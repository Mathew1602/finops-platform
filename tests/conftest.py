import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from finops import pricing as P  # noqa: E402


@pytest.fixture(scope="session")
def ref_catalog():
    """Reference-only catalog so tests never need Floci running."""
    cat, _ = P.build_catalog(use_api=False)
    return cat


@pytest.fixture
def tiny_catalog():
    """Catalog with the brief's $0.05/h EC2 price."""
    return pd.DataFrame([
        ["AmazonEC2", "x.test", "Linux", "us-east-1", P.TERM_OD, "Hrs", 0.05, "test", "brief example"],
        ["AmazonEC2", "x.test", "Linux", "us-east-1", P.TERM_RI_1YR, "Hrs", 0.035, "test", "brief example"],
    ], columns=P.CATALOG_COLUMNS)
