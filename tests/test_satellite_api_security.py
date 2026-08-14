# -*- coding: utf-8 -*-
"""
Test hồi quy bảo mật cho API vệ tinh (custom satellite points) — Pha 0.

Bối cảnh (B1/B2/B3 trong docs/BAO_CAO_DANH_GIA_TOAN_DIEN_2026-08.md):
- Trước đây `save_custom_satellite_point` và `delete_custom_satellite_point`
  nằm trong `public_endpoints` của `check_auth` → bất kỳ ai chưa đăng nhập
  cũng có thể ghi/xóa dữ liệu DB.
- Bộ test này khóa hành vi mới: endpoint GHI/XÓA yêu cầu đăng nhập (401),
  endpoint ĐỌC public vẫn hoạt động, và không endpoint nào lộ thông tin lỗi
  nội bộ ra client.
"""
import json
import unittest

from app import app
from models import CustomSatellitePoint, db


class SatelliteApiSecurityTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self._created_keys = []

    def tearDown(self):
        with app.app_context():
            for key in self._created_keys:
                CustomSatellitePoint.query.filter_by(key=key).delete()
            db.session.commit()

    def _point_payload(self, key):
        return {
            'route_id': 'route-test',
            'key': key,
            'name': 'Điểm test',
            'phone': '0912000000',
            'lat': 21.0,
            'lng': 105.0,
            'parentKey': 'parent-test',
        }

    # ── B1: Endpoint ghi/xóa yêu cầu đăng nhập ────────────────────────────

    def test_save_point_requires_login(self):
        """POST /api/custom-satellite-points khi CHƯA đăng nhập phải bị chặn."""
        with self.client.session_transaction() as sess:
            sess.clear()
        resp = self.client.post(
            '/api/custom-satellite-points',
            data=json.dumps(self._point_payload('sec_test_save')),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 401)

    def test_delete_point_requires_login(self):
        """POST /api/custom-satellite-points/delete khi CHƯA đăng nhập phải bị chặn."""
        with self.client.session_transaction() as sess:
            sess.clear()
        resp = self.client.post(
            '/api/custom-satellite-points/delete',
            data=json.dumps({'key': 'sec_test_delete'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 401)

    # ── Endpoint đọc public vẫn hoạt động (giữ nguyên tính năng) ─────────

    def test_get_points_stays_public(self):
        resp = self.client.get('/api/custom-satellite-points')
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertIn('pointsByRoute', payload)

    def test_error_responses_do_not_leak_internals(self):
        """Khi thiếu dữ liệu bắt buộc, lỗi trả về không chứa dấu vết nội bộ."""
        with self.client.session_transaction() as sess:
            sess.clear()
        resp = self.client.post(
            '/api/custom-satellite-points',
            data=json.dumps({'route_id': 'x'}),
            content_type='application/json',
        )
        # Chưa đăng nhập → 401, không phải 500 kèm chi tiết hệ thống
        self.assertEqual(resp.status_code, 401)


if __name__ == '__main__':
    unittest.main()
