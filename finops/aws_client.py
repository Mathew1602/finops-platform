"""Boto3 clients pointed at the local Floci AWS emulator."""

import os
from functools import lru_cache

import boto3
from botocore.config import Config

FLOCI_ENDPOINT = os.environ.get("FLOCI_ENDPOINT", "http://localhost:4566")
DEFAULT_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

_CONFIG = Config(connect_timeout=3, read_timeout=10, retries={"max_attempts": 1})


@lru_cache(maxsize=None)
def get_client(service: str, region: str = DEFAULT_REGION):
    """Return a boto3 client for `service` that talks to Floci.

    Floci accepts any credentials, so dummy test keys are used. The Pricing
    API is a global service that AWS serves from us-east-1, so it is pinned there.
    """
    if service == "pricing":
        region = "us-east-1"
    return boto3.client(
        service,
        endpoint_url=FLOCI_ENDPOINT,
        region_name=region,
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "test"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
        config=_CONFIG,
    )
