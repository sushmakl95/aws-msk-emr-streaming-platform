"""Kinesis Data Streams source builder.

Uses Spark's Kinesis connector (needs the AWS labs package at runtime). MSK is
the preferred bus in this platform, but Kinesis is supported as a secondary
path for teams already invested in Kinesis.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyspark.sql import DataFrame, SparkSession

from streaming.utils.logging_config import get_logger

log = get_logger(__name__, component="source.kinesis")


@dataclass
class KinesisSourceConfig:
    """Kinesis source configuration."""

    stream_name: str
    region: str = "us-east-1"
    initial_position: str = "LATEST"  # LATEST, TRIM_HORIZON, AT_TIMESTAMP
    timestamp_iso: str | None = None  # required if initial_position==AT_TIMESTAMP
    batch_size: int = 10_000


class KinesisSource:
    """Kinesis source for Spark Structured Streaming.

    Requires the Spark Kinesis connector:
      org.apache.spark:spark-streaming-kinesis-asl_2.12:3.5.0

    Authentication uses the running IAM role (EMR instance profile or EKS
    service account role). The role must have:
      kinesis:GetShardIterator, kinesis:GetRecords,
      kinesis:DescribeStream, kinesis:DescribeStreamSummary,
      dynamodb:* (for the checkpoint table the connector creates)
    """

    def __init__(self, spark: SparkSession, config: KinesisSourceConfig):
        self.spark = spark
        self.config = config

    def read_stream(self) -> DataFrame:
        """Build the streaming source DataFrame."""
        log.info(
            "kinesis_source_start",
            stream=self.config.stream_name,
            region=self.config.region,
            initial_position=self.config.initial_position,
        )

        reader = (
            self.spark.readStream
            .format("kinesis")
            .option("streamName", self.config.stream_name)
            .option("endpointUrl", f"https://kinesis.{self.config.region}.amazonaws.com")
            .option("region", self.config.region)
            .option("startingPosition", self.config.initial_position)
            .option("kinesis.executor.maxFetchRecordsPerShard", self.config.batch_size)
        )

        if self.config.initial_position == "AT_TIMESTAMP":
            if not self.config.timestamp_iso:
                raise ValueError(
                    "AT_TIMESTAMP requires timestamp_iso in config"
                )
            reader = reader.option("startingTimestamp", self.config.timestamp_iso)

        return reader.load()
