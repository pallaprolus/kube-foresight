"""Tests for YAML patch generation."""

import tempfile
from pathlib import Path

import yaml

from kube_foresight.models import ConfidenceLevel, Recommendation
from kube_foresight.recommender.patch import (
    format_cpu,
    format_memory,
    generate_patch,
    write_patches,
)


def test_format_cpu():
    assert format_cpu(0.1) == "100m"
    assert format_cpu(0.5) == "500m"
    assert format_cpu(1.0) == "1"
    assert format_cpu(2.0) == "2"
    assert format_cpu(1.5) == "1500m"
    assert format_cpu(0.01) == "10m"


def test_format_memory():
    assert format_memory(64 * 1024 * 1024) == "64Mi"
    assert format_memory(1024 * 1024 * 1024) == "1Gi"
    assert format_memory(256 * 1024 * 1024) == "256Mi"
    assert format_memory(2 * 1024 * 1024 * 1024) == "2Gi"


def _make_recommendation(**kwargs):
    defaults = dict(
        deployment_name="test-app",
        container_name="app",
        namespace="default",
        strategy="p95",
        headroom=0.2,
        current_cpu_request=1.0,
        current_cpu_limit=2.0,
        current_memory_request=1024 * 1024 * 1024,
        current_memory_limit=2 * 1024 * 1024 * 1024,
        recommended_cpu_request=0.2,
        recommended_cpu_limit=0.3,
        recommended_memory_request=256 * 1024 * 1024,
        recommended_memory_limit=384 * 1024 * 1024,
        cpu_reduction_pct=80.0,
        memory_reduction_pct=75.0,
        confidence=ConfidenceLevel.HIGH,
    )
    defaults.update(kwargs)
    return Recommendation(**defaults)


def test_generate_patch_structure():
    rec = _make_recommendation()
    patch = generate_patch(rec)
    assert patch["apiVersion"] == "apps/v1"
    assert patch["kind"] == "Deployment"
    assert patch["metadata"]["name"] == "test-app"
    assert patch["metadata"]["namespace"] == "default"
    container = patch["spec"]["template"]["spec"]["containers"][0]
    assert container["name"] == "app"
    assert container["resources"]["requests"]["cpu"] == "200m"
    assert container["resources"]["requests"]["memory"] == "256Mi"


def test_generate_patch_uses_container_name_not_deployment_name():
    rec = _make_recommendation(deployment_name="web-api", container_name="nginx")
    patch = generate_patch(rec)
    assert patch["metadata"]["name"] == "web-api"
    container = patch["spec"]["template"]["spec"]["containers"][0]
    assert container["name"] == "nginx"


def test_write_patches():
    rec = _make_recommendation()
    with tempfile.TemporaryDirectory() as tmpdir:
        files = write_patches([rec], output_dir=tmpdir)
        assert len(files) == 1
        assert Path(files[0]).exists()
        with open(files[0]) as f:
            data = yaml.safe_load(f)
        assert data["kind"] == "Deployment"
        assert data["metadata"]["name"] == "test-app"
