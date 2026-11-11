"""GET /logs/body-stats — the dashboard weight sparkline's read path."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

import quintacle_core.api as api_module
import quintacle_core.retrieval as retrieval
from quintacle_core.db import connect
from quintacle_core.nodes.logs.repository import LogsRepository


@pytest.fixture(autouse=True)
def _reset_singleton():
    retrieval._index = None
    yield
    retrieval._index = None


def test_body_stats_between_filters_metric_and_window_oldest_first(tmp_path):
    repo = LogsRepository(connect(tmp_path / "test.db"))
    repo.log_body_stat(date(2026, 10, 30), "weight", 181.0, "lb")
    repo.log_body_stat(date(2026, 9, 1), "weight", 190.0, "lb")  # outside window
    repo.log_body_stat(date(2026, 10, 20), "weight", 183.5, "lb")
    repo.log_body_stat(date(2026, 10, 25), "body fat", 18.0, "%")

    rows = repo.body_stats_between("weight", date(2026, 10, 1), date(2026, 10, 31))
    assert [(r["date"], r["value"]) for r in rows] == [("2026-10-20", 183.5), ("2026-10-30", 181.0)]


def test_body_stats_endpoint_over_http(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    client = TestClient(api_module.create_app())
    for d, v in [("2026-11-01", 182.2), ("2026-11-03", 181.6)]:
        res = client.post("/logs/body-stats", json={"date": d, "metric": "weight", "value": v, "unit": "lb"})
        assert res.status_code == 200
    res = client.get("/logs/body-stats?start=2026-10-01&end=2026-11-05&metric=Weight")
    assert res.status_code == 200
    got = [(r["date"], r["value"], r["unit"]) for r in res.json()]
    assert got == [("2026-11-01", 182.2, "lb"), ("2026-11-03", 181.6, "lb")]
    # metric defaults to weight
    assert len(client.get("/logs/body-stats?start=2026-10-01&end=2026-11-05").json()) == 2
