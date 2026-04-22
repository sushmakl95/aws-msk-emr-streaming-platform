"""Topic creator Lambda.

Invoked by Terraform (aws_lambda_invocation) to create initial MSK topics.
Uses IAM auth; must run in a VPC subnet with access to the MSK cluster.

Payload:
    {
        "bootstrap_servers": "...",
        "topics": [
            {"name": "cdc.public.orders", "partitions": 6, "replication_factor": 3},
            ...
        ]
    }
"""

from __future__ import annotations

from typing import Any

from confluent_kafka.admin import AdminClient, NewTopic

from streaming.utils.logging_config import get_logger

log = get_logger(__name__, component="lambda.topic_creator")


def handler(event: dict, context: Any) -> dict:
    bootstrap = event["bootstrap_servers"]
    topics = event.get("topics", [])

    admin = AdminClient({
        "bootstrap.servers": bootstrap,
        "security.protocol": "SASL_SSL",
        "sasl.mechanisms": "OAUTHBEARER",
        "sasl.oauthbearer.config": "aws_msk_iam",
    })

    new_topics = [
        NewTopic(
            topic=t["name"],
            num_partitions=t.get("partitions", 3),
            replication_factor=t.get("replication_factor", 3),
            config=t.get("config", {
                "retention.ms": "604800000",  # 7 days default
                "compression.type": "lz4",
                "min.insync.replicas": "2",
            }),
        )
        for t in topics
    ]

    created: list[str] = []
    skipped: list[str] = []
    failed: list[dict] = []

    futures = admin.create_topics(new_topics, request_timeout=30)
    for topic, future in futures.items():
        try:
            future.result()
            created.append(topic)
            log.info("topic_created", topic=topic)
        except Exception as exc:
            msg = str(exc)
            if "already exists" in msg.lower():
                skipped.append(topic)
            else:
                failed.append({"topic": topic, "error": msg})
                log.warning("topic_creation_failed", topic=topic, error=msg)

    return {
        "created": created,
        "skipped": skipped,
        "failed": failed,
        "ok": len(failed) == 0,
    }
