# -*- coding: utf-8 -*-
"""Skeleton tests for report aggregation and export.
"""
import pytest
from app import app


def test_aggregate_endpoint_requires_auth(client):
    # unauthenticated should get 401 or 403 depending on app
    resp = client.get('/api/tasks/1/report/aggregate')
    assert resp.status_code in (401, 403)


@pytest.mark.skip("integration test - enable when DB fixtures available")
def test_aggregate_returns_expected_shape(client, login_as_admin, db_session):
    # Setup: create task, items, assignments, submissions (fixtures)
    # Call API and assert shape
    resp = client.get('/api/tasks/42/report/aggregate?cycle=2026-08')
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'items' in data and isinstance(data['items'], list)
    assert 'units' in data and isinstance(data['units'], list)


@pytest.mark.skip("integration test - export docx")
def test_export_docx_produces_file(client, login_as_admin, db_session):
    resp = client.get('/tasks/42/export-outline.docx')
    assert resp.status_code == 200
    assert resp.headers['Content-Type'].startswith('application/vnd.openxmlformats-officedocument.wordprocessingml.document')
