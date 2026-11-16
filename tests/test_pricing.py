import json

from finops import assumptions as A
from finops import pricing as P


def test_reference_catalog_has_core_services(ref_catalog):
    for svc in ["AmazonEC2", "AmazonS3", "AmazonRDS", "AWSLambda", "AmazonDynamoDB", "AWSELB", "AWSBackup"]:
        assert (ref_catalog.service == svc).any(), svc
    assert set(ref_catalog.source) == {P.SRC_REF}


def test_region_multiplier_is_applied_and_labelled(ref_catalog):
    base = P.get_price(ref_catalog, "AmazonEC2", "t3.small", "Linux")
    fra = P.get_price(ref_catalog, "AmazonEC2", "t3.small", "Linux", region="eu-central-1")
    assert fra.price == base.price * A.REGION_PRICE_MULTIPLIER["eu-central-1"]
    assert fra.source == P.SRC_DERIVED


def test_missing_price_returns_none(ref_catalog):
    assert P.get_price(ref_catalog, "AmazonEC2", "does.not.exist", "Linux") is None


def test_flatten_amortises_reserved_upfront():
    doc = {"product": {"sku": "S1", "attributes": {"regionCode": "us-east-1", "instanceType": "m5.large"}},
           "terms": {"Reserved": {"S1.R": {
               "termAttributes": {"LeaseContractLength": "1yr", "PurchaseOption": "Partial Upfront"},
               "priceDimensions": {
                   "a": {"unit": "Quantity", "pricePerUnit": {"USD": "876"}, "description": "upfront"},
                   "b": {"unit": "Hrs", "pricePerUnit": {"USD": "0.02"}, "description": "hourly"}}}}}}
    flat = P.flatten_price_list([json.loads(json.dumps(doc))])
    assert len(flat) == 1
    row = flat.iloc[0]
    assert row.term == "Reserved-1yr-PartialUpfront"
    assert abs(row.effective_hourly - (0.02 + 876 / 8760)) < 1e-9


def test_same_price_region_is_still_labelled_derived(ref_catalog):
    # us-west-2 uses a x1.00 multiplier, but the price was not retrieved for that region.
    q = P.get_price(ref_catalog, "AmazonEC2", "t3.small", "Linux", region="us-west-2")
    assert q.source == P.SRC_DERIVED


def test_api_reserved_no_upfront_maps_to_lookup_term():
    doc = {"product": {"sku": "S1", "attributes": {"regionCode": "us-east-1", "instanceType": "m5.large",
                                                   "operatingSystem": "Linux"}},
           "terms": {"Reserved": {"S1.R": {
               "termAttributes": {"LeaseContractLength": "1yr", "PurchaseOption": "No Upfront"},
               "priceDimensions": {"b": {"unit": "Hrs", "pricePerUnit": {"USD": "0.06"}, "beginRange": "0",
                                         "description": "hourly"}}}}}}
    rows = P._api_rows_to_catalog("AmazonEC2", P.flatten_price_list([doc]))
    assert [r["term"] for r in rows] == [P.TERM_RI_1YR]
