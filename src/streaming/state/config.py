"""State store configuration helpers for streaming jobs.

Covers Spark's RocksDB state store and Flink's state backend.
"""

from __future__ import annotations


def rocksdb_state_store_config(
    compact_on_commit: bool = True,
    compression: str = "lz4",
    block_size_kb: int = 4,
    write_buffer_size_mb: int = 64,
    max_write_buffer_number: int = 4,
) -> dict[str, str]:
    """Spark RocksDB state store tuning.

    Defaults chosen for workloads with high update rate + moderate state size.
    For large state (>100GB), bump write_buffer_size_mb to 128 and
    max_write_buffer_number to 6.
    """
    return {
        "spark.sql.streaming.stateStore.providerClass": (
            "org.apache.spark.sql.execution.streaming.state.RocksDBStateStoreProvider"
        ),
        "spark.sql.streaming.stateStore.rocksdb.compactOnCommit": str(compact_on_commit).lower(),
        "spark.sql.streaming.stateStore.rocksdb.compression": compression,
        "spark.sql.streaming.stateStore.rocksdb.blockSizeKB": str(block_size_kb),
        "spark.sql.streaming.stateStore.rocksdb.writeBufferSizeMB": str(write_buffer_size_mb),
        "spark.sql.streaming.stateStore.rocksdb.maxWriteBufferNumber": str(max_write_buffer_number),
        "spark.sql.streaming.stateStore.rocksdb.changelogCheckpointing.enabled": "true",
        # Disable timer compression to avoid rare data loss issues
        "spark.sql.streaming.stateStore.rocksdb.trackTotalNumberOfRows": "true",
    }


def flink_state_backend_config(
    checkpoint_dir: str,
    incremental: bool = True,
    local_recovery: bool = True,
) -> dict[str, str]:
    """Flink RocksDB state backend config.

    For KDA (Kinesis Data Analytics), some of these are overridden by the
    application config. These work for self-managed Flink clusters too.
    """
    return {
        "state.backend": "rocksdb",
        "state.checkpoints.dir": checkpoint_dir,
        "state.backend.incremental": str(incremental).lower(),
        "state.backend.local-recovery": str(local_recovery).lower(),
        "state.backend.rocksdb.localdir": "/tmp/flink-rocksdb",
        "state.backend.rocksdb.memory.managed": "true",
        # Predefined options for write-heavy workloads
        "state.backend.rocksdb.predefined-options": "SPINNING_DISK_OPTIMIZED_HIGH_MEM",
    }


def watermark_tuning_advice(
    source_type: str,
    expected_out_of_orderness: str = "10 seconds",
    acceptable_late_arrival: str = "10 minutes",
) -> dict[str, str]:
    """Watermark tuning cheatsheet per source type."""
    advice = {
        "kafka": (
            "Use kafka timestamp from message headers as event time. "
            f"Set withWatermark('event_time', '{expected_out_of_orderness}')."
        ),
        "kinesis": (
            "Kinesis is strictly per-shard ordered; set watermark based on the "
            f"max event time seen per shard. Delay: '{expected_out_of_orderness}'."
        ),
        "cdc_debezium": (
            "Use source.ts_ms from Debezium envelope (the DB transaction commit). "
            "This is strictly increasing per transaction, so watermarks can be tight "
            f"('{expected_out_of_orderness}')."
        ),
    }
    return {
        "advice": advice.get(source_type, "Unknown source type"),
        "recommended_watermark_delay": expected_out_of_orderness,
        "acceptable_late_arrival": acceptable_late_arrival,
    }
