"""OpenLineage configuration for Flink jobs.

Flink 1.19 ships with native OpenLineage support via the `openlineage-flink`
plug-in. We enable it per-job with an env-driven config so the same binary
runs against Marquez in dev, DataHub in prod.

Usage in Flink SQL bootstrap:

    from streaming.lineage.openlineage_flink import apply_openlineage_env
    apply_openlineage_env(env, job_name="orders_enrichment")
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class OpenLineageConfig:
    url: str
    namespace: str
    job_name: str
    api_key: str | None = None

    @classmethod
    def from_env(cls, job_name: str) -> OpenLineageConfig:
        return cls(
            url=os.environ.get("OPENLINEAGE_URL", "http://marquez.internal:5000"),
            namespace=os.environ.get("OPENLINEAGE_NAMESPACE", "flink-streaming"),
            job_name=job_name,
            api_key=os.environ.get("OPENLINEAGE_API_KEY"),
        )

    def to_flink_conf(self) -> dict[str, str]:
        conf = {
            "execution.job-listeners": "io.openlineage.flink.OpenLineageFlinkJobListener",
            "openlineage.transport.type": "http",
            "openlineage.transport.url": self.url,
            "openlineage.namespace": self.namespace,
            "openlineage.job.name": self.job_name,
        }
        if self.api_key:
            conf["openlineage.transport.auth.type"] = "api_key"
            conf["openlineage.transport.auth.apiKey"] = self.api_key
        return conf


def apply_openlineage_env(env, *, job_name: str) -> None:  # pragma: no cover - Flink runtime
    """Applies OpenLineage config to a Flink StreamExecutionEnvironment."""
    cfg = OpenLineageConfig.from_env(job_name)
    flink_conf = env.get_config()
    for k, v in cfg.to_flink_conf().items():
        flink_conf.set_string(k, v)
