"""Windowing transforms for streaming aggregations.

Covers the 3 window types: tumbling, sliding, session.
"""

from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F


def tumbling_window(
    df: DataFrame,
    event_time_col: str,
    window_duration: str,
    group_cols: list[str],
    aggregations: dict[str, str],
    watermark_delay: str = "10 minutes",
) -> DataFrame:
    """Non-overlapping fixed-size windows.

    Example: count events per-user per-5-minute bucket.

        tumbling_window(df, "event_time", "5 minutes", ["user_id"], {"*": "count"})

    `aggregations` maps column name → agg function ("count", "sum", "avg", "max", "min").
    """
    watermarked = df.withWatermark(event_time_col, watermark_delay)
    agg_exprs = [
        F.count("*").alias(f"{col}_count") if fn == "count" and col == "*"
        else _agg_expr(col, fn)
        for col, fn in aggregations.items()
    ]
    return (
        watermarked
        .groupBy(
            F.window(F.col(event_time_col), window_duration).alias("window"),
            *[F.col(c) for c in group_cols],
        )
        .agg(*agg_exprs)
        .select(
            F.col("window.start").alias("window_start"),
            F.col("window.end").alias("window_end"),
            *[F.col(c) for c in group_cols],
            *[F.col(c) for c in _agg_output_cols(aggregations)],
        )
    )


def sliding_window(
    df: DataFrame,
    event_time_col: str,
    window_duration: str,
    slide_duration: str,
    group_cols: list[str],
    aggregations: dict[str, str],
    watermark_delay: str = "10 minutes",
) -> DataFrame:
    """Overlapping windows (e.g., 5-min window sliding every 1 min).

    Example: rolling 5-minute count, updated every minute.
    """
    watermarked = df.withWatermark(event_time_col, watermark_delay)
    agg_exprs = [_agg_expr(col, fn) for col, fn in aggregations.items()]
    return (
        watermarked
        .groupBy(
            F.window(
                F.col(event_time_col), window_duration, slide_duration
            ).alias("window"),
            *[F.col(c) for c in group_cols],
        )
        .agg(*agg_exprs)
        .select(
            F.col("window.start").alias("window_start"),
            F.col("window.end").alias("window_end"),
            *[F.col(c) for c in group_cols],
            *[F.col(c) for c in _agg_output_cols(aggregations)],
        )
    )


def session_window(
    df: DataFrame,
    event_time_col: str,
    session_gap: str,
    group_cols: list[str],
    aggregations: dict[str, str],
    watermark_delay: str = "10 minutes",
) -> DataFrame:
    """Session windows — dynamic size, closed after a gap of inactivity.

    Example: group user clicks into sessions (30-min inactivity).
    """
    watermarked = df.withWatermark(event_time_col, watermark_delay)
    agg_exprs = [_agg_expr(col, fn) for col, fn in aggregations.items()]
    return (
        watermarked
        .groupBy(
            F.session_window(F.col(event_time_col), session_gap).alias("window"),
            *[F.col(c) for c in group_cols],
        )
        .agg(*agg_exprs)
        .select(
            F.col("window.start").alias("session_start"),
            F.col("window.end").alias("session_end"),
            *[F.col(c) for c in group_cols],
            *[F.col(c) for c in _agg_output_cols(aggregations)],
        )
    )


def _agg_expr(col: str, fn: str):
    fn_lower = fn.lower()
    if fn_lower == "count":
        return F.count(col).alias(f"{col}_count")
    if fn_lower == "sum":
        return F.sum(col).alias(f"{col}_sum")
    if fn_lower == "avg":
        return F.avg(col).alias(f"{col}_avg")
    if fn_lower == "max":
        return F.max(col).alias(f"{col}_max")
    if fn_lower == "min":
        return F.min(col).alias(f"{col}_min")
    raise ValueError(f"Unsupported aggregation: {fn}")


def _agg_output_cols(aggregations: dict[str, str]) -> list[str]:
    return [
        f"{col}_count" if col == "*" and fn == "count" else f"{col}_{fn.lower()}"
        for col, fn in aggregations.items()
    ]
