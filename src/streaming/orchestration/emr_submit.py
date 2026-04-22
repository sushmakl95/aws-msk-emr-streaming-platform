"""EMR job submission — EMR on EKS and EMR Serverless.

Wrapping AWS EMR APIs so the CLI + Step Functions can submit jobs uniformly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import boto3

from streaming.utils.logging_config import get_logger

log = get_logger(__name__, component="orchestration.emr")


@dataclass
class EmrOnEksJobConfig:
    """Config for an EMR on EKS Spark job submission."""
    virtual_cluster_id: str
    job_name: str
    execution_role_arn: str
    release_label: str = "emr-7.0.0-latest"
    entry_point_s3: str = ""
    entry_point_args: list[str] | None = None
    spark_submit_params: str = ""
    monitoring_config: dict | None = None


def submit_emr_on_eks_job(
    cfg: EmrOnEksJobConfig,
    region: str = "us-east-1",
) -> str:
    """Submit a Spark job to EMR on EKS. Returns the job run id."""
    client = boto3.client("emr-containers", region_name=region)

    spark_submit = {
        "sparkSubmitParameters": cfg.spark_submit_params,
    }
    job_driver = {
        "sparkSubmitJobDriver": {
            "entryPoint": cfg.entry_point_s3,
            "entryPointArguments": cfg.entry_point_args or [],
            **spark_submit,
        }
    }

    monitoring = cfg.monitoring_config or {
        "cloudWatchMonitoringConfiguration": {
            "logGroupName": f"/aws/emr-containers/{cfg.virtual_cluster_id}",
            "logStreamNamePrefix": cfg.job_name,
        },
    }

    resp = client.start_job_run(
        name=cfg.job_name,
        virtualClusterId=cfg.virtual_cluster_id,
        executionRoleArn=cfg.execution_role_arn,
        releaseLabel=cfg.release_label,
        jobDriver=job_driver,
        configurationOverrides={"monitoringConfiguration": monitoring},
    )
    job_id = resp["id"]
    log.info("emr_on_eks_job_submitted", job_id=job_id, job_name=cfg.job_name)
    return job_id


@dataclass
class EmrServerlessJobConfig:
    """Config for an EMR Serverless job submission."""
    application_id: str
    job_name: str
    execution_role_arn: str
    entry_point_s3: str = ""
    entry_point_args: list[str] | None = None
    spark_submit_params: str = ""


def submit_emr_serverless_job(
    cfg: EmrServerlessJobConfig,
    region: str = "us-east-1",
) -> str:
    """Submit a Spark job to EMR Serverless. Returns the job run id."""
    client = boto3.client("emr-serverless", region_name=region)

    job_driver = {
        "sparkSubmit": {
            "entryPoint": cfg.entry_point_s3,
            "entryPointArguments": cfg.entry_point_args or [],
            "sparkSubmitParameters": cfg.spark_submit_params,
        }
    }

    resp = client.start_job_run(
        name=cfg.job_name,
        applicationId=cfg.application_id,
        executionRoleArn=cfg.execution_role_arn,
        jobDriver=job_driver,
        configurationOverrides={
            "monitoringConfiguration": {
                "cloudWatchLoggingConfiguration": {
                    "enabled": True,
                    "logGroupName": f"/aws/emr-serverless/{cfg.application_id}",
                },
            },
        },
    )
    job_id = resp["jobRunId"]
    log.info("emr_serverless_job_submitted", job_id=job_id, job_name=cfg.job_name)
    return job_id


def get_job_status(
    job_run_id: str,
    virtual_cluster_id: str | None = None,
    application_id: str | None = None,
    region: str = "us-east-1",
) -> dict:
    """Poll a job's status. Returns the raw describe response."""
    if virtual_cluster_id:
        client = boto3.client("emr-containers", region_name=region)
        return client.describe_job_run(id=job_run_id, virtualClusterId=virtual_cluster_id)
    if application_id:
        client = boto3.client("emr-serverless", region_name=region)
        return client.get_job_run(applicationId=application_id, jobRunId=job_run_id)
    raise ValueError("Must provide virtual_cluster_id or application_id")


def describe_running_jobs(
    virtual_cluster_id: str | None = None,
    application_id: str | None = None,
    region: str = "us-east-1",
) -> list[dict]:
    """List all currently-running jobs."""
    if virtual_cluster_id:
        client = boto3.client("emr-containers", region_name=region)
        resp = client.list_job_runs(
            virtualClusterId=virtual_cluster_id,
            states=["PENDING", "SUBMITTED", "RUNNING"],
        )
        return resp.get("jobRuns", [])
    if application_id:
        client = boto3.client("emr-serverless", region_name=region)
        resp = client.list_job_runs(
            applicationId=application_id,
            states=["PENDING", "SCHEDULED", "RUNNING"],
        )
        return resp.get("jobRuns", [])
    return []


def save_submission_manifest(
    job_id: str,
    cfg: EmrOnEksJobConfig | EmrServerlessJobConfig,
    s3_bucket: str,
    region: str = "us-east-1",
) -> str:
    """Persist job submission metadata to S3 for audit."""
    s3 = boto3.client("s3", region_name=region)
    key = f"manifests/{cfg.job_name}/{job_id}.json"
    manifest = {
        "job_id": job_id,
        "job_name": cfg.job_name,
        "entry_point": cfg.entry_point_s3,
        "args": cfg.entry_point_args,
    }
    s3.put_object(
        Bucket=s3_bucket,
        Key=key,
        Body=json.dumps(manifest, indent=2).encode("utf-8"),
        ContentType="application/json",
    )
    return f"s3://{s3_bucket}/{key}"
