"""AWS Secrets Manager helper."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

import boto3

from streaming.utils.logging_config import get_logger

log = get_logger(__name__, component="secrets")


@lru_cache(maxsize=32)
def get_secret(secret_id: str, region: str = "us-east-1") -> dict[str, Any]:
    """Fetch a JSON secret."""
    client = boto3.client("secretsmanager", region_name=region)
    try:
        response = client.get_secret_value(SecretId=secret_id)
    except client.exceptions.ResourceNotFoundException as exc:
        raise RuntimeError(f"Secret not found: {secret_id}") from exc

    secret_string = response.get("SecretString")
    if not secret_string:
        raise RuntimeError(f"Secret {secret_id} has no SecretString")

    try:
        return json.loads(secret_string)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Secret {secret_id} is not valid JSON - use structured secrets"
        ) from exc


def invalidate_cache() -> None:
    """Clear after rotation."""
    get_secret.cache_clear()
