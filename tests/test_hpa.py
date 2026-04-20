"""Tests for HPA conflict detection."""

import pytest

from kube_foresight.hpa import HPAConflict, HPAInfo, check_hpa_conflicts


@pytest.fixture
def cpu_hpa():
    return HPAInfo(
        name="web-hpa",
        deployment_name="web-server",
        namespace="default",
        min_replicas=2,
        max_replicas=10,
        current_replicas=3,
        cpu_target_pct=80,
        memory_target_pct=None,
    )


@pytest.fixture
def memory_hpa():
    return HPAInfo(
        name="worker-hpa",
        deployment_name="worker",
        namespace="default",
        min_replicas=1,
        max_replicas=5,
        current_replicas=2,
        cpu_target_pct=None,
        memory_target_pct=70,
    )


@pytest.fixture
def dual_hpa():
    return HPAInfo(
        name="api-hpa",
        deployment_name="api-server",
        namespace="staging",
        min_replicas=3,
        max_replicas=20,
        current_replicas=5,
        cpu_target_pct=75,
        memory_target_pct=80,
    )


def test_no_hpa_no_conflict():
    conflicts = check_hpa_conflicts(
        deployment_name="nginx",
        namespace="default",
        hpas=[],
        recommended_cpu_request=0.2,
        current_cpu_request=0.5,
    )
    assert conflicts == []


def test_non_matching_hpa_no_conflict(cpu_hpa):
    conflicts = check_hpa_conflicts(
        deployment_name="other-deploy",
        namespace="default",
        hpas=[cpu_hpa],
        recommended_cpu_request=0.1,
        current_cpu_request=0.5,
    )
    assert conflicts == []


def test_cpu_reduction_triggers_conflict(cpu_hpa):
    # Reducing from 500m to 200m (ratio=2.5 > 1.5 threshold)
    conflicts = check_hpa_conflicts(
        deployment_name="web-server",
        namespace="default",
        hpas=[cpu_hpa],
        recommended_cpu_request=0.2,
        current_cpu_request=0.5,
    )
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c.conflict_type == "cpu_target"
    assert c.hpa_name == "web-hpa"
    assert "80%" in c.message
    assert "scaling" in c.message.lower()


def test_small_cpu_reduction_no_conflict(cpu_hpa):
    # Reducing from 500m to 400m (ratio=1.25 < 1.5 threshold)
    conflicts = check_hpa_conflicts(
        deployment_name="web-server",
        namespace="default",
        hpas=[cpu_hpa],
        recommended_cpu_request=0.4,
        current_cpu_request=0.5,
    )
    assert len(conflicts) == 0


def test_cpu_increase_no_conflict(cpu_hpa):
    # Increasing CPU request — no problem
    conflicts = check_hpa_conflicts(
        deployment_name="web-server",
        namespace="default",
        hpas=[cpu_hpa],
        recommended_cpu_request=0.8,
        current_cpu_request=0.5,
    )
    assert len(conflicts) == 0


def test_memory_hpa_warns(memory_hpa):
    conflicts = check_hpa_conflicts(
        deployment_name="worker",
        namespace="default",
        hpas=[memory_hpa],
        recommended_cpu_request=0.2,
        current_cpu_request=0.5,
    )
    assert len(conflicts) == 1
    assert conflicts[0].conflict_type == "memory_target"
    assert "memory" in conflicts[0].message.lower()


def test_dual_hpa_both_conflicts(dual_hpa):
    # Large CPU reduction + memory HPA → two conflicts
    conflicts = check_hpa_conflicts(
        deployment_name="api-server",
        namespace="staging",
        hpas=[dual_hpa],
        recommended_cpu_request=0.1,
        current_cpu_request=0.5,
    )
    types = {c.conflict_type for c in conflicts}
    assert "cpu_target" in types
    assert "memory_target" in types
    assert len(conflicts) == 2


def test_hpa_info_dataclass():
    hpa = HPAInfo(
        name="test",
        deployment_name="deploy",
        namespace="ns",
        min_replicas=1,
        max_replicas=5,
        current_replicas=2,
        cpu_target_pct=80,
        memory_target_pct=None,
    )
    assert hpa.name == "test"
    assert hpa.cpu_target_pct == 80
    assert hpa.memory_target_pct is None


def test_hpa_conflict_dataclass():
    conflict = HPAConflict(
        deployment_name="deploy",
        namespace="ns",
        hpa_name="hpa-1",
        conflict_type="cpu_target",
        message="Test message",
    )
    assert conflict.conflict_type == "cpu_target"
    assert conflict.message == "Test message"
