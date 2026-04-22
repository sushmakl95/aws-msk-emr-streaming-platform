"""WebSocket $disconnect handler.

Cleans up the DynamoDB connection record when a client disconnects.
"""

from __future__ import annotations

import os
from typing import Any

import boto3


def handler(event: dict, context: Any) -> dict:
    table_name = os.environ["CONNECTIONS_TABLE"]
    ddb = boto3.resource("dynamodb")
    table = ddb.Table(table_name)

    connection_id = event["requestContext"]["connectionId"]

    try:
        table.delete_item(Key={"connection_id": connection_id})
    except Exception:
        pass  # Idempotent; DDB TTL will also clean up stale entries

    return {"statusCode": 200, "body": "disconnected"}
