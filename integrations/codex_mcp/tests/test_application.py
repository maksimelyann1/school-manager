from datetime import date
from email.parser import BytesParser
from email.policy import default
import json
from pathlib import Path
import sys
import tempfile
import unittest
from uuid import uuid4

import httpx
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from integrations.codex_mcp.application import Application, BridgeError, clean
from integrations.codex_mcp.bridge import SchoolManager
from integrations.codex_mcp.schemas import CourseLessonCreate, GroupChanges, LessonChanges, ReportSettingsChanges, ScheduledChanges, TemplateChanges, Upload
from integrations.codex_mcp.server import create_server

TEST_TMP = Path(__file__).resolve().parents[3] / 'tmp/mcp-unit-tests'
TEST_TMP.mkdir(parents=True, exist_ok=True)


def multipart(request):
    raw = b'Content-Type: ' + request.headers['content-type'].encode() + b'\r\n\r\n' + request.read()
    message = BytesParser(policy=default).parsebytes(raw)
    return {part.get_param('name', header='content-disposition'): part.get_payload(decode=True)
            for part in message.iter_parts()}


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.responses = {}
        self.error = None
        def handle(request):
            if request.url.path == '/api/assistant/status':
                return httpx.Response(200, json={'service': 'school_manager', 'assistant_api': 1})
            request.read()
            self.requests.append(request)
            if self.error:
                raise self.error
            result = self.responses.get((request.method, request.url.path), {})
            if isinstance(result, httpx.Response):
                return result
            return httpx.Response(200, json=result)
        self.client = SchoolManager(transport=httpx.MockTransport(handle))
        self.app = Application(self.client)
        self.server = create_server(self.client)

    def call(self, name, **kwargs):
        return self.server._tool_manager.get_tool(name).fn(**kwargs)

    def respond(self, method, path, body):
        self.responses[method, path] = body

    def test_all_tools_have_annotations_and_unique_schemas(self):
        tools = self.server._tool_manager._tools
        self.assertGreaterEqual(len(tools), 90)
        for name, tool in tools.items():
            with self.subTest(name=name):
                self.assertIsNotNone(tool.annotations)
                self.assertTrue(tool.description)
                self.assertEqual(tool.parameters['type'], 'object')
        self.assertFalse(tools['send_report'].annotations.readOnlyHint)
        self.assertTrue(tools['send_report'].annotations.openWorldHint)
        self.assertFalse(tools['send_message'].annotations.idempotentHint)
        self.assertTrue(tools['delete_course'].annotations.destructiveHint)

    def test_prompt_edit_cannot_toggle_autoreports_or_reveal_key(self):
        self.respond('PUT', '/api/parents-report/settings', {'prompt_template': 'Новий',
            'auto_reports_enabled': True, 'google_ai_api_key': 'private-key'})
        result = self.call('update_report_settings', changes=ReportSettingsChanges(prompt_template='Новий'))
        self.assertEqual(json.loads(self.requests[-1].content), {'prompt_template': 'Новий'})
        self.assertNotIn('google_ai_api_key', result)
        self.assertTrue(result['auto_reports_enabled'])
        self.assertEqual(len(self.requests), 1)

    def test_empty_or_unknown_settings_never_reach_backend(self):
        with self.assertRaises(BridgeError):
            self.call('update_report_settings', changes=ReportSettingsChanges())
        for payload in ({'google_ai_api_key': 'x'}, {'unrecognized': True}):
            with self.assertRaises(ValidationError):
                ReportSettingsChanges(**payload)
        self.assertEqual(self.requests, [])

    def test_report_send_preserves_omitted_defaults_and_uses_original_endpoint(self):
        self.call('send_report', lesson_id=5, lesson_date=date(2026, 10, 23))
        self.assertEqual(self.requests[-1].url.path, '/api/parents-report/send')
        self.assertEqual(json.loads(self.requests[-1].content), {'lesson_id': 5, 'lesson_date': '2026-10-23'})
        self.assertEqual(len(self.requests), 1)

    def test_report_explicit_empty_absents_and_false_test_are_not_lost(self):
        self.call('send_report', lesson_id=5, absents='', test=False, review_run_id=9)
        self.assertEqual(json.loads(self.requests[-1].content),
            {'lesson_id': 5, 'absents': '', 'test': False, 'review_run_id': 9})

    def test_resend_keeps_same_uuid_and_uses_existing_contract(self):
        identity = uuid4()
        for _ in range(2):
            self.call('resend_report', run_id=8, request_id=identity)
        self.assertEqual(self.requests[-1].url.path, '/api/parents-report/runs/8/resend')
        self.assertEqual(json.loads(self.requests[-1].content)['request_id'], str(identity))

    def test_report_validation_failure_is_not_retried_or_bypassed(self):
        self.respond('POST', '/api/parents-report/send', httpx.Response(409, json={'detail': 'Потрібна ручна перевірка відвідування'}))
        with self.assertRaisesRegex(BridgeError, '409'):
            self.call('send_report', lesson_id=5)
        self.assertEqual(len(self.requests), 1)
        self.assertNotIn('test', json.loads(self.requests[0].content))

    def test_timeout_never_retries_send_or_implies_delivery(self):
        self.error = httpx.ReadTimeout('timeout')
        with self.assertRaisesRegex(BridgeError, 'невідомий'):
            self.call('send_report', lesson_id=5)
        self.assertEqual(len(self.requests), 1)

    def test_reading_report_queue_does_not_run_sender(self):
        self.respond('GET', '/api/parents-report/pending', {'pending_lessons': [{'group_name': 'Максим'}]})
        self.call('list_pending_reports')
        self.assertEqual([r.method for r in self.requests], ['GET'])

    def test_template_text_edit_preserves_stickers_and_every_existing_file(self):
        self.respond('GET', '/api/templates/3', {'id': 3, 'name': 'Старий', 'text': 'Текст',
            'stickers': [{'file_id': 'sticker-1'}], 'files': [{'id': 10}, {'id': 11}]})
        self.call('update_template', template_id=3, changes=TemplateChanges(text='Новий'))
        fields = multipart(self.requests[-1])
        self.assertEqual(fields['name'].decode(), 'Старий')
        self.assertEqual(fields['text'].decode(), 'Новий')
        self.assertEqual(json.loads(fields['stickers']), [{'file_id': 'sticker-1'}])
        self.assertEqual(json.loads(fields['keep_file_ids']), [10, 11])

    def test_template_explicit_empty_files_and_stickers_are_respected(self):
        self.respond('GET', '/api/templates/3', {'id': 3, 'name': 'Шаблон', 'text': 'Текст',
            'stickers': [{'file_id': 'x'}], 'files': [{'id': 10}]})
        self.call('update_template', template_id=3, changes=TemplateChanges(keep_file_ids=[], stickers=[]))
        fields = multipart(self.requests[-1])
        self.assertEqual(json.loads(fields['keep_file_ids']), [])
        self.assertEqual(json.loads(fields['stickers']), [])

    def test_other_templates_file_ids_rejected_before_write(self):
        self.respond('GET', '/api/templates/3', {'id': 3, 'name': 'Шаблон', 'files': [{'id': 10}]})
        with self.assertRaises(BridgeError):
            self.call('update_template', template_id=3, changes=TemplateChanges(keep_file_ids=[99]))
        self.assertEqual([r.method for r in self.requests], ['GET'])

    def test_group_edit_keeps_telegram_id_and_other_unrequested_fields(self):
        self.respond('GET', '/api/groups/7', {'name': 'Група', 'telegram_id': '-100123',
            'lesson_time': '18:00', 'lesson_day': 'субота', 'category_id': 4})
        self.call('update_group', group_id=7, changes=GroupChanges(name='Нова'))
        payload = json.loads(self.requests[-1].content)
        self.assertEqual(payload['telegram_id'], '-100123')
        self.assertEqual(payload['category_id'], 4)
        self.assertEqual(payload['lesson_time'], '18:00')

    def test_schedule_only_existing_weekday_semantics_daily_mapping(self):
        self.respond('GET', '/api/groups/7', {'id': 7})
        self.call('create_scheduled_message', group_id=7, message='Текст', send_day='щодня', send_time='11:00')
        fields = multipart(self.requests[-1])
        self.assertEqual(fields['send_day'], b'daily')
        self.assertEqual(fields['repeat_count'], b'1')
        self.assertNotIn('send_at', fields)

    def test_arbitrary_date_and_new_schedule_fields_rejected(self):
        with self.assertRaises(BridgeError):
            self.call('create_scheduled_message', group_id=7, message='x', send_day='2026-11-14', send_time='11:00')
        with self.assertRaises(ValidationError):
            ScheduledChanges(send_at='2026-11-14T11:00:00')
        self.assertFalse(any(r.method == 'POST' for r in self.requests))

    def test_already_inactive_does_not_toggle_back_on(self):
        self.respond('GET', '/api/auto-messages/', [{'id': 2, 'is_active': 0}])
        result = self.call('set_scheduled_message_active', message_id=2, active=False)
        self.assertFalse(result['changed'])
        self.assertEqual([r.method for r in self.requests], ['GET'])

    def test_send_rejects_missing_recipient_instead_of_partial_silent_send(self):
        self.respond('GET', '/api/groups/', [{'id': 1}])
        with self.assertRaises(BridgeError):
            self.call('send_message', group_ids=[1, 999], message='Привіт')
        self.assertEqual([r.method for r in self.requests], ['GET'])

    def test_send_deduplicates_explicit_recipients_and_preserves_text(self):
        self.respond('GET', '/api/groups/', [{'id': 1}])
        self.call('send_message', group_ids=[1, 1], message='<b>Урок</b>\n\nЗавтра 🙂')
        fields = multipart(self.requests[-1])
        self.assertEqual(json.loads(fields['group_ids']), [1])
        self.assertEqual(fields['message'].decode(), '<b>Урок</b>\n\nЗавтра 🙂')

    def test_export_refuses_overwrite_and_downloads_binary(self):
        self.respond('GET', '/api/parents-report/export', httpx.Response(200, content=b'XLSX', headers={'content-type': 'application/octet-stream'}))
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as folder:
            path = Path(folder)/'export.xlsx'
            result = self.call('export_report_workbook', destination=str(path))
            self.assertEqual(Path(result['path']).read_bytes(), b'XLSX')
            with self.assertRaises(BridgeError):
                self.call('export_report_workbook', destination=str(path))
            self.assertEqual(path.read_bytes(), b'XLSX')

    def test_upload_filename_cannot_escape_or_add_headers(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as folder:
            path=Path(folder)/'file.txt'
            path.write_text('file')
            with self.assertRaises(BridgeError):
                self.client.upload('POST', '/api/templates/', {'name': 'x'}, [Upload(path=str(path), filename='../bad')])
        self.assertEqual(self.requests, [])

    def test_secret_keys_filtered_recursively(self):
        result = clean({'google_ai_api_key': 'secret', 'has_active_token': True,
                        'connection': {'access_token': 'x', 'state': 'connected'}, 'token': 'x'})
        self.assertEqual(result, {'has_active_token': True, 'connection': {'state': 'connected'}})

    def test_download_error_json_is_not_saved_as_successful_backup(self):
        self.respond('GET', '/api/system/backup', {'error': 'Базу не знайдено'})
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as folder:
            path=Path(folder)/'backup.db'
            with self.assertRaises(BridgeError):
                self.call('export_application_file', kind='database_backup', destination=str(path))
            self.assertFalse(path.exists())

    def test_filtered_runs_disclose_limited_scope_and_keep_date(self):
        self.respond('GET', '/api/parents-report/runs', [{'id': 3, 'lesson_group_name': 'Максим',
            'status': 'success', 'lesson_date': '2026-10-23'}])
        result=self.call('list_report_runs', limit=1, start=date(2026,10,23))
        self.assertTrue(result['history_may_be_truncated'])
        self.assertEqual(result['filter_scope'], 'fetched_recent_runs')

    def test_application_download_never_auto_installs(self):
        self.call('application_update', action='download')
        self.assertEqual(json.loads(self.requests[-1].content), {'auto_install': False})

    def test_creation_partial_failure_keeps_created_row_id(self):
        self.respond('POST', '/api/parents-report/schedule', {'id': 7})
        self.respond('PATCH', '/api/parents-report/schedule/7', httpx.Response(422, json={'detail': 'Перевірте час'}))
        result = self.call('create_lesson', fields=LessonChanges(group_name='Група'))
        self.assertTrue(result['partial'])
        self.assertEqual(result['lesson_id'],7)
        self.assertEqual([r.method for r in self.requests], ['POST','PATCH'])

    def test_new_course_lesson_does_not_silently_ignore_order(self):
        with self.assertRaises(ValidationError):
            CourseLessonCreate(lesson_title='Тема', row_order=4)
        self.call('create_course_lesson', course_id=3, fields=CourseLessonCreate(lesson_title='Тема'))
        self.assertEqual(json.loads(self.requests[-1].content), {'lesson_title': 'Тема'})


if __name__=='__main__':
    unittest.main()
