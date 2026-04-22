"""WebSocket $connect handler.

Invoked by API Gateway when a client opens a wss:// connection. Stores the
connection in DynamoDB so the broadcaster Lambda can find it later.

Expected query parameters:
    ?user_id=<id>&topics=orders,alerts

Environment variables:
    CONNECTIONS_TABLE: DynamoDB table name
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import boto3


def handler(event: dict, context: Any) -> dict:
    table_name = os.environ["CONNECTIONS_TABLE"]
    ddb = boto3.resource("dynamodb")
    table = ddb.Table(table_name)

    connection_id = event["requestContext"]["connectionId"]
    qs = event.get("queryStringParameters") or {}
    user_id = qs.get("user_id", "anonymous")
    topics = [t.strip() for t in qs.get("topics", "").split(",") if t.strip()]

    # TTL: auto-expire 24h after connect (API Gateway closes idle conns at ~10 min)
    ttl = int(datetime.now(UTC).timestamp()) + 24 * 3600

    table.put_item(Item={
        "connection_id": connection_id,
        "user_id": user_id,
        "subscribed_topics": topics or ["*"],
        "connected_at": datetime.now(UTC).isoformat(),
        "ttl": ttl,
    })

    return {"statusCode": 200, "body": "connected"}
