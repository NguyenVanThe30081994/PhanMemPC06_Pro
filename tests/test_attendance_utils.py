# -*- coding: utf-8 -*-
import unittest
from datetime import date, datetime

from attendance_utils import build_slots_for_date, normalize_attendance_config, resolve_slot_status


class _Config:
    def __init__(self, **kwargs):
        self.name = kwargs.get('name', 'Điểm danh')
        self.mode = kwargs.get('mode', 'interval')
        self.interval_minutes = kwargs.get('interval_minutes', 120)
        self.day_start_time = kwargs.get('day_start_time', '08:00')
        self.day_end_time = kwargs.get('day_end_time', '12:00')
        self.schedule_times_json = kwargs.get('schedule_times_json', '["08:00", "11:00"]')
        self.active_weekdays_json = kwargs.get('active_weekdays_json', '[0,1,2,3,4,5,6]')
        self.early_checkin_minutes = kwargs.get('early_checkin_minutes', 15)
        self.late_allow_minutes = kwargs.get('late_allow_minutes', 60)
        self.is_active = kwargs.get('is_active', True)
        self.note = kwargs.get('note', '')


class AttendanceUtilsTests(unittest.TestCase):
    def test_interval_slots_are_generated_within_range(self):
        config = _Config(mode='interval', interval_minutes=120, day_start_time='08:00', day_end_time='12:00')
        slots = build_slots_for_date(date(2026, 6, 2), config)

        self.assertEqual([slot['slot_time'] for slot in slots], ['08:00', '10:00', '12:00'])
        self.assertEqual(slots[0]['window_start_at'].strftime('%H:%M'), '07:45')
        self.assertEqual(slots[0]['window_end_at'].strftime('%H:%M'), '09:00')

    def test_schedule_mode_uses_fixed_time_points(self):
        config = _Config(mode='schedule', schedule_times_json='["07:30", "13:15", "07:30"]')
        normalized = normalize_attendance_config(config)

        self.assertEqual(normalized['schedule_times'], ['07:30', '13:15'])

        slots = build_slots_for_date(date(2026, 6, 2), config)
        self.assertEqual([slot['slot_time'] for slot in slots], ['07:30', '13:15'])

    def test_slot_status_transitions(self):
        config = _Config(mode='schedule', schedule_times_json='["08:00"]', early_checkin_minutes=10, late_allow_minutes=15)
        slot = build_slots_for_date(date(2026, 6, 2), config)[0]

        self.assertEqual(resolve_slot_status(slot, now=datetime(2026, 6, 2, 7, 45)), 'upcoming')
        self.assertEqual(resolve_slot_status(slot, now=datetime(2026, 6, 2, 7, 55)), 'available')
        self.assertEqual(resolve_slot_status(slot, now=datetime(2026, 6, 2, 8, 16)), 'missed')
        self.assertEqual(resolve_slot_status(slot, submission=object(), now=datetime(2026, 6, 2, 8, 16)), 'completed')


if __name__ == '__main__':
    unittest.main()
