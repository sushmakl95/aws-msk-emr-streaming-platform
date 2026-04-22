"""WebSocket broadcast Lambda.

Triggered by MSK event source mapping (topic: ws-broadcast). Each message
contains a payload + a list of user_ids to push to (or '*' for all).

Flow:
    Stream job writes to 'ws-broadcast' topic
        → Lambda event source mapping triggers this handler
        → Handler queries DDB for matching connections
        → Handler calls API Gateway postToConnection for each

Environment variables:
    CONNECTIONS_TABLE: DynamoDB connection registry
    WS_ENDPOINT: API Gateway WebSocket mgmt endpoint
        (e.g., https://abc.execute-api.us-east-1.amazonaws.com/prod)
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

import boto3

from streaming.utils.logging_config import get_logger

log = get_logger(__name__, component="lambda.ws_broadcast")


def handler(event: dict, context: Any) -> dict:
    table_name = os.environ["CONNECTIONS_TABLE"]
    ws_endpoint = os.environ["WS_ENDPOINT"]

    ddb = boto3.resource("dynamodb")
    table = ddb.Table(table_name)
    apigw = boto3.client("apigatewaymanagementapi", endpoint_url=ws_endpoint)

    total_pushed = 0
    total_failed = 0

    for record_batch in event.get("records", {}).values():
        for record in record_batch:
            try:
                value_bytes = base64.b64decode(record["value"])
                msg = json.loads(value_bytes)
                user_targets = msg.get("user_targets", "*")
                payload = msg.get("payload", {})

                conn_ids = _find_connection_ids(table, user_targets)
                for conn_id in conn_ids:
                    try:
                        apigw.post_to_connection(
                            ConnectionId=conn_id,
                            Data=json.dumps(payload).encode("utf-8"),
                        )
                        total_pushed += 1
                    except apigw.exceptions.GoneException:
                        # Stale connection - remove from registry
                        table.delete_item(Key={"connection_id": conn_id})
                        total_failed += 1
                    except Exception as exc:
                        log.warning("push_failed", conn_id=conn_id, error=str(exc))
                        total_failed += 1
            except Exception as exc:
                log.exception("record_processing_failed", error=str(exc))
                total_failed += 1

    log.info("broadcast_complete", pushed=total_pushed, failed=total_failed)
    return {"statusCode": 200, "pushed": total_pushed, "failed": total_failed}


def _find_connection_ids(table: Any, user_targets: Any) -> list[str]:
    """Look up active connections for the given user_targets spec.

    user_targets can be:
      - "*" (broadcast to all connections)
      - single user_id string
      - list of user_id strings
    """
    if user_targets == "*":
        # Scan is expensive; in production, use a GSI on topic/user
        resp = table.scan(ProjectionExpression="connection_id")
        return [item["connection_id"] for item in resp.get("Items", [])]

    if isinstance(user_targets, str):
        user_targets = [user_targets]

    conn_ids: list[str] = []
    for user_id in user_targets:
        # Needs a GSI: user_id -> connection_id
        resp = table.query(
            IndexName="user_id_index",
            KeyConditionExpression="user_id = :u",
            ExpressionAttributeValues={":u": user_id},
        )
        conn_ids.extend(item["connection_id"] for item in resp.get("Items", []))
    return conn_ids
