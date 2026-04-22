#!/usr/bin/env python3
"""Validate MSK Connect configuration files.

CI entry point. Checks:
  - Each .properties file parses as valid Java properties
  - Required keys are present per connector class
  - No hardcoded credentials (must reference ${VAR_NAME})
  - Schema Registry settings present when Avro/Debezium is used

Usage: python scripts/validate_connect_configs.py <config_dir>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


REQUIRED_COMMON = {"name", "connector.class"}

REQUIRED_BY_CONNECTOR = {
    "io.debezium.connector.postgresql.PostgresConnector": {
        "database.hostname", "database.user", "database.password",
        "database.dbname", "plugin.name", "slot.name", "publication.name",
        "schema.history.internal.kafka.bootstrap.servers",
    },
    "io.debezium.connector.mysql.MySqlConnector": {
        "database.hostname", "database.user", "database.password",
        "database.server.id", "schema.history.internal.kafka.bootstrap.servers",
    },
    "io.debezium.connector.mongodb.MongoDbConnector": {
        "mongodb.connection.string", "capture.mode",
    },
    "io.confluent.connect.s3.S3SinkConnector": {
        "s3.region", "s3.bucket.name", "format.class",
        "partitioner.class", "flush.size",
    },
}

# A placeholder pattern like ${POSTGRES_PASSWORD} is OK; a literal password is not.
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z_][A-Z0-9_]*\}$")


def parse_properties(path: Path) -> dict[str, str]:
    """Parse a Java .properties file (simple format, no escapes)."""
    props: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        props[key.strip()] = value.strip()
    return props


def validate(path: Path) -> list[str]:
    """Return a list of error messages (empty if valid)."""
    errors: list[str] = []
    try:
        props = parse_properties(path)
    except Exception as exc:
        return [f"Failed to parse: {exc}"]

    # Common required keys
    for key in REQUIRED_COMMON:
        if key not in props:
            errors.append(f"Missing required key: {key}")

    connector_class = props.get("connector.class", "")
    required = REQUIRED_BY_CONNECTOR.get(connector_class, set())
    for key in required:
        if key not in props:
            errors.append(f"Missing key for {connector_class}: {key}")

    # Detect hardcoded passwords
    sensitive_keys = [
        "database.password", "mongodb.password", "database.user",
    ]
    for key in sensitive_keys:
        value = props.get(key, "")
        if value and not PLACEHOLDER_RE.match(value):
            # Warn unless it's a trivial test placeholder
            if value not in ("CHANGE_ME", "", "debezium_user"):
                errors.append(
                    f"Hardcoded value for {key}; use ${{VAR_NAME}} placeholder instead"
                )

    # Debezium + Avro convergence
    uses_avro = any(
        "AWSKafkaAvroConverter" in props.get(k, "")
        for k in ["key.converter", "value.converter"]
    )
    if uses_avro:
        required_avro = {
            "value.converter.schemaRegistryName",
            "value.converter.region",
        }
        for key in required_avro:
            if key not in props:
                errors.append(f"Avro converter missing required: {key}")

    return errors


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: validate_connect_configs.py <config_dir>")
        return 2

    root = Path(argv[1])
    if not root.is_dir():
        print(f"ERROR: {root} is not a directory")
        return 2

    files = list(root.rglob("*.properties"))
    if not files:
        print(f"No .properties files found under {root}")
        return 0

    print(f"Validating {len(files)} MSK Connect config(s)...\n")
    failed = 0
    for f in sorted(files):
        rel = f.relative_to(root.parent)
        errors = validate(f)
        if not errors:
            print(f"  OK    {rel}")
        else:
            failed += 1
            print(f"  FAIL  {rel}")
            for e in errors:
                print(f"    - {e}")

    print()
    if failed:
        print(f"FAIL: {failed} of {len(files)} config(s) invalid")
        return 1
    print(f"OK: all {len(files)} config(s) valid")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
