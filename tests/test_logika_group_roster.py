from datetime import date
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from logika_client import LogikaClient, group_lesson_attendance, parse_attendance


class GroupRosterTests(unittest.TestCase):
    day = date(2026, 10, 17)

    def member(self, identity, status='ACTIVE', changed='2026-09-04T14:50:24.537922'):
        return {'studentId': identity, 'groupId': 77,
                'status': {'status': status, 'statusUpdateDate': changed}}

    def records(self, *states):
        return parse_attendance([{'scheduleId': 101, 'studentId': {'key': i, 'value': f'Учень {i}'}, 'state': state}
                                 for i, state in enumerate(states, 1)], 101)

    def test_expelled_and_transferred_excluded_even_when_marked_absent_or_present(self):
        members = [self.member(1), self.member(2), self.member(3, 'EXPELLED'), self.member(4, 'TRANSFERRED')]
        for state in ['NO_LESSON', 'PRESENT', 'ABSENT', 'MISSED', 'UNKNOWN']:
            with self.subTest(state=state):
                values, excluded = group_lesson_attendance(self.records('PRESENT', 'ABSENT', state, state),
                                                          members, 77, self.day)
                self.assertEqual([r['studentId']['key'] for r in values], [1, 2])
                self.assertEqual(excluded, 2)

    def test_inactive_student_missing_from_attendance_does_not_make_journal_incomplete(self):
        values, excluded = group_lesson_attendance(self.records('PRESENT', 'ABSENT'),
            [self.member(1), self.member(2), self.member(3, 'EXPELLED')], 77, self.day)
        self.assertEqual((len(values), excluded), (2, 1))

    def test_missing_active_student_still_blocks(self):
        with self.assertRaisesRegex(ValueError, 'активних учнів 2, відміток 1'):
            group_lesson_attendance(self.records('PRESENT'), [self.member(1), self.member(2)], 77, self.day)

    def test_historical_lesson_before_exit_retains_that_student(self):
        values, excluded = group_lesson_attendance(self.records('ABSENT'),
            [self.member(1, 'TRANSFERRED', '2026-10-20T12:00:00')], 77, self.day)
        self.assertEqual((len(values), excluded), (1, 0))

    def test_unknown_status_wrong_group_unknown_student_or_duplicate_roster_blocks(self):
        cases = [[self.member(1, 'NEW_UNKNOWN_STATUS')], [{**self.member(1), 'groupId': 88}],
                 [self.member(2)], [self.member(1), self.member(1)],
                 [self.member(1, changed='invalid')], {'content': []}]
        for members in cases:
            with self.subTest(members=members), self.assertRaises(ValueError):
                group_lesson_attendance(self.records('PRESENT'), members, 77, self.day)

    def test_all_inactive_produces_no_eligible_students(self):
        values, excluded = group_lesson_attendance(self.records('ABSENT', 'NO_LESSON'),
            [self.member(1, 'EXPELLED'), self.member(2, 'TRANSFERRED')], 77, self.day)
        self.assertEqual((values, excluded), ([], 2))

    def test_group_roster_api_uses_all_members_with_validated_shape(self):
        client = LogikaClient(access_token='fake')
        response = Mock(status_code=200)
        response.json.return_value = [self.member(1)]
        with patch.object(client, '_authorized_request', return_value=response) as request:
            self.assertEqual(client.get_group_students(77), [self.member(1)])
        self.assertTrue(request.call_args.args[1].endswith('/groups/77/students/all'))
        response.json.return_value = {'content': []}
        with patch.object(client, '_authorized_request', return_value=response), self.assertRaises(ValueError):
            client.get_group_students(77)

    def test_absents_button_excludes_inactive_absences(self):
        client = LogikaClient(access_token='fake')
        with patch.object(client, 'get_attendance', return_value=self.records('PRESENT', 'ABSENT', 'ABSENT')), \
             patch.object(client, 'get_group_students', return_value=[self.member(1), self.member(2), self.member(3, 'TRANSFERRED')]):
            self.assertEqual(client.get_absent_students(101, group_id=77, lesson_date=self.day), ['Учень 2'])
