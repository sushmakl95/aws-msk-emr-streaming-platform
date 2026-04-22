"""Enrichment — join streaming data with dimensions or other streams."""

from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F


def broadcast_enrich(
    stream_df: DataFrame,
    dim_df: DataFrame,
    join_key: str,
    dim_cols: list[str],
    join_type: str = "left",
) -> DataFrame:
    """Enrich a stream with a broadcasted dimension table.

    Safe for dim tables under ~2GB. The dim_df should be a batch DataFrame
    (not streaming). Use `refresh_dim_df` at restart to pick up dim changes.

    Example: enrich orders stream with product catalog.
    """
    return stream_df.join(
        F.broadcast(dim_df.select(join_key, *dim_cols)),
        on=join_key,
        how=join_type,
    )


def stream_stream_join(
    left_df: DataFrame,
    right_df: DataFrame,
    join_key: str,
    left_event_time: str,
    right_event_time: str,
    time_window: str = "1 hour",
    join_type: str = "inner",
    left_watermark: str = "10 minutes",
    right_watermark: str = "10 minutes",
) -> DataFrame:
    """Stream-stream join with time constraint.

    Without a time constraint, state grows unbounded. The time_window limits
    how much of each stream's state Spark keeps.

    Example: join clickstream to orders placed within 1 hour of the click.
    """
    left_wm = left_df.withWatermark(left_event_time, left_watermark)
    right_wm = right_df.withWatermark(right_event_time, right_watermark)

    join_condition = (
        (F.col(f"left.{join_key}") == F.col(f"right.{join_key}"))
        & (F.col(f"left.{left_event_time}") >= F.col(f"right.{right_event_time}"))
        & (
            F.col(f"left.{left_event_time}")
            <= F.col(f"right.{right_event_time}") + F.expr(f"INTERVAL {time_window}")
        )
    )

    return left_wm.alias("left").join(
        right_wm.alias("right"),
        on=join_condition,
        how=join_type,
    )


def refresh_dim_df(spark, dim_source: str, refresh_timestamp: str = None) -> DataFrame:
    """Load/refresh a dimension DataFrame at job restart.

    For slowly-changing dims, re-read on restart (daily/weekly cadence).
    For near-real-time dims, consider CDC-fed broadcast state in Flink or
    state store updates in Spark.
    """
    df = spark.read.format("delta").load(dim_source)
    if refresh_timestamp:
        df = df.filter(F.col("_loaded_at") <= F.lit(refresh_timestamp))
    df.cache()
    return df
