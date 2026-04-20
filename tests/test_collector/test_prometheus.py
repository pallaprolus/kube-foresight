"""Tests for Prometheus collector (mocked HTTP)."""

from unittest.mock import MagicMock, patch

from kube_foresight.collector.prometheus import PrometheusCollector, _extract_deployment_name


def test_extract_deployment_name():
    assert _extract_deployment_name("api-gateway-7d5f8c6b9-xk2pq") == "api-gateway"
    assert _extract_deployment_name("my-app-abc123-xyz45") == "my-app"
    assert _extract_deployment_name("simple-pod") == "simple-pod"


def test_extract_deployment_name_multi_hyphen():
    assert _extract_deployment_name("my-cool-app-7d5f8c-xk2pq") == "my-cool-app"


def test_check_connection_success():
    collector = PrometheusCollector(url="http://localhost:9090")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": {"version": "2.45.0"}}

    with patch.object(collector._session, "get", return_value=mock_resp):
        ok, msg = collector.check_connection()
        assert ok is True
        assert "2.45.0" in msg


def test_check_connection_failure():
    collector = PrometheusCollector(url="http://localhost:9090")
    mock_resp = MagicMock()
    mock_resp.status_code = 503
    mock_resp.text = "Service Unavailable"

    with patch.object(collector._session, "get", return_value=mock_resp):
        ok, msg = collector.check_connection()
        assert ok is False
        assert "503" in msg
