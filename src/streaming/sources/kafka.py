"""Kafka/MSK source builder with IAM auth + Glue Schema Registry."""

from __future__ import annotations

from dataclasses import dataclass

from pyspark.sql import DataFrame, SparkSession

from streaming.utils.logging_config import get_logger

log = get_logger(__name__, component="source.kafka")


@dataclass
class KafkaSourceConfig:
    """Kafka source configuration.

    For MSK with IAM auth, set:
      use_iam_auth=True
      bootstrap_servers=<broker list from cluster>

    For local dev Kafka (no auth):
      use_iam_auth=False
      bootstrap_servers="localhost:9092"
    """

    bootstrap_servers: str
    topics: list[str]
    starting_offsets: str = "latest"  # "earliest", "latest", or JSON
    max_offsets_per_trigger: int | None = None
    use_iam_auth: bool = True
    consumer_group: str | None = None
    """If set, enables Kafka consumer group commits (loses exactly-once in
    favor of at-least-once with visible lag metrics)."""
    fail_on_data_loss: bool = True


class KafkaSource:
    """MSK / Kafka source for Spark Structured Streaming.

    Exactly-once semantics achieved via Spark's checkpoint offsets (not Kafka
    consumer groups). Set `consumer_group` only if you need external lag
    monitoring and can tolerate at-least-once.
    """

    def __init__(self, spark: SparkSession, config: KafkaSourceConfig):
        self.spark = spark
        self.config = config

    def read_stream(self) -> DataFrame:
        """Build the streaming source DataFrame."""
        log.info(
            "kafka_source_start",
            bootstrap=self.config.bootstrap_servers,
            topics=self.config.topics,
            iam=self.config.use_iam_auth,
        )

        reader = (
            self.spark.readStream
            .format("kafka")
            .option("kafka.bootstrap.servers", self.config.bootstrap_servers)
            .option("subscribe", ",".join(self.config.topics))
            .option("startingOffsets", self.config.starting_offsets)
            .option("failOnDataLoss", str(self.config.fail_on_data_loss).lower())
        )

        if self.config.max_offsets_per_trigger:
            reader = reader.option(
                "maxOffsetsPerTrigger", self.config.max_offsets_per_trigger
            )

        if self.config.use_iam_auth:
            # MSK IAM auth requires these configs; IAM role must have
            # kafka-cluster:Connect + kafka-cluster:ReadData
            reader = (
                reader
                .option("kafka.security.protocol", "SASL_SSL")
                .option("kafka.sasl.mechanism", "AWS_MSK_IAM")
                .option(
                    "kafka.sasl.jaas.config",
                    "software.amazon.msk.auth.iam.IAMLoginModule required;",
                )
                .option(
                    "kafka.sasl.client.callback.handler.class",
                    "software.amazon.msk.auth.iam.IAMClientCallbackHandler",
                )
            )

        if self.config.consumer_group:
            reader = reader.option("kafka.group.id", self.config.consumer_group)

        return reader.load()
