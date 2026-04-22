# Contributing

## Adding a new streaming job

Most common contribution. Two paths:

### Spark Structured Streaming (Python)

1. Create `src/streaming/jobs/my_new_job.py`
2. Use sources from `streaming.sources`, sinks from `streaming.sinks`, transforms from `streaming.transforms`
3. Add a unit test in `tests/unit/`
4. Run `make ci` locally
5. Open PR

Template:
```python
from streaming.sources import KafkaSource, KafkaSourceConfig
from streaming.sinks import RedisSink, RedisSinkConfig
from streaming.utils import get_streaming_spark_session

def run(args):
    spark = get_streaming_spark_session(app_name="my-job")
    source = KafkaSource(spark, KafkaSourceConfig(
        bootstrap_servers=args.bootstrap_servers,
        topics=["my.topic"],
        use_iam_auth=not args.local,
    ))
    sink = RedisSink(RedisSinkConfig(
        name="my-sink",
        host=args.redis_host,
        key_prefix="my:",
        key_field="id",
    ))
    (source.read_stream()
        .writeStream
        .foreachBatch(sink.make_foreach_batch_fn())
        .option("checkpointLocation", args.checkpoint_location)
        .start()
        .awaitTermination())
```

### Flink SQL

1. Create `src/flink/my_new_job.sql`
2. Follow the pattern in `orders_enrichment.sql`: source DDL, sink DDL, `BEGIN STATEMENT SET;` + `INSERT INTO ...`
3. Deploy: `make compose-up` + test in local Flink SQL client

## Adding a new sink type

1. Create `src/streaming/sinks/my_sink.py` extending `BaseSink`
2. Implement `write_batch(batch_df, batch_id) -> SinkBatchResult`
3. Register in `src/streaming/sinks/__init__.py`
4. Add unit test in `tests/unit/test_sinks_my_sink.py`
5. Update `config/sink-configs.yaml` example

## Coding style

- Format with `make format` (ruff)
- All public functions have docstrings
- Type hints throughout
- Lint with `ruff check` before push
- Use `structlog` via `get_logger`, not `print` or stdlib logging

## Working on Terraform

Modules live under `infra/terraform/modules/<name>/`. Each module:
- Has a `main.tf` with `variable`, `resource`, `output` blocks
- No semicolons in HCL
- Sensitive vars wrapped in `nonsensitive()` for `for_each` keys
- Run `terraform fmt -recursive` before commit

## Pre-commit hooks

```bash
pre-commit install
```

Enforces: ruff format + lint + detect-secrets + terraform fmt on commit.

## PR checklist

- [ ] `make ci` green locally
- [ ] Unit tests for new code
- [ ] Docs updated if public API changed
- [ ] No secrets in diff
- [ ] Terraform plan reviewed if infra changed
- [ ] CHANGELOG entry

## Questions

Open a GitHub Discussion or ping me on [LinkedIn](https://www.linkedin.com/in/sushmakl1995/).
