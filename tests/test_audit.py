"""Tests for the SQLite audit trail."""

import time

import pytest

from kube_foresight.audit import AuditLog


@pytest.fixture
def audit_log(tmp_path):
    return AuditLog(db_path=tmp_path / "test_audit.db")


def test_record_and_retrieve(audit_log):
    row_id = audit_log.record(
        action="apply",
        deployment_name="nginx",
        namespace="default",
        dry_run=False,
        success=True,
        message="Patch applied",
        source_ip="127.0.0.1",
        patch_yaml="apiVersion: apps/v1\n",
    )
    assert row_id >= 1
    entries = audit_log.get_recent(limit=10)
    assert len(entries) == 1
    e = entries[0]
    assert e.action == "apply"
    assert e.deployment_name == "nginx"
    assert e.namespace == "default"
    assert e.dry_run is False
    assert e.success is True
    assert e.message == "Patch applied"
    assert e.source_ip == "127.0.0.1"
    assert "apiVersion" in e.patch_yaml


def test_dry_run_recorded(audit_log):
    audit_log.record(
        action="dry-run",
        deployment_name="api-server",
        namespace="staging",
        dry_run=True,
        success=True,
        message="Dry-run OK",
    )
    entries = audit_log.get_recent()
    assert len(entries) == 1
    assert entries[0].dry_run is True
    assert entries[0].action == "dry-run"


def test_failure_recorded(audit_log):
    audit_log.record(
        action="apply",
        deployment_name="broken-deploy",
        namespace="prod",
        dry_run=False,
        success=False,
        message="403 Forbidden",
    )
    entries = audit_log.get_recent()
    assert entries[0].success is False
    assert "403" in entries[0].message


def test_get_for_deployment(audit_log):
    audit_log.record(action="apply", deployment_name="nginx", namespace="default")
    audit_log.record(action="apply", deployment_name="redis", namespace="default")
    audit_log.record(action="dry-run", deployment_name="nginx", namespace="default")

    nginx_entries = audit_log.get_for_deployment("nginx")
    assert len(nginx_entries) == 2
    for e in nginx_entries:
        assert e.deployment_name == "nginx"

    redis_entries = audit_log.get_for_deployment("redis")
    assert len(redis_entries) == 1


def test_ordering_newest_first(audit_log):
    audit_log.record(action="apply", deployment_name="first", namespace="default")
    time.sleep(0.01)
    audit_log.record(action="apply", deployment_name="second", namespace="default")

    entries = audit_log.get_recent()
    assert entries[0].deployment_name == "second"
    assert entries[1].deployment_name == "first"


def test_limit(audit_log):
    for i in range(10):
        audit_log.record(action="apply", deployment_name=f"deploy-{i}", namespace="default")
    entries = audit_log.get_recent(limit=3)
    assert len(entries) == 3


def test_timestamp_is_utc(audit_log):
    audit_log.record(action="apply", deployment_name="test", namespace="default")
    entries = audit_log.get_recent()
    assert entries[0].timestamp.tzname() == "UTC"


def test_empty_audit_log(audit_log):
    entries = audit_log.get_recent()
    assert entries == []


def test_default_values(audit_log):
    audit_log.record(action="apply", deployment_name="minimal")
    entries = audit_log.get_recent()
    e = entries[0]
    assert e.namespace == ""
    assert e.dry_run is False
    assert e.success is True
    assert e.message == ""
    assert e.source_ip == ""
    assert e.patch_yaml == ""
