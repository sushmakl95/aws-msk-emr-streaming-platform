from __future__ import annotations

import pytest

from streaming.lineage.openlineage_flink import OpenLineageConfig


def test_config_from_env_defaults(monkeypatch):
    monkeypatch.delenv("OPENLINEAGE_URL", raising=False)
    monkeypatch.delenv("OPENLINEAGE_NAMESPACE", raising=False)
    monkeypatch.delenv("OPENLINEAGE_API_KEY", raising=False)
    cfg = OpenLineageConfig.from_env(job_name="orders")
    assert cfg.namespace == "flink-streaming"
    assert cfg.job_name == "orders"
    assert cfg.api_key is None


def test_config_respects_env(monkeypatch):
    monkeypatch.setenv("OPENLINEAGE_URL", "https://marquez.example.com")
    monkeypatch.setenv("OPENLINEAGE_NAMESPACE", "prod-flink")
    monkeypatch.setenv("OPENLINEAGE_API_KEY", "k")
    cfg = OpenLineageConfig.from_env(job_name="x")
    assert cfg.url == "https://marquez.example.com"
    assert cfg.namespace == "prod-flink"
    assert cfg.api_key == "k"


def test_to_flink_conf_sets_job_listener():
    cfg = OpenLineageConfig(url="http://m:5000", namespace="n", job_name="j")
    conf = cfg.to_flink_conf()
    assert conf["execution.job-listeners"] == "io.openlineage.flink.OpenLineageFlinkJobListener"
    assert conf["openlineage.transport.url"] == "http://m:5000"
    assert "openlineage.transport.auth.type" not in conf


def test_to_flink_conf_includes_auth_when_key_set():
    cfg = OpenLineageConfig(url="u", namespace="n", job_name="j", api_key="secret")
    conf = cfg.to_flink_conf()
    assert conf["openlineage.transport.auth.type"] == "api_key"
    assert conf["openlineage.transport.auth.apiKey"] == "secret"


@pytest.mark.parametrize("job", ["orders_enrichment", "cdc_fan_out", "sessionize"])
def test_job_name_roundtrip(job):
    cfg = OpenLineageConfig.from_env(job_name=job)
    assert cfg.to_flink_conf()["openlineage.job.name"] == job
