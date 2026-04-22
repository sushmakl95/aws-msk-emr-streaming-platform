"""Streaming platform CLI.

Unified command-line tool for:
    streaming submit-emr       - submit a Spark job to EMR on EKS or Serverless
    streaming create-topics    - create MSK topics from config/topics.yaml
    streaming describe-lag     - describe consumer group lag
    streaming validate-configs - validate MSK Connect configs
    streaming submit-flink     - deploy Flink SQL or PyFlink job to KDA
"""

from __future__ import annotations

import json
from pathlib import Path

import click

from streaming.utils.logging_config import get_logger

log = get_logger(__name__, component="cli")


@click.group()
@click.version_option("1.0.0")
def cli() -> None:
    """AWS MSK + EMR streaming platform CLI."""


# -----------------------------------------------------------------------------
# submit-emr
# -----------------------------------------------------------------------------
@cli.command()
@click.option("--runtime", type=click.Choice(["eks", "serverless"]), required=True)
@click.option("--cluster-id", help="EMR on EKS virtual cluster ID (for eks)")
@click.option("--application-id", help="EMR Serverless application ID (for serverless)")
@click.option("--role-arn", required=True, help="Execution role ARN")
@click.option("--job-name", required=True)
@click.option("--entry-point", required=True, help="S3 URI of the Python file")
@click.option("--entry-args", multiple=True, help="Args to the entry point")
@click.option("--submit-params", default="")
@click.option("--region", default="us-east-1")
def submit_emr(
    runtime: str,
    cluster_id: str | None,
    application_id: str | None,
    role_arn: str,
    job_name: str,
    entry_point: str,
    entry_args: tuple,
    submit_params: str,
    region: str,
) -> None:
    """Submit a Spark Structured Streaming job to EMR."""
    from streaming.orchestration import (
        EmrOnEksJobConfig,
        EmrServerlessJobConfig,
        submit_emr_on_eks_job,
        submit_emr_serverless_job,
    )

    if runtime == "eks":
        if not cluster_id:
            raise click.UsageError("--cluster-id required for eks")
        cfg = EmrOnEksJobConfig(
            virtual_cluster_id=cluster_id,
            job_name=job_name,
            execution_role_arn=role_arn,
            entry_point_s3=entry_point,
            entry_point_args=list(entry_args),
            spark_submit_params=submit_params,
        )
        job_id = submit_emr_on_eks_job(cfg, region=region)
    else:
        if not application_id:
            raise click.UsageError("--application-id required for serverless")
        cfg_s = EmrServerlessJobConfig(
            application_id=application_id,
            job_name=job_name,
            execution_role_arn=role_arn,
            entry_point_s3=entry_point,
            entry_point_args=list(entry_args),
            spark_submit_params=submit_params,
        )
        job_id = submit_emr_serverless_job(cfg_s, region=region)

    click.echo(f"Submitted: {job_id}")


# -----------------------------------------------------------------------------
# create-topics
# -----------------------------------------------------------------------------
@cli.command()
@click.option("--bootstrap-servers", required=True)
@click.option("--config-file", default="config/topics.yaml", type=click.Path(exists=True))
@click.option("--dry-run", is_flag=True)
def create_topics(bootstrap_servers: str, config_file: str, dry_run: bool) -> None:
    """Create MSK topics defined in config/topics.yaml."""
    import yaml  # type: ignore[import-untyped]

    data = yaml.safe_load(Path(config_file).read_text())
    topics = data.get("topics", [])

    if dry_run:
        for t in topics:
            click.echo(
                f"WOULD CREATE: {t['name']}  partitions={t.get('partitions', 3)}  "
                f"rf={t.get('replication_factor', 3)}"
            )
        return

    from streaming.lambdas.topic_creator import handler

    event = {"bootstrap_servers": bootstrap_servers, "topics": topics}
    result = handler(event, None)
    click.echo(json.dumps(result, indent=2))


# -----------------------------------------------------------------------------
# validate-configs
# -----------------------------------------------------------------------------
@cli.command()
@click.argument("config-dir", type=click.Path(exists=True))
def validate_configs(config_dir: str) -> None:
    """Validate MSK Connect property files against expected schema."""
    import subprocess
    result = subprocess.run(
        ["python", "scripts/validate_connect_configs.py", config_dir],
        check=False,
    )
    raise SystemExit(result.returncode)


# -----------------------------------------------------------------------------
# describe-lag
# -----------------------------------------------------------------------------
@cli.command()
@click.option("--bootstrap-servers", required=True)
@click.option("--group-id", required=True)
def describe_lag(bootstrap_servers: str, group_id: str) -> None:
    """Show consumer group lag for all topics."""
    from confluent_kafka.admin import AdminClient

    admin = AdminClient({
        "bootstrap.servers": bootstrap_servers,
        "security.protocol": "SASL_SSL",
        "sasl.mechanisms": "OAUTHBEARER",
        "sasl.oauthbearer.config": "aws_msk_iam",
    })

    # Simplified output; production version would aggregate per-partition offsets
    md = admin.list_groups(timeout=10)
    for group in md.valid:
        if group.id == group_id:
            click.echo(f"Group: {group.id}, state={group.state}")
            for member in group.members:
                click.echo(f"  member={member.id} host={member.client_host}")


# -----------------------------------------------------------------------------
# submit-flink
# -----------------------------------------------------------------------------
@cli.command()
@click.option("--application-name", required=True)
@click.option("--sql-file", type=click.Path(exists=True))
@click.option("--py-file", type=click.Path(exists=True))
@click.option("--region", default="us-east-1")
def submit_flink(
    application_name: str,
    sql_file: str | None,
    py_file: str | None,
    region: str,
) -> None:
    """Start a Kinesis Data Analytics for Apache Flink application."""
    import boto3

    client = boto3.client("kinesisanalyticsv2", region_name=region)
    # Start the existing application (pre-created via Terraform)
    client.start_application(ApplicationName=application_name)
    click.echo(f"Started KDA application: {application_name}")

    if sql_file:
        click.echo(f"  (SQL: {sql_file} is deployed via Terraform upload)")
    if py_file:
        click.echo(f"  (PyFlink: {py_file} is deployed via Terraform upload)")


if __name__ == "__main__":
    cli()
