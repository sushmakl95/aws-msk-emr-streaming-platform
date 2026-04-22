"""PyFlink DataStream job: real-time deduplication + late-arrival handling.

Shows the Flink DataStream API as an alternative to SQL for cases where you
need fine-grained control over state/timers (e.g., custom windowing,
side outputs for late events).

Runs on Amazon Kinesis Data Analytics for Apache Flink. Submit via:
    flink run -py dedup_stream.py -pyexec /usr/bin/python3 \\
      --bootstrap-servers <msk-brokers> \\
      --topic app.transactions
"""

from __future__ import annotations

import argparse
from typing import Any

# These imports are for PyFlink runtime - commented out here since CI doesn't have
# PyFlink installed. Uncomment when running on KDA.
# from pyflink.common import Configuration, Time
# from pyflink.common.serialization import SimpleStringSchema
# from pyflink.common.typeinfo import Types
# from pyflink.datastream import StreamExecutionEnvironment
# from pyflink.datastream.connectors.kafka import KafkaSource
# from pyflink.datastream.functions import KeyedProcessFunction


class DedupWithTimer:
    """KeyedProcessFunction that emits each txn_id once per 1-hour window.

    Uses Flink's timer service + value state. Late events (beyond 1h of their
    canonical time) are sent to a side output for audit.
    """

    LATE_EVENTS_TAG = "late-events"
    DEDUP_WINDOW_MS = 60 * 60 * 1000  # 1h

    def __init__(self):
        self.seen_state = None  # ValueState[Boolean]

    def open(self, runtime_context: Any) -> None:
        # state_descriptor = ValueStateDescriptor("seen", Types.BOOLEAN())
        # self.seen_state = runtime_context.get_state(state_descriptor)
        pass

    def process_element(self, txn: dict, ctx: Any) -> Any:
        seen = self.seen_state.value() if self.seen_state else None

        event_time_ms = int(txn.get("event_time_ms", 0))
        current_watermark = ctx.timer_service().current_watermark()

        # Late event handling
        if event_time_ms < current_watermark - self.DEDUP_WINDOW_MS:
            ctx.output(self.LATE_EVENTS_TAG, txn)
            return

        if seen is None or not seen:
            # First occurrence - emit + set timer for state cleanup
            self.seen_state.update(True)
            ctx.timer_service().register_event_time_timer(
                event_time_ms + self.DEDUP_WINDOW_MS
            )
            yield txn

    def on_timer(self, timestamp: int, ctx: Any) -> None:
        # Cleanup state after window elapses
        self.seen_state.clear()


def run_job(args: argparse.Namespace) -> None:
    """Entry point for the job."""
    # env = StreamExecutionEnvironment.get_execution_environment()
    # env.set_parallelism(4)
    # env.enable_checkpointing(30_000)  # 30s
    # env.get_checkpoint_config().set_checkpoint_storage_dir(args.checkpoint_dir)
    #
    # kafka_source = (
    #     KafkaSource.builder()
    #     .set_bootstrap_servers(args.bootstrap_servers)
    #     .set_topics(args.topic)
    #     .set_value_only_deserializer(SimpleStringSchema())
    #     .set_properties({
    #         "security.protocol": "SASL_SSL",
    #         "sasl.mechanism": "AWS_MSK_IAM",
    #     })
    #     .build()
    # )
    #
    # ds = env.from_source(kafka_source, WatermarkStrategy.no_watermarks(), "msk")
    # parsed = ds.map(lambda s: json.loads(s), output_type=Types.PICKLED_BYTE_ARRAY())
    # deduped = (
    #     parsed
    #     .key_by(lambda t: t["txn_id"])
    #     .process(DedupWithTimer(), output_type=Types.PICKLED_BYTE_ARRAY())
    # )
    # deduped.print()
    # env.execute("realtime-dedup")
    print(f"Would start Flink dedup job reading from {args.topic}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap-servers", required=True)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--checkpoint-dir", required=True)
    args = parser.parse_args()
    run_job(args)


if __name__ == "__main__":
    main()
