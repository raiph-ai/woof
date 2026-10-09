import http.client
import json
import os
from pathlib import Path
import sqlite3
import stat
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import backend


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.home = Path(self.temp.name)
        self.web = self.home / 'web'
        self.web.mkdir()
        (self.web / 'index.html').write_text('<!doctype html><h1>Nudge</h1>')
        self.hermes = self.home / 'hermes-fixture'
        self.hermes.write_text('fixture executable; CLI calls mocked')
        self.hermes.chmod(0o700)
        self.app = backend.Companion(self.home, hermes=self.hermes, web=self.web, profile='default')
        self.server = backend.Server(self.app, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.app.close()
        self.temp.cleanup()

    def http(self, method='GET', path='/api/state', data=None, auth=True, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        hs = {'Authorization': 'Bearer ' + self.app.token} if auth else {}
        if data is not None:
            hs['Content-Type'] = 'application/json'
        hs.update(headers or {})
        connection.request(method, path, body=json.dumps(data) if data is not None else None, headers=hs)
        response = connection.getresponse()
        result = (response.status, dict(response.getheaders()), response.read())
        connection.close()
        return result

    def cron_store(self, jobs):
        (self.home / 'cron').mkdir(exist_ok=True)
        (self.home / 'cron' / 'jobs.json').write_text(json.dumps({'jobs': jobs}))

    def wait_request(self, rid):
        for _ in range(100):
            req = next(r for r in self.app.state()['requests'] if r['id'] == rid)
            if req['status'] in ('completed', 'error'):
                return req
            time.sleep(0.01)
        self.fail('request did not finish')

    def history_fixture(self):
        path = self.home / 'state.db'
        with sqlite3.connect(path, factory=backend.ClosingConnection) as db:
            db.executescript('CREATE TABLE sessions(id TEXT PRIMARY KEY, source TEXT); '
                             'CREATE TABLE messages(id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, '
                             'content TEXT, timestamp REAL, active INTEGER);')
            for sid, source in [('real', 'cli'), ('self', 'nudge-request'), ('analysis', 'companion-analysis')]:
                db.execute('INSERT INTO sessions VALUES (?,?)', (sid, source))
            rows = [(1, 'real', 'user', 'Help review this project', 1, 1),
                    (2, 'real', 'assistant', 'Assistant chatter', 2, 1),
                    (3, 'self', 'user', 'Exclude self', 3, 1),
                    (4, 'real', 'user', json.dumps([{'type': 'text', 'text': 'Plan a follow up'},
                        {'type': 'image_url', 'image_url': {'url': 'secret'}}]), 4, 1),
                    (5, 'analysis', 'user', 'Exclude analysis', 5, 1),
                    (6, 'real', 'user', 'Inactive request', 6, 0)]
            db.executemany('INSERT INTO messages VALUES (?,?,?,?,?,?)', rows)
        return path

    def fresh_history_fixture(self):
        path = self.history_fixture()
        with sqlite3.connect(path, factory=backend.ClosingConnection) as db:
            db.execute('UPDATE messages SET timestamp=timestamp+?', (time.time() - 10,))
        return path

    def test_state_indexed_latest_rows_provenance_and_fresh_readback(self):
        with self.app.connect() as db:
            db.executemany('INSERT INTO notifications VALUES (?,?,?,?,0,NULL)',
                           [(f'fixture-{i}', 'Fixture', 'Body', f'{i:06}') for i in range(400)])
            db.executemany('INSERT INTO requests VALUES (?,?,?,?,?)',
                           [(f'fixture-{i}', 'Fixture', 'completed', 'Body', f'{i:06}') for i in range(120)])
            db.execute('INSERT INTO message_provenance VALUES (?,?,?,?,?)',
                       ('fixture-399', 'session', 'message', 'cli', 123))
            db.execute('INSERT INTO message_provenance VALUES (?,?,?,?,?)',
                       ('fixture-398', None, None, None, None))
            for table in ('notifications', 'requests'):
                plan = db.execute(f'EXPLAIN QUERY PLAN SELECT * FROM {table} ORDER BY created_at DESC LIMIT 100').fetchall()
                self.assertTrue(any(table + '_created_at' in r[3] for r in plan))
        state = json.loads(self.http()[2])
        self.assertEqual(len(state['notifications']), 300)
        self.assertEqual(len(state['requests']), 100)
        self.assertEqual(state['notifications'][0]['id'], 'fixture-399')
        self.assertEqual(state['requests'][0]['id'], 'fixture-119')
        self.assertEqual(state['notifications'][0]['message_id'], 'message')
        self.assertIn('session_id', state['notifications'][1])
        self.assertIsNone(state['notifications'][1]['session_id'])
        self.assertNotIn('session_id', state['notifications'][2])
        self.assertNotIn('provenance_id', state['notifications'][0])
        with self.app.connect() as db:
            db.execute("UPDATE notifications SET body='Changed',read=1 WHERE id='fixture-399'")
            db.execute("UPDATE message_provenance SET source='slack' WHERE notification_id='fixture-399'")
        newest = json.loads(self.http()[2])['notifications'][0]
        self.assertEqual((newest['body'], newest['read'], newest['source']), ('Changed', True, 'slack'))
        with self.app.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM notifications').fetchone()[0], 400)
            self.assertEqual(db.execute('SELECT count(*) FROM requests').fetchone()[0], 120)

    def test_coaching_settings_contract_auth_validation_and_no_call(self):
        self.assertEqual(self.http(path='/api/coaching-settings', auth=False)[0], 401)
        self.assertEqual(self.http('POST', '/api/coaching-settings', {}, auth=False)[0], 401)
        defaults = json.loads(self.http(path='/api/coaching-settings')[2])
        self.assertEqual(set(defaults), {'interval_minutes', 'timezone', 'last_checked_at', 'next_check_at', 'busy', 'last_error'})
        self.assertEqual(defaults['interval_minutes'], 120)
        self.assertEqual(defaults['timezone'], 'UTC')
        self.assertIsNone(defaults['last_checked_at'])
        with patch.object(self.app, 'chat') as chat:
            for value in (14, 125, 1441, True, 120.0, '120', None):
                self.assertEqual(self.http('POST', '/api/coaching-settings', {'interval_minutes': value})[0], 400)
            for tz in ('Bad/Zone', '', None, 12):
                self.assertEqual(self.http('POST', '/api/coaching-settings', {'interval_minutes': 15, 'timezone': tz})[0], 400)
            for minutes in (15, 1440):
                code, _, body = self.http('POST', '/api/coaching-settings', {'interval_minutes': minutes, 'timezone': 'America/Los_Angeles'})
                self.assertEqual(code, 200)
                saved = json.loads(body)
                self.assertEqual(saved, json.loads(self.http(path='/api/coaching-settings')[2]))
                self.assertEqual(saved['interval_minutes'], minutes)
            self.assertEqual(self.app.coaching_save({'interval_minutes': 120})['timezone'], 'America/Los_Angeles')
            chat.assert_not_called()
        self.assertEqual(self.app.state()['status']['coaching'], self.app.coaching_settings())

    def test_coaching_cadence_restart_interval_recalculation_and_quiet(self):
        with self.app.connect() as db:
            anchor = float(db.execute("SELECT value FROM meta WHERE key='coaching_anchor'").fetchone()[0])
        with patch.object(backend.time, 'time', return_value=anchor + 7199):
            self.assertEqual(self.app.refresh(automatic=True), {'status': 'not-due'})
        with patch.object(backend.time, 'time', return_value=anchor + 7200), patch.object(self.app, 'chat') as chat:
            request = self.app.refresh(automatic=True)
            outcome = self.wait_request(request['id'])
            self.assertEqual(outcome['status'], 'completed')
            self.assertIn('Quiet window', outcome['body'])
            self.assertEqual(self.app.refresh(automatic=True), {'status': 'not-due'})
            chat.assert_not_called()
        with self.app.connect() as db:
            attempt = float(db.execute("SELECT value FROM meta WHERE key='coaching_attempt'").fetchone()[0])
        settings = self.app.coaching_save({'interval_minutes': 15})
        self.assertAlmostEqual(backend.datetime.fromisoformat(settings['next_check_at']).timestamp(), attempt + 900, places=5)
        app2 = backend.Companion(self.home, hermes=self.hermes, profile='default')
        try:
            self.assertEqual(app2.coaching_settings(), settings)
            with patch.object(backend.time, 'time', return_value=attempt + 899):
                self.assertEqual(app2.refresh(automatic=True)['status'], 'not-due')
            with patch.object(backend.time, 'time', return_value=attempt + 900), patch.object(app2, 'chat') as chat:
                rid = app2.refresh(automatic=True)['id']
                app2.pool.shutdown(wait=True)
                self.assertEqual(app2.state()['requests'][0]['id'], rid)
                chat.assert_not_called()
            self.assertEqual(app2.state()['notifications'], [])
        finally:
            app2.close()

    def test_coaching_busy_immediate_manual_and_slots_failure_checkpoint(self):
        self.fresh_history_fixture()
        entered, release = threading.Event(), threading.Event()
        def reflect(*args, **kwargs):
            entered.set()
            release.wait(3)
            return '{"proactive":[],"ideas":[]}', None
        with patch.object(self.app, 'chat', side_effect=reflect) as chat:
            status, _, body = self.http('POST', '/api/refresh', {})
            self.assertEqual(status, 202)
            self.assertTrue(entered.wait(2))
            self.assertEqual(self.app.refresh(), {'status': 'running'})
            state = self.app.state()
            self.assertTrue(state['status']['analysis_busy'])
            self.assertTrue(state['status']['coaching']['busy'])
            release.set()
            self.wait_request(json.loads(body)['id'])
            chat.assert_called_once()
        for _ in range(3):
            self.assertTrue(self.app.slots.acquire(False))
        try:
            with self.assertRaisesRegex(ValueError, 'busy'):
                self.app.refresh()
            self.assertFalse(self.app.analysis_busy)
            self.assertIsNotNone(self.app.coaching_settings()['last_error'])
            self.assertEqual(self.app.refresh(automatic=True)['status'], 'not-due')
        finally:
            for _ in range(3):
                self.app.slots.release()

    def test_coaching_recent_overnight_bounded_sources_and_noise_before_limit(self):
        path = self.history_fixture()
        end = backend.datetime.fromisoformat('2030-02-02T17:00:00+00:00').timestamp()
        self.app.coaching_save({'interval_minutes': 120, 'timezone': 'America/Los_Angeles'})
        with sqlite3.connect(path, factory=backend.ClosingConnection) as db:
            db.execute('UPDATE messages SET timestamp=?', (end - 37 * 3600,))
            db.execute('UPDATE messages SET timestamp=? WHERE id IN (1,2)', (end - 12 * 3600,))
            db.execute('UPDATE messages SET timestamp=? WHERE id=2', (end - 3600,))
            for mid in range(10, 70):
                db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?)', (mid, 'real', 'user', 'Context ' * 200, end - mid, 1))
            db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?)', (100, 'real', 'user', 'Future', end + 1, 1))
        self.managed_fixture()
        todo = self.app.todo_save({'title': 'Project experiment', 'details': 'x' * 4000, 'due_date': '2035-01-01'})['todo']
        self.assertEqual(self.app.state()['todos'], [todo])
        with patch.object(backend, 'now', return_value=backend.datetime.fromtimestamp(end - 3600, backend.timezone.utc).isoformat()):
            with self.app.connect() as db:
                for nid, jid in [('normal-result', None), ('owned-result', 'owned'), ('todo-note', todo['id']), ('foreign', 'other')]:
                    self.app._notify(db, nid, 'Meaningful result', 'Synthetic meaningful result', jid)
                self.app._notify(db, 'interval-result', '[heartbeat-style] Project check', 'Useful finding', 'owned')
                for i in range(30):
                    self.app._notify(db, 'noise-' + str(i), 'Global watchdog heartbeat', 'Nothing changed')
        with patch.object(backend.time, 'time', return_value=end):
            context = self.app.coach_context()
        self.assertEqual({n['id'] for n in context['notifications']}, {'normal-result', 'owned-result', 'todo-note', 'interval-result'})
        self.assertIn(1, [h['message_id'] for h in context['history']])
        self.assertLessEqual(len(json.dumps(context)), 24000)
        self.assertLessEqual(len(context['history']), 24)
        self.assertEqual(context['previous_evening'], '2030-02-01T18:00:00-08:00')
        self.assertNotIn(100, [h['message_id'] for h in context['history']])
        # Sparse history still includes the previous night, never stale anchors.
        with sqlite3.connect(path, factory=backend.ClosingConnection) as db:
            db.execute('DELETE FROM messages WHERE id>=10')
        before = path.read_bytes()
        with patch.object(backend.time, 'time', return_value=end):
            context = self.app.coach_context()
        self.assertEqual([h['message_id'] for h in context['history']], [1])
        self.assertEqual(context['history'][0]['assistant_reply']['message_id'], 2)
        self.assertEqual(context['history'][0]['assistant_reply']['timestamp'], end - 3600)
        self.assertEqual(path.read_bytes(), before)

    def test_coaching_exact_multisource_provenance_and_no_repair(self):
        self.fresh_history_fixture()
        todo = self.app.todo_save({'title': 'Project research', 'due_date': '2035-01-01'})['todo']
        with self.app.connect() as db:
            self.app._notify(db, 'ordinary', 'Project result', 'Synthetic finding')
        refs = [{'kind': 'conversation', 'session_id': 'real', 'message_id': 2},
                {'kind': 'notification', 'id': 'ordinary'}, {'kind': 'todo', 'id': todo['id']}]
        card = {'title': 'Compare exploratory angles', 'body': 'Possibility, not an obligation',
                'prompt': 'Research options with normal approvals', 'provenance': refs}
        generated = {'proactive': [], 'ideas': [card]}
        with patch.object(self.app, 'chat', return_value=(json.dumps(generated), None)) as chat, patch.object(self.app, 'request') as request:
            self.wait_request(self.app.refresh()['id'])
            self.assertTrue(chat.call_args.kwargs['analysis'])
            request.assert_not_called()
        saved = self.app.state()['ideas']
        self.assertIn('notification=ordinary', saved[0]['source'])
        self.assertIn('todo=' + todo['id'], saved[0]['source'])
        context = self.app.coach_context()
        for ref in ({'kind': 'conversation', 'session_id': 'wrong', 'message_id': 2},
                    {'kind': 'notification', 'id': todo['id']}, {'kind': 'todo', 'id': 'ordinary'},
                    {'kind': 'todo', 'id': 'invented'}, {'kind': 'tool', 'id': 'ordinary'}):
            with self.assertRaises(ValueError):
                backend.Companion.validate_coaching({'proactive': [{**card, 'provenance': [ref]}], 'ideas': []}, context)
        with patch.object(self.app, 'chat', side_effect=RuntimeError('private provider error')):
            outcome = self.wait_request(self.app.refresh()['id'])
        self.assertEqual(outcome['status'], 'error')
        self.assertEqual(self.app.state()['ideas'], saved)
        self.assertNotIn('private provider error', self.app.coaching_settings()['last_error'])
        self.assertEqual([n['id'] for n in self.app.state()['notifications']], ['ordinary'])
        app2 = backend.Companion(self.home, hermes=self.hermes, profile='default')
        try:
            self.assertEqual(app2.state()['ideas'], saved)
            self.assertIsNotNone(app2.coaching_settings()['last_error'])
        finally:
            app2.close()

    def test_coaching_budget_is_bounded_without_changing_other_analysis(self):
        for prompt, budget, timeout in [('Read-only individual coaching reflection. DATA:{}', '120', 150),
                                        ('Read-only probe', '60', 90)]:
            with patch.object(self.app, 'cli', side_effect=RuntimeError('controlled budget probe')) as cli:
                with self.assertRaises(RuntimeError):
                    self.app.chat(prompt, analysis=True)
                args, _, actual_timeout = cli.call_args.args
                self.assertEqual(args[args.index('--run-budget') + 1], budget)
                self.assertEqual(actual_timeout, timeout)
                self.assertEqual(args[args.index('-t') + 1], 'none')
                self.assertNotIn('--yolo', args)
                if budget == '120':
                    self.assertEqual(args[args.index('--reasoning') + 1], 'low')
                else:
                    self.assertNotIn('--reasoning', args)

    def test_coaching_real_subprocess_tools_disabled_adapter(self):
        import sys
        if os.name == 'nt':
            self.skipTest('Executable script fixture uses a POSIX shebang')
        self.hermes.write_text('#!' + sys.executable + '\nimport json,sys\n'
                              'a=sys.argv\nassert a[a.index("-t")+1]=="none"\n'
                              'assert "--ignore-rules" in a\nassert "--yolo" not in a\n'
                              'assert a[a.index("--max-turns")+1]=="1"\n'
                              'assert sys.stdin.read()=="Read-only probe"\n'
                              'print(json.dumps({"type":"result","text":"OK","exit_code":0}))\n')
        self.assertEqual(self.app.chat('Read-only probe', analysis=True), ('OK', None))

    def test_coaching_automatic_model_failure_durable_restart_and_health_merge(self):
        self.fresh_history_fixture()
        context = self.app.coach_context()
        card = {'title': 'Optional project experiment', 'body': 'A possibility based on the project',
                'prompt': 'Draft experiment options', 'source_session': 'real', 'message_id': 1}
        saved = backend.Companion.validate_coaching({'proactive': [card], 'ideas': []}, context)
        with self.app.connect() as db:
            db.execute("INSERT OR REPLACE INTO meta VALUES ('suggestions',?)", (json.dumps(saved),))
            db.execute("UPDATE meta SET value=? WHERE key='coaching_anchor'", (str(time.time() - 7201),))
            db.execute('INSERT INTO health_issues VALUES (?,?,?,?,?,0)', ('health-existing', 'Observed issue', 'A real observation', 'Review safely', 'settings'))
        with patch.object(self.app, 'chat', side_effect=RuntimeError('provider failed')) as chat, patch.object(self.app, 'request') as request:
            outcome = self.wait_request(self.app.refresh(automatic=True)['id'])
            self.assertEqual(outcome['status'], 'error')
            self.assertEqual(self.app.refresh(automatic=True)['status'], 'not-due')
            chat.assert_called_once()
            request.assert_not_called()
        state = self.app.state()
        self.assertEqual(state['proactive'][1:], saved['proactive'])
        self.assertEqual(state['proactive'][0]['id'], 'health-existing')
        self.assertEqual(state['notifications'], [])
        app2 = backend.Companion(self.home, hermes=self.hermes, profile='default')
        try:
            with patch.object(app2, 'chat') as chat:
                self.assertEqual(app2.refresh(automatic=True)['status'], 'not-due')
                chat.assert_not_called()
            self.assertEqual(app2.state()['proactive'], state['proactive'])
            self.assertIsNotNone(app2.coaching_settings()['last_error'])
        finally:
            app2.close()

    def test_coaching_interrupted_restart_no_spam_or_replay(self):
        stamp = time.time()
        with self.app.connect() as db:
            db.execute('INSERT INTO requests VALUES (?,?,?,?,?)', ('interrupted-coach', 'Conversation suggestions', 'running', '', backend.now()))
            db.execute("INSERT INTO meta VALUES ('coaching_attempt',?)", (str(stamp),))
        app2 = backend.Companion(self.home, hermes=self.hermes, profile='default')
        try:
            self.assertEqual(app2.state()['requests'][0]['status'], 'error')
            self.assertEqual(app2.state()['notifications'], [])
            self.assertFalse(app2.coaching_settings()['busy'])
            self.assertIn('interrupted', app2.coaching_settings()['last_error'])
            self.assertEqual(app2.refresh(automatic=True)['status'], 'not-due')
        finally:
            app2.close()

    def test_coaching_bridge_loop_runs_separate_health_and_coach(self):
        with patch.object(self.app.stop, 'wait', side_effect=[False, True]), \
                patch.object(self.app, 'poll') as poll, \
                patch.object(self.app, 'health_check') as health, \
                patch.object(self.app, 'refresh') as coach:
            self.app.polling()
        poll.assert_called_once_with()
        health.assert_called_once_with(daily=True)
        coach.assert_called_once_with(automatic=True)

    def test_new_routes_authentication(self):
        self.assertEqual(self.http(path='/api/todos', auth=False)[0], 401)
        for route in ('optimize', 'todo-save', 'todo-action', 'health-check', 'health-action'):
            self.assertEqual(self.http('POST', '/api/' + route, {}, auth=False)[0], 401)

    def test_optimize_analysis_contract_no_mutations(self):
        payload = {'title': 'Inbox review', 'prompt': 'Check connected inbox', 'schedule': 'every 2h', 'mode': 'cron'}
        answer = {**payload, 'prompt': 'Only report new actionable inbox findings.',
                  'alert_when': 'New actionable mail', 'summary': 'Narrow alerts to useful findings'}
        with self.app.connect() as db:
            before = list(db.iterdump())
        with patch.object(self.app, 'cli', return_value=json.dumps({'type': 'result', 'text': json.dumps(answer), 'exit_code': 0})) as cli:
            result = self.app.optimize(payload)
        self.assertEqual(result['method'], 'agent')
        self.assertEqual(result['schedule'], payload['schedule'])
        self.assertIn('[SILENT]', result['prompt'])
        args, prompt, timeout = cli.call_args.args
        self.assertEqual(args[args.index('-t') + 1], 'none')
        self.assertIn('--ignore-rules', args)
        self.assertEqual(timeout, 90)
        for phrase in ('sender', 'subject', 'unchanged previously reported', 'Permission', 'Never send, delete', 'untrusted'):
            self.assertIn(phrase, prompt)
        with self.app.connect() as db:
            self.assertEqual(list(db.iterdump()), before)

    def test_optimize_fail_closed_and_owned_sample_only(self):
        payload = {'title': 'Inbox', 'prompt': 'Read inbox', 'schedule': '30m', 'mode': 'heartbeat'}
        with patch.object(self.app, 'chat', side_effect=RuntimeError('Provider unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'Notification optimization failed'):
                self.app.optimize(payload)
        with patch.object(self.app, 'chat') as chat:
            with self.assertRaises(LookupError):
                self.app.optimize({**payload, 'id': 'unrelated'})
            chat.assert_not_called()
        self.managed_fixture()
        self.app.custom()  # migrate fixture ownership, not during optimization
        with self.app.connect() as db:
            self.app._notify(db, 'sample', 'Inbox', '# Cron Job\n## Prompt\nprivate boilerplate\n## Response\nSynthetic finding', 'owned')
            self.app._notify(db, 'foreign', 'Other', 'foreign-secret', 'other')
        answer = {**payload, 'alert_when': 'New findings', 'summary': 'Less noise'}
        with patch.object(self.app, 'chat', return_value=(json.dumps(answer), None)) as chat:
            self.app.optimize({**payload, 'id': 'owned'})
            supplied = chat.call_args.args[0].split('RECENT RESULTS:\n')[1]
            self.assertIn('Synthetic finding', supplied)
            self.assertNotIn('private boilerplate', supplied)
            self.assertNotIn('foreign-secret', supplied)
        for invalid in ({**answer, 'schedule': 'every 9h'}, {**answer, 'prompt': ''}, {'summary': 'oops'}):
            with patch.object(self.app, 'chat', return_value=(json.dumps(invalid), None)):
                with self.assertRaises(RuntimeError):
                    self.app.optimize(payload)

    def test_owned_outputs_response_silence_duplicates_and_failures(self):
        job = self.managed_fixture()
        self.cron_store([job, dict(job, id='unrelated')])
        bodies = ['WOOF_NO_CHANGE', '[SILENT]', 'Synthetic sender: action A',
                  'Synthetic sender:  action A', 'Synthetic sender: action B',
                  'Permission denied', 'Permission denied', 'WOOF_NO_CHANGE plus a problem']
        for jid in ('owned', 'unrelated'):
            output = self.home / 'cron' / 'output' / jid
            output.mkdir(parents=True)
            for i, body in enumerate(bodies):
                (output / f'{i:02}.md').write_text('# Cron Job\n## Prompt\nInjected instructions\n## Response\n' + body)
        self.app.poll()
        state = self.app.state()
        notes = [n for n in state['notifications'] if n.get('job_id') == 'owned' and not n['id'].startswith('created-')]
        self.assertEqual(len(notes), 5)
        self.assertTrue(all('Injected instructions' not in n['body'] for n in notes))
        self.assertEqual(len([n for n in state['notifications'] if n.get('job_id') == 'unrelated']), 8)
        with self.app.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM seen WHERE key LIKE 'output:%'").fetchone()[0], 16)
        job.update(last_status='error', last_run_at='new')
        self.cron_store([job])
        (self.home / 'cron' / 'output' / 'owned' / '99.md').write_text('## Response\n[SILENT]')
        self.app.poll()
        self.assertIn('[SILENT]', [n['body'] for n in self.app.state()['notifications']])

    def test_owned_output_backfill_and_restart_dedupe(self):
        self.managed_fixture()
        self.app.custom()
        key = 'output:owned:old.md'
        raw = '# Cron Job\n## Prompt\n' + 'boilerplate ' * 4000 + '\n## Response\nUseful synthetic response'
        output = self.home / 'cron' / 'output' / 'owned'
        output.mkdir(parents=True)
        (output / 'old.md').write_text(raw)
        nid = backend.hashlib.sha256(key.encode()).hexdigest()
        with self.app.connect() as db:
            db.execute('INSERT INTO seen VALUES (?)', (key,))
            self.app._notify(db, nid, 'Old result', raw[:32000], 'owned')
        self.assertEqual(next(n for n in self.app.state()['notifications'] if n['id'] == nid)['body'], 'Useful synthetic response')
        app2 = backend.Companion(self.home, hermes=self.hermes, profile='default')
        try:
            self.assertEqual(len([n for n in app2.state()['notifications'] if n['id'] == nid]), 1)
        finally:
            app2.close()

    def test_optimized_schedule_continuity_boolean_and_readback(self):
        payload = {'title': 'Review', 'prompt': 'Only new findings', 'schedule': 'every 2h', 'mode': 'cron', 'optimized': True}
        def cli(args, **kwargs):
            self.assertEqual(args[3], payload['prompt'])
            self.assertEqual(args[-1], payload['title'])
            self.assertIn('--continuity', args)
            self.cron_store([{'id': 'fresh', 'name': args[-1], 'prompt': args[3], 'schedule_display': args[2],
                              'enabled': True, 'deliver': 'local', 'context_from': ['self']}])
            return 'Created job: fresh'
        with patch.object(self.app, 'cli', side_effect=cli):
            self.assertEqual(self.app.schedule(payload)['id'], 'fresh')
        with patch.object(self.app, 'cli') as mocked:
            for value in ('true', 1, None):
                with self.assertRaises(ValueError):
                    self.app.schedule({**payload, 'optimized': value})
            mocked.assert_not_called()
        self.managed_fixture()
        jobs = self.app.jobs_raw()
        jobs[0]['context_from'] = ['other-job']
        self.cron_store(jobs)
        def edit(args, **kwargs):
            self.fake_custom_cli(args)
            self.assertIn('--continuity', args)
            jobs = self.app.jobs_raw()
            jobs[0]['context_from'].append('self')
            self.cron_store(jobs)
            return 'Edited'
        with patch.object(self.app, 'cli', side_effect=edit):
            self.app.custom_edit({**payload, 'id': 'owned'})
        self.assertEqual(self.app.jobs_raw()[0]['context_from'], ['other-job', 'self'])
        with patch.object(self.app, 'cli', side_effect=self.fake_custom_cli):
            jobs = self.app.jobs_raw()
            jobs[0]['context_from'] = []
            self.cron_store(jobs)
            with self.assertRaisesRegex(RuntimeError, 'continuity'):
                self.app.custom_edit({**payload, 'id': 'owned'})

    def test_todo_crud_dates_and_validation(self):
        payload = {'title': 'Send draft for review', 'details': 'Synthetic task', 'due_date': '2035-02-28',
                   'reminder_at': '2035-02-28T09:00:00-08:00', 'timezone': 'America/Los_Angeles'}
        status, _, body = self.http('POST', '/api/todo-save', payload)
        self.assertEqual(status, 200)
        todo = json.loads(body)['todo']
        self.assertEqual(todo['reminder_at'], '2035-02-28T17:00:00+00:00')
        self.assertEqual(json.loads(self.http(path='/api/todos')[2])['todos'], [todo])
        self.assertEqual(self.app.todo_action({'id': todo['id'], 'action': 'complete'})['todo']['status'], 'completed')
        self.assertEqual(self.app.todo_action({'id': todo['id'], 'action': 'reopen'})['todo']['status'], 'pending')
        for changes in ({'due_date': '2035-02-29'}, {'due_date': '2035-2-28'}, {'timezone': 'Invalid/Zone'},
                        {'reminder_at': '2035-02-28T09:00:00'}, {'reminder_at': '2000-01-01T00:00:00Z'},
                        {'title': ''}, {'details': 'x' * 4001}):
            self.assertEqual(self.http('POST', '/api/todo-save', {**payload, **changes})[0], 400)
        self.app.todo_action({'id': todo['id'], 'action': 'delete'})
        self.assertEqual(self.app.todos(), {'todos': []})
        with self.assertRaises(LookupError):
            self.app.todo_save({**payload, 'id': todo['id']})

    def test_todo_due_once_catchup_restart_and_rearm(self):
        payload = {'title': 'Review task', 'details': 'Review details', 'due_date': '2035-01-01',
                   'reminder_at': '2035-01-01T10:00:00Z'}
        todo = self.app.todo_save(payload)['todo']
        later = '2035-01-01T11:00:00+00:00'
        with patch.object(backend, 'now', return_value=later), patch.object(self.app, 'poll_messages', side_effect=OSError('no history')):
            self.app.poll()
        first = self.app.todos()['todos'][0]
        self.assertEqual(first['reminded_at'], later)
        notes = [n for n in self.app.state()['notifications'] if n['id'].startswith('todo-reminder-')]
        self.assertEqual(len(notes), 1)
        self.assertTrue(notes[0]['custom'])
        self.assertEqual(self.app.todo_save({**payload, 'id': todo['id'], 'details': 'Edited'})['todo']['reminded_at'], later)
        app2 = backend.Companion(self.home, hermes=self.hermes, profile='default')
        try:
            with patch.object(backend, 'now', return_value=later):
                app2.poll()
            self.assertEqual(len([n for n in app2.state()['notifications'] if n['id'].startswith('todo-reminder-')]), 1)
        finally:
            app2.close()
        self.app.todo_save({**payload, 'id': todo['id'], 'reminder_at': '2035-01-02T10:00:00Z'})
        self.assertIsNone(self.app.todos()['todos'][0]['reminded_at'])
        with patch.object(backend, 'now', return_value='2035-01-03T00:00:00+00:00'):
            self.app.poll_todos()
        self.assertEqual(len([n for n in self.app.state()['notifications'] if n['id'].startswith('todo-reminder-')]), 2)
        self.app.todo_action({'id': todo['id'], 'action': 'delete'})
        self.assertEqual(len([n for n in self.app.state()['notifications'] if n['id'].startswith('todo-reminder-')]), 2)

    def test_todo_complete_cancels_pending_reminder(self):
        todo = self.app.todo_save({'title': 'Task', 'due_date': '2035-01-01', 'reminder_at': '2035-01-01T10:00:00Z'})['todo']
        self.app.todo_action({'id': todo['id'], 'action': 'complete'})
        with patch.object(backend, 'now', return_value='2035-01-02T10:00:00+00:00'):
            self.app.poll_todos()
        self.assertFalse(any(n['id'].startswith('todo-reminder-') for n in self.app.state()['notifications']))

    def test_health_healthy_frequency_restart_and_no_notifications(self):
        with patch.object(self.app, 'chat', return_value=('WOOF_HEALTH_OK', None)) as chat:
            result = self.app.health_check(daily=True)
            self.wait_request(result['id'])
            self.assertEqual(self.app.health_check(daily=True), {'status': 'not-due'})
            chat.assert_called_once()
            self.assertTrue(chat.call_args.kwargs['analysis'])
            state = self.app.state()
            self.assertEqual(state['status']['health']['issues_count'], 0)
            self.assertIsNotNone(state['status']['health']['checked_at'])
            self.assertFalse(state['notifications'])
        app2 = backend.Companion(self.home, hermes=self.hermes, profile='default')
        try:
            with patch.object(app2, 'chat') as chat:
                self.assertEqual(app2.health_check(daily=True), {'status': 'not-due'})
                chat.assert_not_called()
        finally:
            app2.close()

    def test_health_busy_merge_actions_and_resolve(self):
        job = self.managed_fixture(enabled=True)
        job['last_status'] = 'error'
        self.cron_store([job])
        self.app.custom()
        with self.app.connect() as db:
            suggestions = {'proactive': [{'id': 'conversation', 'title': 'Follow up'}], 'ideas': []}
            db.execute("INSERT OR REPLACE INTO meta VALUES ('suggestions',?)", (json.dumps(suggestions),))
            db.execute("INSERT OR REPLACE INTO meta VALUES ('suggestions_method','model')")
        entered, release = threading.Event(), threading.Event()
        def probe(*args, **kwargs):
            entered.set()
            release.wait(3)
            return 'WOOF_HEALTH_OK', None
        with patch.object(self.app, 'chat', side_effect=probe) as chat, patch.object(self.app, 'request') as request:
            result = self.app.health_check()
            self.assertTrue(entered.wait(2))
            self.assertEqual(self.app.health_check(), {'status': 'running'})
            release.set()
            self.wait_request(result['id'])
            request.assert_not_called()
            chat.assert_called_once()
        state = self.app.state()
        self.assertIn('conversation', [c['id'] for c in state['proactive']])
        cards = [c for c in state['proactive'] if c.get('source') == 'agent-health']
        self.assertEqual(len(cards), 2)
        with patch.object(self.app, 'request', return_value={'id': 'queued-repair', 'status': 'queued'}) as request:
            result = self.app.health_action({'id': cards[0]['id']})
            self.assertEqual(result['id'], 'queued-repair')
            self.assertIn('minimally scoped', request.call_args.args[0]['prompt'])
            self.assertIn('verify', request.call_args.args[0]['prompt'])
        with self.assertRaises(LookupError):
            self.app.health_action({'id': 'unknown'})
        self.cron_store([])
        with patch.object(self.app, 'chat', return_value=('WOOF_HEALTH_OK', None)):
            self.wait_request(self.app.health_check()['id'])
        with self.assertRaises(LookupError):
            self.app.health_action({'id': cards[0]['id']})
        self.assertIn('conversation', [c['id'] for c in self.app.state()['proactive']])

    def test_health_unavailable_provider_and_cli_manual_remediation(self):
        with patch.object(self.app, 'chat', side_effect=RuntimeError('private token must not leak')):
            self.wait_request(self.app.health_check()['id'])
        card = next(c for c in self.app.state()['proactive'] if c.get('source') == 'agent-health')
        self.assertEqual(card['action']['kind'], 'settings')
        self.assertNotIn('private token', json.dumps(card))
        with self.assertRaises(ValueError):
            self.app.health_action({'id': card['id']})
        self.hermes.unlink()
        with patch.object(self.app, 'chat') as chat:
            self.wait_request(self.app.health_check()['id'])
            chat.assert_not_called()
        card = next(c for c in self.app.state()['proactive'] if c.get('source') == 'agent-health')
        self.assertEqual(card['id'], 'health-cli')
        self.assertEqual(card['action']['kind'], 'settings')
        self.assertIn('bridge host', card['prompt'])

    def test_todo_unchanged_past_reminder_preserves_emission(self):
        payload = {'title': 'Review', 'due_date': '2035-01-01', 'reminder_at': '2035-01-01T10:00:00Z'}
        todo = self.app.todo_save(payload)['todo']
        later = backend.datetime.fromisoformat('2035-01-02T10:00:00+00:00')
        with patch.object(backend, 'now', return_value=later.isoformat()):
            self.app.poll_todos()
        with patch.object(backend, 'datetime', wraps=backend.datetime) as clock:
            clock.now.return_value = later
            same = self.app.todo_save({**payload, 'id': todo['id'], 'title': 'New title'})['todo']
            self.assertEqual(same['reminded_at'], later.isoformat())
            with self.assertRaises(ValueError):
                self.app.todo_save({**payload, 'id': todo['id'], 'reminder_at': '2035-01-01T11:00:00Z'})

    def test_health_daily_interval_and_failed_action_observations(self):
        self.managed_fixture(enabled=False)
        self.app.custom()
        jobs = self.app.jobs_raw()
        jobs.append(dict(jobs[0], id='unrelated', last_status='error'))
        self.cron_store(jobs)
        with self.app.connect() as db:
            db.execute('INSERT INTO requests VALUES (?,?,?,?,?)', ('old-failed', 'Synthetic action', 'error', 'private details', backend.now()))
        with patch.object(self.app, 'chat', return_value=('WOOF_HEALTH_OK', None)):
            self.wait_request(self.app.health_check(daily=True)['id'])
            with self.app.connect() as db:
                started = float(db.execute("SELECT value FROM meta WHERE key='health_started_at'").fetchone()[0])
            with patch.object(backend.time, 'time', return_value=started + 86399):
                self.assertEqual(self.app.health_check(daily=True)['status'], 'not-due')
            with patch.object(backend.time, 'time', return_value=started + 86401):
                self.wait_request(self.app.health_check(daily=True)['id'])
        cards = [c for c in self.app.state()['proactive'] if c.get('source') == 'agent-health']
        self.assertEqual([c['id'] for c in cards], ['health-requests'])
        self.assertIn('historical', cards[0]['body'])
        self.assertNotIn('private details', json.dumps(cards))

    def test_health_action_queues_ordinary_chat_only_after_click(self):
        self.managed_fixture(enabled=True)
        with patch.object(self.app, 'chat', return_value=('WOOF_HEALTH_OK', None)) as chat:
            self.wait_request(self.app.health_check()['id'])
            self.assertEqual(chat.call_count, 1)
            hid = next(c['id'] for c in self.app.state()['proactive'] if c.get('source') == 'agent-health')
        with patch.object(self.app, 'chat', return_value=('Repair request outcome', 'repair-session')) as chat:
            status, _, body = self.http('POST', '/api/health-action', {'id': hid})
            self.assertEqual(status, 202)
            self.wait_request(json.loads(body)['id'])
            chat.assert_called_once()
            self.assertFalse(chat.call_args.kwargs.get('analysis', False))
            self.assertIn('normal Hermes approvals', chat.call_args.args[0])

    def test_context_cleaner_excludes_runtime_and_skill_preamble(self):
        self.assertEqual(backend.conversation_text('[ASYNC DELEGATION BATCH COMPLETE — test] runtime message'), '')
        self.assertEqual(backend.conversation_text('[INTERNAL NOTIFICATION — generated by the Hermes gateway] status'), '')
        wrapped = '[IMPORTANT: The "test" skill is auto-loaded.]\n' + ('skill docs ' * 250) + '\n[Skill directory: /path/skill]\n\nPlease help me review the website navigation.'
        self.assertEqual(backend.conversation_text(wrapped), 'Please help me review the website navigation.')
        self.assertEqual(backend.conversation_text('[rp | Slack user <@U123>] Review the website'), 'Review the website')

    def test_all_reads_require_auth(self):
        for path in ('/api/state', '/api/info', '/', '/app.js'):
            self.assertEqual(self.http(path=path, auth=False)[0], 401)
        self.assertEqual(self.http(headers={'Authorization': 'Bearer wrong'})[0], 401)
        self.assertEqual(self.http()[0], 200)

    def test_token_cookie_and_redirect(self):
        status, headers, _ = self.http(path='/?token=' + self.app.token, auth=False)
        self.assertEqual(status, 303)
        self.assertEqual(headers['Location'], '/')
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertIn('SameSite=Strict', headers['Set-Cookie'])
        cookie = headers['Set-Cookie'].split(';')[0]
        self.assertEqual(self.http(auth=False, headers={'Cookie': cookie})[0], 200)
        self.assertEqual(self.http(path='/?token=wrong', auth=False)[0], 401)
        if os.name != 'nt':
            self.assertEqual(stat.S_IMODE((self.home / 'nudge' / 'token').stat().st_mode), 0o600)

    def test_origin_and_host_guard(self):
        for headers in ({'Host': 'evil.test'}, {'Origin': 'https://evil.test'},
                        {'Origin': 'null'}, {'Sec-Fetch-Site': 'cross-site'}):
            self.assertEqual(self.http(headers=headers)[0], 403)
            self.assertEqual(self.http('POST', '/api/refresh', {}, headers=headers)[0], 403)
        self.assertEqual(self.http(headers={'Origin': self.server.origin})[0], 200)
        self.assertNotIn('Access-Control-Allow-Origin', self.http()[1])

    def test_input_and_json(self):
        for value in ('', 'x' * 16001, None, 12):
            self.assertEqual(self.http('POST', '/api/request', {'prompt': value})[0], 400)
        self.assertEqual(self.http('POST', '/api/request', [1, 2])[0], 400)
        self.assertEqual(self.http('POST', '/api/request', {'prompt': 'valid'},
                                   headers={'Content-Type': 'text/plain'})[0], 415)
        self.assertEqual(self.http('POST', '/api/job', {'id': '../bad', 'action': 'run'})[0], 400)
        self.assertEqual(self.http('POST', '/api/job', {'id': 'unknown', 'action': 'run'})[0], 404)
        self.assertEqual(self.http('POST', '/api/request', {'prompt': 'valid'}, auth=False)[0], 401)

    def test_static_allowlist_and_csp(self):
        status, headers, body = self.http(path='/')
        self.assertEqual(status, 200)
        self.assertIn(b'Nudge', body)
        self.assertIn("script-src 'self'", headers['Content-Security-Policy'])
        for path in ('/../backend.py', '/%2e%2e/backend.py', '/token', '/web/index.html'):
            self.assertEqual(self.http(path=path)[0], 404)
        try:
            (self.web / 'app.js').symlink_to(self.home / 'nudge' / 'token')
        except OSError:
            if os.name != 'nt':
                raise
            return  # Windows may require developer mode or administrator rights to create symlinks.
        self.assertEqual(self.http(path='/app.js')[0], 404)

    def test_parse_history_read_only_and_exclusions(self):
        path = self.history_fixture()
        before = path.read_bytes()
        history = backend.recent_history(path)
        self.assertEqual([h['message_id'] for h in history], [4, 1])
        self.assertEqual(history[0]['text'], 'Plan a follow up')
        self.assertEqual(path.read_bytes(), before)
        self.assertLessEqual(sum(len(h['text']) for h in backend.recent_history(path, max_chars=25)), 25)

    def test_fallback_provenance(self):
        history = backend.recent_history(self.history_fixture())
        suggestions = backend.fallback_suggestions(history)
        self.assertEqual(len(suggestions['proactive']), 1)
        self.assertEqual(len(suggestions['ideas']), 1)
        for entry in suggestions['proactive'] + suggestions['ideas']:
            self.assertIn('deterministic-history; session=real; message=', entry['source'])
            self.assertIn('not an inferred pending task', entry['body'])
        self.assertEqual(suggestions, backend.fallback_suggestions(history))

    def test_schedule_adapter_heartbeat_and_verified_delivery(self):
        calls = []
        def cli(args, **kwargs):
            calls.append(args)
            self.cron_store([{'id': 'new-job', 'name': args[-1], 'schedule_display': args[2],
                              'schedule': {'kind': 'interval'}, 'prompt': args[3],
                              'enabled': True, 'deliver': ['local']}])
            return '\x1b[32mCreated job: new-job\x1b[0m\n'
        with patch.object(self.app, 'cli', side_effect=cli):
            result = self.app.schedule({'title': 'Check', 'prompt': 'Be harmless', 'schedule': '30m', 'mode': 'heartbeat'})
        self.assertEqual(result['id'], 'new-job')
        self.assertEqual(calls[0][2], 'every 30m')
        self.assertEqual(calls[0][-1], '[heartbeat-style] Check')
        self.assertEqual(calls[0][4:6], ['--deliver', 'local'])
        with self.assertRaises(ValueError):
            self.app.schedule({'title': 'Check', 'prompt': 'Be harmless', 'schedule': '0 9 * * *', 'mode': 'heartbeat'})
        with patch.object(self.app, 'cli', return_value='Created job: missing'):
            with self.assertRaises(RuntimeError):
                self.app.schedule({'title': 'Check', 'prompt': 'Be harmless', 'schedule': 'every 2h', 'mode': 'cron'})

    def managed_fixture(self, jid='owned', enabled=False):
        job = {'id': jid, 'name': 'Email checkup', 'prompt': 'Check email',
               'schedule': {'kind': 'interval', 'minutes': 120}, 'schedule_display': 'every 120m',
               'deliver': 'local', 'enabled': enabled, 'last_status': 'ok',
               'last_run_at': '2026-10-08T04:17:31Z', 'next_run_at': '2026-10-08T06:17:31Z'}
        self.cron_store([job])
        with self.app.connect() as db:
            self.app._notify(db, 'created-' + jid, job['name'], 'Created Hermes schedule: every 2h', jid)
        return job

    def fake_custom_cli(self, args, **kwargs):
        jobs = self.app.jobs_raw()
        if args[:2] == ['cron', 'remove']:
            self.cron_store([j for j in jobs if j['id'] != args[2]])
            return 'Removed job'
        self.assertEqual(args[:2], ['cron', 'edit'])
        job = next(j for j in jobs if j['id'] == args[2])
        for flag, field in [('--name', 'name'), ('--prompt', 'prompt'), ('--deliver', 'deliver')]:
            job[field] = args[args.index(flag) + 1]
        schedule = args[args.index('--schedule') + 1]
        match = backend.re.fullmatch(r'every (\d+)([mhd])', schedule)
        if match:
            minutes = int(match[1]) * {'m': 1, 'h': 60, 'd': 1440}[match[2]]
            job['schedule'] = {'kind': 'interval', 'minutes': minutes}
            job['schedule_display'] = f'every {minutes}m'
        else:
            job['schedule'] = {'kind': 'cron', 'expr': schedule}
            job['schedule_display'] = schedule
        self.cron_store(jobs)
        return 'Edited job'

    def test_custom_legacy_exact_ownership_and_annotation(self):
        job = self.managed_fixture('14dbc75a3840', enabled=True)
        unrelated = dict(job, id='unrelated')  # Identical name is NOT ownership.
        self.cron_store([job, unrelated])
        with self.app.connect() as db:
            self.app._notify(db, 'result', job['name'], 'Email result', job['id'])
            self.app._notify(db, 'other-result', job['name'], 'Other result', 'unrelated')
            self.app._notify(db, 'created-fake', 'Same name', 'Not a creation confirmation', 'fake')
            self.app._notify(db, 'created-wrong-id', 'Same name', 'Created Hermes schedule: every 2h', 'wrong')
        status, _, body = self.http(path='/api/custom')
        self.assertEqual(status, 200)
        entries = json.loads(body)['notifications']
        self.assertEqual([n['id'] for n in entries], ['14dbc75a3840'])
        self.assertEqual(entries[0]['prompt'], 'Check email')
        self.assertTrue(entries[0]['exists'])
        self.assertEqual(set(entries[0]), {'id', 'title', 'prompt', 'schedule', 'mode', 'enabled',
                                         'last_status', 'last_run_at', 'next_run_at', 'exists'})
        state = self.app.state()
        self.assertEqual(state['custom_notifications'], entries)
        notes = {n['id']: n for n in state['notifications']}
        self.assertTrue(notes['result']['custom'])
        self.assertNotIn('custom', notes['other-result'])
        self.assertNotIn('custom', notes['created-fake'])
        app2 = backend.Companion(self.home, hermes=self.hermes, profile='default')
        try:
            self.assertEqual(app2.custom()['notifications'], entries)
        finally:
            app2.close()

    def test_custom_schedule_durable_ownership_only_on_verified_create(self):
        def cli(args, **kwargs):
            self.cron_store([{'id': 'created', 'name': args[-1], 'prompt': args[3],
                              'schedule': {'kind': 'interval', 'minutes': 120},
                              'schedule_display': 'every 120m', 'deliver': 'local', 'enabled': True}])
            return 'Created job: created'
        with patch.object(self.app, 'cli', side_effect=cli):
            self.app.schedule({'title': 'Check', 'prompt': 'Check it', 'schedule': 'every 2h', 'mode': 'cron'})
        with self.app.connect() as db:
            self.assertEqual(db.execute('SELECT mode FROM managed_jobs WHERE id=?', ('created',)).fetchone()[0], 'cron')
        self.assertEqual(self.app.custom()['notifications'][0]['prompt'], 'Check it')
        with patch.object(self.app, 'cli', return_value='Created job: missing'):
            with self.assertRaises(RuntimeError):
                self.app.schedule({'title': 'Check', 'prompt': 'Check it', 'schedule': 'every 2h', 'mode': 'cron'})
        with self.app.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM managed_jobs').fetchone()[0], 1)

    def test_custom_edit_verified_normalized_interval_and_mode_prefixes(self):
        self.managed_fixture()
        payload = {'id': 'owned', 'title': 'New title', 'prompt': 'New prompt', 'schedule': '2h', 'mode': 'heartbeat'}
        with patch.object(self.app, 'cli', side_effect=self.fake_custom_cli) as cli:
            status, _, body = self.http('POST', '/api/custom-edit', payload)
            self.assertEqual(status, 200, body)
            notification = json.loads(body)['notification']
            self.assertEqual(notification['schedule'], 'every 120m')
            self.assertEqual(notification['title'], '[heartbeat-style] New title')
            self.assertFalse(notification['enabled'])
            self.assertEqual(notification['mode'], 'heartbeat')
            self.assertIn('--deliver', cli.call_args.args[0])
            payload.update(title=notification['title'], prompt=notification['prompt'])
            self.app.custom_edit(payload)
            self.assertEqual(self.app.jobs_raw()[0]['name'].count('[heartbeat-style]'), 1)
            payload.update(mode='cron', schedule='0 9 * * *')
            final = self.app.custom_edit(payload)['notification']
            self.assertEqual(final['title'], 'New title')
            self.assertEqual(final['prompt'], 'New prompt')
            self.assertEqual(final['schedule'], '0 9 * * *')
        with patch.object(self.app, 'cli') as cli:
            payload.update(mode='heartbeat')
            self.assertEqual(self.http('POST', '/api/custom-edit', payload)[0], 400)
            cli.assert_not_called()

    def test_custom_once_schedule_is_editable_and_unchanged_reads_do_not_write(self):
        job = self.managed_fixture()
        timestamp = '2030-01-02T03:04:00+00:00'
        job.update(schedule={'kind': 'once', 'run_at': timestamp},
                   schedule_display='once at 2030-01-02 03:04')
        self.cron_store([job])
        first = self.app.custom()['notifications'][0]
        self.assertEqual(first['schedule'], timestamp)
        self.assertTrue(self.app.schedule_matches(job, first['schedule']))
        statements = []
        original = self.app.connect
        def traced():
            db = original()
            db.set_trace_callback(statements.append)
            return db
        with patch.object(self.app, 'connect', side_effect=traced):
            self.assertEqual(self.app.custom()['notifications'][0], first)
        self.assertFalse(any(s.startswith('UPDATE managed_jobs SET snapshot=') for s in statements))

    def test_custom_edit_rejects_failed_readback(self):
        original = self.managed_fixture()
        payload = {'id': 'owned', 'title': 'New', 'prompt': 'New prompt', 'schedule': 'every 2h', 'mode': 'cron'}
        for mutation in ({'name': 'wrong'}, {'prompt': 'wrong'},
                         {'schedule': {'kind': 'interval', 'minutes': 60}, 'schedule_display': 'every 60m'},
                         {'deliver': 'slack'}, {'enabled': True}):
            self.cron_store([original])
            def cli(args, **kwargs):
                self.fake_custom_cli(args)
                self.cron_store([dict(self.app.jobs_raw()[0], **mutation)])
                return 'Edited'
            with patch.object(self.app, 'cli', side_effect=cli):
                self.assertEqual(self.http('POST', '/api/custom-edit', payload)[0], 502)
        with self.app.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM managed_jobs WHERE title=?', ('New',)).fetchone()[0], 0)

    def test_custom_delete_tombstone_history_and_idempotence(self):
        job = self.managed_fixture()
        self.cron_store([job, dict(job, id='unrelated')])
        with self.app.connect() as db:
            self.app._notify(db, 'historical', 'Email result', 'Keep me', 'owned')
        with patch.object(self.app, 'cli', side_effect=self.fake_custom_cli) as cli:
            for _ in range(2):
                status, _, body = self.http('POST', '/api/custom-delete', {'id': 'owned'})
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(body), {'id': 'owned', 'deleted': True})
            cli.assert_called_once_with(['cron', 'remove', 'owned'])
        self.assertEqual([j['id'] for j in self.app.jobs_raw()], ['unrelated'])
        self.assertEqual(self.app.custom()['notifications'], [])
        notes = {n['id']: n for n in self.app.state()['notifications']}
        self.assertEqual(notes['historical']['body'], 'Keep me')
        self.assertTrue(notes['historical']['custom'])
        app2 = backend.Companion(self.home, hermes=self.hermes, profile='default')
        try:
            self.assertEqual(app2.custom()['notifications'], [])
            self.assertTrue(next(n for n in app2.state()['notifications'] if n['id'] == 'historical')['custom'])
        finally:
            app2.close()
        payload = {'id': 'owned', 'title': 'New', 'prompt': 'New', 'schedule': 'every 2h', 'mode': 'cron'}
        self.assertEqual(self.http('POST', '/api/custom-edit', payload)[0], 404)

    def test_custom_delete_verification_failure_no_tombstone(self):
        self.managed_fixture()
        self.app.custom()
        with patch.object(self.app, 'cli', return_value='Removed'):
            self.assertEqual(self.http('POST', '/api/custom-delete', {'id': 'owned'})[0], 502)
        self.assertEqual(len(self.app.custom()['notifications']), 1)

    def test_custom_unrelated_rejection_and_auth(self):
        job = self.managed_fixture()
        self.cron_store([job, dict(job, id='unrelated')])
        payload = {'id': 'unrelated', 'title': 'New', 'prompt': 'New', 'schedule': 'every 2h', 'mode': 'cron'}
        with patch.object(self.app, 'cli') as cli:
            for endpoint in ('/api/custom-edit', '/api/custom-delete'):
                self.assertEqual(self.http('POST', endpoint, payload)[0], 404)
                self.assertEqual(self.http('POST', endpoint, payload, auth=False)[0], 401)
            cli.assert_not_called()
        self.assertEqual(self.http(path='/api/custom', auth=False)[0], 401)

    def test_custom_missing_completed_entry_and_output(self):
        self.managed_fixture()
        self.app.custom()
        self.cron_store([])
        directory = self.home / 'cron' / 'output' / 'owned'
        directory.mkdir(parents=True)
        (directory / 'completed.md').write_text('One-shot completed')
        state = self.app.state()
        entry = state['custom_notifications'][0]
        self.assertFalse(entry['exists'])
        self.assertFalse(entry['enabled'])
        self.assertIsNone(entry['next_run_at'])
        self.assertEqual(entry['last_status'], 'ok')
        self.assertEqual(entry['prompt'], 'Check email')
        self.assertTrue(next(n for n in state['notifications'] if n['body'] == 'One-shot completed')['custom'])
        with patch.object(self.app, 'cli') as cli:
            payload = {'id': 'owned', 'title': 'New', 'prompt': 'New', 'schedule': 'every 2h', 'mode': 'cron'}
            self.assertEqual(self.http('POST', '/api/custom-edit', payload)[0], 404)
            self.assertEqual(self.http('POST', '/api/custom-delete', {'id': 'owned'})[0], 200)
            cli.assert_not_called()

    def test_custom_schedule_verification_shapes(self):
        matches = self.app.schedule_matches
        self.assertTrue(matches({'schedule': {'kind': 'interval', 'minutes': 120}}, 'every 2h'))
        self.assertFalse(matches({'schedule': {'kind': 'interval', 'minutes': 60},
                                  'schedule_display': 'every 2h'}, 'every 2h'))
        self.assertFalse(matches({'schedule': {'kind': 'once'}, 'schedule_display': '2h'}, '2h'))
        self.assertTrue(matches({'schedule': {'kind': 'once', 'run_at': '2026-10-08T09:00:00-07:00'}},
                                '2026-10-08T16:00:00Z'))
        self.assertTrue(matches({'schedule': {'kind': 'once', 'run_at': '2026-10-08T09:00:00-07:00'}},
                                '2026-10-08T09:00:00'))
        self.assertTrue(matches({'schedule': {'kind': 'once', 'run_at': '2026-10-08T09:00:00Z',
                                              'display': 'once in 30m'}}, 'in 30m'))

    def test_custom_migration_on_startup_without_listing(self):
        self.managed_fixture('14dbc75a3840')
        app2 = backend.Companion(self.home, hermes=self.hermes, profile='default')
        try:
            with app2.connect() as db:
                row = db.execute('SELECT * FROM managed_jobs WHERE id=?', ('14dbc75a3840',)).fetchone()
                self.assertEqual(row['title'], 'Email checkup')
                self.assertEqual(row['schedule'], 'every 2h')
                self.assertIsNone(row['deleted_at'])
        finally:
            app2.close()

    def test_custom_legacy_missing_entry(self):
        self.managed_fixture()
        self.cron_store([])
        entry = self.app.custom()['notifications'][0]
        self.assertFalse(entry['exists'])
        self.assertEqual(entry['schedule'], 'every 2h')
        self.assertEqual(entry['prompt'], '')  # No invention when creation record lacks prompt.

    def test_request_async_result_and_error_persist(self):
        with patch.object(self.app, 'chat', return_value=('Done', 'sid')):
            result = self.app.request({'prompt': 'test'})
            req = self.wait_request(result['id'])
            self.assertEqual(req['status'], 'completed')
            self.assertEqual(req['body'], 'Done')
        with patch.object(self.app, 'chat', side_effect=RuntimeError('timed out')):
            result = self.app.request({'prompt': 'test'})
            self.assertEqual(self.wait_request(result['id'])['status'], 'error')
        app2 = backend.Companion(self.home, hermes=self.hermes, web=self.web, profile='default')
        try:
            self.assertEqual(len(app2.state()['requests']), 2)
            self.assertEqual(len(app2.state()['notifications']), 2)
        finally:
            app2.close()

    def test_refresh_real_analysis_adapter_and_provenance_validation(self):
        self.fresh_history_fixture()
        valid = {'proactive': [{'title': 'Review', 'body': 'Optional follow up', 'prompt': 'Review the project',
                              'source_session': 'real', 'message_id': 1}], 'ideas': []}
        with patch.object(self.app, 'chat', return_value=(json.dumps(valid), 'analysis-sid')) as chat:
            result = self.app.refresh()
            self.assertEqual(self.wait_request(result['id'])['status'], 'completed')
            self.assertTrue(chat.call_args.kwargs['analysis'])
            self.assertIn('conversation-analysis; session=real; message=1', self.app.state()['proactive'][0]['source'])
        valid['proactive'][0]['source_session'] = 'fabricated'
        with patch.object(self.app, 'chat', return_value=(json.dumps(valid), 'analysis-sid')):
            result = self.app.refresh()
            self.assertEqual(self.wait_request(result['id'])['status'], 'error')
            self.assertIn('conversation-analysis; session=real', self.app.state()['proactive'][0]['source'])
            self.assertEqual(self.app.state()['ideas'], [])
            self.assertIsNotNone(self.app.coaching_settings()['last_error'])
            self.assertFalse(self.app.analysis_busy)

    def test_durable_cron_output_and_status_dedupe(self):
        self.cron_store([{'id': 'job1', 'name': 'Check', 'enabled': True, 'last_run_at': '2026-01-01',
                          'last_status': 'error', 'last_error': 'failed'}])
        directory = self.home / 'cron' / 'output' / 'job1'
        directory.mkdir(parents=True)
        (directory / '20260101.md').write_text('Cron result')
        for _ in range(3):
            self.app.poll()
        self.assertEqual(len(self.app.state()['notifications']), 2)
        app2 = backend.Companion(self.home, hermes=self.hermes, profile='default')
        try:
            self.assertEqual(len(app2.state()['notifications']), 2)
            (directory / '20260102.md').write_text('Cron result')
            self.assertEqual(len(app2.state()['notifications']), 3)
        finally:
            app2.close()

    def test_notification_read_durable(self):
        with self.app.connect() as db:
            self.app._notify(db, 'note', 'Test', 'Body')
        self.assertEqual(self.http('POST', '/api/notification', {'id': 'note', 'read': True})[0], 200)
        self.assertTrue(self.app.state()['notifications'][0]['read'])
        self.assertEqual(self.http('POST', '/api/notification', {'id': 'note', 'read': False})[0], 400)

    def test_job_pause_verified(self):
        self.cron_store([{'id': 'job1', 'name': 'test', 'enabled': True}])
        def cli(args, **kwargs):
            self.assertEqual(args, ['cron', 'pause', 'job1'])
            self.cron_store([{'id': 'job1', 'name': 'test', 'enabled': False}])
            return 'Paused job: test (job1)'
        with patch.object(self.app, 'cli', side_effect=cli):
            result = self.app.job({'id': 'job1', 'action': 'pause'})
            self.assertEqual(self.wait_request(result['id'])['status'], 'completed')
        self.assertFalse(self.app.state()['jobs'][0]['enabled'])

    def test_stream_parser(self):
        answer, sid, events = backend.parse_stream('noise\n' + json.dumps(
            {'type': 'result', 'text': 'answer', 'session_id': 'sid', 'exit_code': 0}))
        self.assertEqual((answer, sid), ('answer', 'sid'))
        for bad in ('noise', '{"type":"result","text":"","exit_code":0}',
                    '{"type":"result","text":"partial","exit_code":2}'):
            with self.assertRaises(RuntimeError):
                backend.parse_stream(bad)

    def test_analysis_tools_disabled_and_no_yolo(self):
        def cli(args, prompt, timeout):
            self.assertIn('none', args)
            self.assertIn('--ignore-rules', args)
            self.assertNotIn('--yolo', args)
            self.assertEqual(args[args.index('--source') + 1], 'nudge-analysis')
            return '{"type":"result","text":"OK","exit_code":0}'
        with patch.object(self.app, 'cli', side_effect=cli):
            self.assertEqual(self.app.chat('safe', analysis=True)[0], 'OK')

    def test_automatic_history_seed_debounce_and_llm_preservation(self):
        path = self.history_fixture()
        self.app.last_history_check = float('-inf')
        with patch.object(self.app, 'chat', side_effect=AssertionError('Automatic history must not call LLM')):
            state = self.app.state()
            self.assertEqual(state['proactive'], [])
            self.assertEqual(state['ideas'], [])
        saved = {'proactive': [{'id': 'llm', 'title': 'LLM', 'body': 'Body', 'prompt': 'Test'}], 'ideas': []}
        saved['proactive'][0]['source'] = 'conversation-analysis; session=real; message=1'
        with self.app.connect() as db:
            db.execute("INSERT OR REPLACE INTO meta VALUES ('suggestions',?)", (json.dumps(saved),))
        self.app.last_history_check = float('-inf')
        self.assertEqual(self.app.state()['proactive'][0]['id'], 'llm')
        with sqlite3.connect(path, factory=backend.ClosingConnection) as db:
            db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?)', (7, 'real', 'user', 'A new request', 7, 1))
        self.assertEqual(self.app.state()['proactive'][0]['id'], 'llm')
        self.app.last_history_check = float('-inf')
        self.assertEqual(self.app.state()['proactive'][0]['id'], 'llm')

    def stream_fixture(self):
        path = self.history_fixture()
        with sqlite3.connect(path, factory=backend.ClosingConnection) as db:
            for name, kind in [('tool_calls', 'TEXT'), ('tool_call_id', 'TEXT'),
                               ('finish_reason', 'TEXT'), ('reasoning', 'TEXT'),
                               ('display_kind', 'TEXT'), ('display_metadata', 'TEXT'),
                               ('message_uid', 'TEXT'), ('_compressed_summary', 'INTEGER')]:
                db.execute(f'ALTER TABLE messages ADD COLUMN {name} {kind}')
            db.executemany('INSERT INTO sessions VALUES (?,?)',
                           [('slack', 'slack'), ('cron', 'cron'), ('delegate', 'subagent'),
                            ('tool', 'tool'), ('own-analysis', 'nudge-analysis')])
        self.assertEqual(self.app.poll_messages(), 0)  # Establish durable high water.
        return path

    def add_message(self, path, mid, body='New answer', **values):
        row = dict(id=mid, session_id='slack', role='assistant', content=body,
                   timestamp=mid, active=1, finish_reason='stop', message_uid=f'uid-{mid}')
        row.update(values)
        with sqlite3.connect(path, factory=backend.ClosingConnection) as db:
            db.execute('INSERT INTO messages (' + ','.join(row) + ') VALUES (' +
                       ','.join('?' for _ in row) + ')', tuple(row.values()))

    def test_message_watcher_no_backfill_new_clean_body_and_restart_dedupe(self):
        path = self.stream_fixture()
        self.assertEqual(self.app.state()['notifications'], [])
        body = 'Done.\n\n*Slack formatting* and <https://example.com|link> preserved.'
        self.add_message(path, 7, body, reasoning='Private thought')
        before = path.read_bytes()
        notes = self.app.state()['notifications']
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]['body'], body)
        self.assertEqual(notes[0]['session_id'], 'slack')
        self.assertEqual(notes[0]['message_id'], 'uid-7')
        self.assertEqual(notes[0]['source'], 'slack')
        self.assertEqual(notes[0]['created_at'], '1970-01-01T00:00:07+00:00')
        self.assertEqual(path.read_bytes(), before)
        app2 = backend.Companion(self.home, hermes=self.hermes, profile='default')
        try:
            self.assertEqual(len(app2.state()['notifications']), 1)
            self.add_message(path, 8, body, message_uid='uid-7')
            self.assertEqual(len(app2.state()['notifications']), 1)
            self.add_message(path, 9, 'x' * 33000, timestamp=1)
            notes = app2.state()['notifications']
            self.assertEqual(len(notes), 2)
            self.assertEqual(len(next(n for n in notes if n['message_id'] == 'uid-9')['body']), 32000)
        finally:
            app2.close()

    def test_message_watcher_excludes_internal_tools_thinking_and_cron(self):
        path = self.stream_fixture()
        cases = [dict(role='tool'), dict(role='analysis'), dict(tool_calls='[{"id":"call"}]'),
                 dict(finish_reason='tool_calls'), dict(finish_reason='incomplete'),
                 dict(display_kind='hidden'), dict(display_kind='analysis'), dict(active=0),
                 dict(display_metadata='{"channel":"analysis"}'),
                 dict(display_metadata='{"presentation_suppressed":true}'),
                 dict(session_id='cron'), dict(session_id='delegate'), dict(session_id='tool'),
                 dict(session_id='own-analysis'), dict(_compressed_summary=1),
                 dict(content='[ASYNC DELEGATION BATCH COMPLETE — test] internal'),
                 dict(content='[INTERNAL NOTIFICATION — generated by the Hermes gateway] injected')]
        for mid, values in enumerate(cases, 7):
            self.add_message(path, mid, **values)
        self.app.poll_messages()
        self.assertEqual(self.app.state()['notifications'], [])
        self.add_message(path, 100, reasoning='Thinking should not enter the body')
        self.assertEqual(self.app.state()['notifications'][0]['body'], 'New answer')

    def test_message_watcher_bounded_backlog_batches_survive_restart(self):
        path = self.stream_fixture()
        for mid in range(7, 32):
            self.add_message(path, mid)
        self.assertEqual(self.app.poll_messages(batch_size=7), 7)
        self.assertEqual(self.app.poll_messages(batch_size=7), 7)
        with self.app.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM notifications').fetchone()[0], 14)
            self.assertEqual(db.execute("SELECT value FROM meta WHERE key='assistant_cursor'").fetchone()[0], '20')
        app2 = backend.Companion(self.home, hermes=self.hermes, profile='default')
        try:
            self.assertEqual(app2.poll_messages(batch_size=7), 7)
            self.assertEqual(app2.poll_messages(batch_size=7), 4)
            self.assertEqual(app2.poll_messages(batch_size=7), 0)
            notes = app2.state()['notifications']
            self.assertEqual(len(notes), 25)
            self.assertEqual({n['message_id'] for n in notes}, {f'uid-{mid}' for mid in range(7, 32)})
        finally:
            app2.close()

    def test_request_completion_reconciles_stream_before_and_after_result(self):
        path = self.stream_fixture()
        def chat(prompt):
            self.add_message(path, 7, 'Done', session_id='self')
            self.app.poll_messages()  # Simulate polling while chat has not returned.
            return 'Done', 'self'
        with patch.object(self.app, 'chat', side_effect=chat):
            request = self.app.request({'prompt': 'Explicit work'})
            self.wait_request(request['id'])
        notes = self.app.state()['notifications']
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]['id'], 'request-' + request['id'])
        self.assertEqual(notes[0]['session_id'], 'self')
        self.add_message(path, 8, 'Done', session_id='self', message_uid='uid-7')
        self.assertEqual(len(self.app.state()['notifications']), 1)
        self.add_message(path, 9, 'Other explicit companion result', session_id='self', message_uid='other')
        # Distinct messages are still visible; only the matching completion is merged.
        self.assertEqual(len(self.app.state()['notifications']), 2)
        with sqlite3.connect(path, factory=backend.ClosingConnection) as db:
            db.execute('INSERT INTO sessions VALUES (?,?)', ('self-other', 'nudge-request'))
        self.add_message(path, 10, 'Unmapped companion request completion', session_id='self-other')
        self.assertEqual(len(self.app.state()['notifications']), 3)

    def test_reflection_prompt_projects_concrete_assistance_outcomes_and_provenance(self):
        path = self.fresh_history_fixture()
        history = backend.recent_history(path)
        self.assertEqual(history[-1]['assistant_reply']['message_id'], 2)
        generated = {'proactive': [], 'ideas': [{'title': 'Build a project review checklist',
                      'body': 'For the project discussed earlier', 'prompt': 'Draft a review checklist',
                      'source_session': 'real', 'message_id': 1}]}
        with patch.object(self.app, 'chat', return_value=(json.dumps(generated), 'analysis')) as chat:
            self.app._analyze()
        prompt = chat.call_args.args[0]
        for phrase in ('past conversations', 'projects they describe', 'concrete actions the assistant',
                       'open loops', 'assistant replies', 'Do not execute or create cron jobs'):
            self.assertIn(phrase, prompt)
        self.assertTrue(chat.call_args.kwargs['analysis'])
        self.assertIn('assistant_reply', prompt)
        self.assertIn('conversation-analysis; session=real; message=1', self.app.state()['ideas'][0]['source'])
        with sqlite3.connect(path, factory=backend.ClosingConnection) as db:
            db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?)', (7, 'real', 'user', 'Unrelated newer history', 7, 1))
        self.app.last_history_check = float('-inf')
        with patch.object(self.app, 'chat', side_effect=AssertionError('No automatic paid loop')):
            self.assertEqual(self.app.state()['ideas'][0]['title'], 'Build a project review checklist')

    def test_message_checkpoint_rolls_back_with_failed_notification_batch(self):
        path = self.stream_fixture()
        self.add_message(path, 7)
        self.add_message(path, 8)
        original = self.app._notify
        def fail_second(db, nid, title, body, job_id=None):
            original(db, nid, title, body, job_id)
            if db.execute('SELECT count(*) FROM notifications').fetchone()[0] == 2:
                raise RuntimeError('Fixture interrupted import')
        with patch.object(self.app, '_notify', side_effect=fail_second):
            with self.assertRaisesRegex(RuntimeError, 'interrupted import'):
                self.app.poll_messages()
        with self.app.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM notifications').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM seen').fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT value FROM meta WHERE key='assistant_cursor'").fetchone()[0], '6')
        self.assertEqual(self.app.poll_messages(), 2)
        self.assertEqual(len(self.app.state()['notifications']), 2)

    def test_empty_model_reflection_persists_across_new_history_and_restart(self):
        path = self.fresh_history_fixture()
        with patch.object(self.app, 'chat', return_value=('{"proactive":[],"ideas":[]}', 'analysis')):
            self.app._analyze()
        with sqlite3.connect(path, factory=backend.ClosingConnection) as db:
            db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?)', (7, 'real', 'user', 'New unrelated project', 7, 1))
        app2 = backend.Companion(self.home, hermes=self.hermes, profile='default')
        try:
            self.assertEqual(app2.state()['ideas'], [])
            self.assertEqual(app2.state()['proactive'], [])
        finally:
            app2.close()

    def test_non_ascii_auth_rejected_not_crash(self):
        self.assertEqual(self.http(headers={'Authorization': 'Bearer caf\u00e9'})[0], 401)
        self.assertEqual(self.http(path='/?token=%E2%98%83', auth=False)[0], 401)

    def test_restart_marks_interrupted_request_error(self):
        with self.app.connect() as db:
            db.execute('INSERT INTO requests VALUES (?,?,?,?,?)', ('interrupted', 'Work', 'running', '', backend.now()))
        app2 = backend.Companion(self.home, hermes=self.hermes, profile='default')
        try:
            self.assertEqual(app2.state()['requests'][0]['status'], 'error')
            self.assertEqual(len(app2.state()['notifications']), 1)
        finally:
            app2.close()

    def test_info_and_instance_profile(self):
        self.app.profile = 'work'
        status, _, body = self.http(path='/api/info')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {'kind': 'hermes-nudge', 'protocol_version': 1,
                                          'profile': 'work', 'origin': self.server.origin, 'tls': False})
        self.assertEqual(json.loads(self.http()[2])['status']['profile'], 'work')
        self.assertNotIn(self.app.token, body.decode())

    def test_profile_home_and_cli_environment(self):
        app = backend.Companion(self.home, hermes=self.hermes, profile='work')
        try:
            self.assertEqual(app.home, self.home / 'profiles' / 'work')
            self.assertEqual(backend.profile_home(app.home, 'work'), app.home)
            self.assertEqual(backend.profile_home(app.home, 'default'), self.home)
            process = Mock(returncode=0)
            process.communicate.return_value = ('OK', '')
            with patch.dict(os.environ, {'HERMES_PROFILE': 'other', 'HERMES_HOME': 'other',
                                        'HERMES_SESSION_ID': 'private', 'HERMES_YOLO': '1'}), \
                    patch.object(backend.subprocess, 'Popen', return_value=process) as spawn:
                self.assertEqual(app.cli(['cron', 'list']), 'OK')
            self.assertEqual(spawn.call_args.args[0], [str(self.hermes), '--profile', 'work', 'cron', 'list'])
            env = spawn.call_args.kwargs['env']
            self.assertEqual(env['HERMES_HOME'], str(app.home))
            self.assertEqual(env['HERMES_PROFILE'], 'work')
            self.assertNotIn('HERMES_YOLO', env)
            self.assertNotIn('HERMES_SESSION_ID', env)
        finally:
            app.close()
        for bad in ('../work', '', 'Work', 'a/b'):
            with self.assertRaises(ValueError):
                backend.profile_home(self.home, bad)
        with patch.dict(os.environ, {'HERMES_PROFILE': 'work'}):
            self.assertEqual(backend.arguments([])[1].profile, 'work')
            self.assertEqual(backend.arguments(['--profile', 'default'])[1].profile, 'default')
        with patch.dict(os.environ, {}, clear=True):
            args = backend.arguments([])[1]
            self.assertEqual(args.profile, 'default')
            self.assertEqual(args.host, '127.0.0.1')
            self.assertFalse(args.allow_insecure_http)

    def test_executable_discovery(self):
        with patch.object(backend.shutil, 'which', return_value=str(self.hermes)):
            self.assertEqual(backend.discover_hermes(), self.hermes)
        with patch.object(backend.shutil, 'which', return_value=None), \
                patch.object(backend.Path, 'home', return_value=self.home):
            candidate = self.home / '.hermes' / 'hermes-agent' / 'venv' / 'bin' / 'hermes'
            candidate.parent.mkdir(parents=True)
            candidate.write_text('fixture')
            candidate.chmod(0o700)
            self.assertEqual(backend.discover_hermes(), candidate)
            self.assertEqual(backend.discover_hermes(self.hermes), self.hermes)

    def test_network_listener_policy_and_tls_validation(self):
        for host in ('0.0.0.0', '::', 'bridge.example'):
            with self.assertRaises(ValueError):
                backend.listener_options(host, 'https://nudge.example', None, None, False)
        with self.assertRaises(ValueError):
            backend.listener_options('0.0.0.0', None, None, None, True)
        self.assertEqual(backend.listener_options('0.0.0.0', 'http://nudge.example:47831', None, None, True),
                         ('http://nudge.example:47831', None))
        self.assertEqual(backend.listener_options('::1', None, None, None, False), (None, None))
        for cert, key in (('cert', None), (None, 'key')):
            with self.assertRaises(ValueError):
                backend.listener_options('127.0.0.1', None, cert, key, False)
        for host in ('*', '*.example', 'http://example', ''):
            with self.assertRaises(ValueError):
                backend.listener_options(host, None, None, None, True)
        for url in ('https://*.example', 'https://user:pass@nudge.example', 'https://nudge.example/path',
                    'https://nudge.example?x=1', 'https://nudge.example#x', 'https://nudge.example:bad',
                    'https://0.0.0.0', 'file:///nudge', 'https://nudge.example\n'):
            with self.assertRaises(ValueError):
                backend.public_origin(url)
        with self.assertRaises(OSError):
            backend.listener_options('127.0.0.1', None, str(self.home / 'missing-cert'), str(self.home / 'missing-key'), False)
        with patch.object(backend, 'Companion') as companion, patch.object(backend.ssl, 'SSLContext') as context:
            context.return_value.load_cert_chain.side_effect = ssl.SSLError('invalid certificate')
            with patch('sys.stderr'), self.assertRaises(SystemExit) as failure:
                backend.main(['--hermes-home', str(self.home), '--tls-cert', 'cert', '--tls-key', 'key'])
            self.assertEqual(failure.exception.code, 2)
            companion.assert_not_called()

    def test_reverse_proxy_exact_host_origin_and_secure_cookie(self):
        server = backend.Server(self.app, 0, public_url='https://nudge.example')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        old = self.server
        self.server = server
        try:
            self.assertEqual(self.http(headers={'Host': 'nudge.example', 'Origin': 'https://nudge.example'})[0], 200)
            self.assertEqual(self.http(headers={'Host': 'nudge.example'})[0], 200)
            self.assertEqual(self.http()[0], 200)  # canonical bind host also accepted
            for headers in ({'Host': '*.example'}, {'Host': 'evil.example'}, {'Host': 'nudge.example:443'},
                            {'Host': 'nudge.example', 'Origin': 'http://nudge.example'},
                            {'Host': 'nudge.example', 'Origin': 'null'}, {'Host': '0.0.0.0'}):
                self.assertEqual(self.http(headers=headers)[0], 403)
            status, headers, _ = self.http(path='/?token=' + self.app.token, auth=False,
                                          headers={'Host': 'nudge.example'})
            self.assertEqual(status, 303)
            self.assertIn('; Secure', headers['Set-Cookie'])
            self.assertNotIn('Access-Control-Allow-Origin', headers)
        finally:
            self.server = old
            server.shutdown()
            server.server_close()
            thread.join()

    def test_duplicate_host_and_origin_rejected(self):
        for name, value in (('Host', 'evil.example'), ('Origin', self.server.origin)):
            connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
            try:
                connection.putrequest('GET', '/api/info')
                connection.putheader('Authorization', 'Bearer ' + self.app.token)
                connection.putheader(name, value)
                if name == 'Origin':
                    connection.putheader(name, value)
                connection.endheaders()
                response = connection.getresponse()
                self.assertEqual(response.status, 403)
                response.read()
            finally:
                connection.close()

    def test_all_interface_host_is_not_trusted(self):
        server = backend.Server(self.app, 0, host='0.0.0.0', public_url='http://nudge.example:47831',
                                allow_insecure_http=True)
        try:
            self.assertEqual(server.trusted_hosts, {'nudge.example:47831'})
            self.assertEqual(server.trusted_origins, {'http://nudge.example:47831'})
            self.assertFalse(server.secure_cookie)
        finally:
            server.server_close()

    def test_timeout_posix_group_and_windows_fallback(self):
        for platform in (('posix', 'nt') if hasattr(backend.signal, 'SIGKILL') else ('nt',)):
            process = Mock(pid=123)
            process.communicate.side_effect = [subprocess.TimeoutExpired('hermes', 1), ('', '')]
            with patch.object(backend.subprocess, 'Popen', return_value=process) as spawn, \
                    patch.object(backend.os, 'name', platform), \
                    patch.object(backend.subprocess, 'run') as taskkill, \
                    patch.object(backend.os, 'killpg', create=True) as killpg:
                with self.assertRaisesRegex(RuntimeError, 'timed out.*not retried'):
                    self.app.cli(['cron', 'list'], timeout=1)
                self.assertEqual(spawn.call_args.kwargs['start_new_session'], platform != 'nt')
                if platform == 'posix':
                    killpg.assert_called_once_with(123, backend.signal.SIGKILL)
                    process.kill.assert_not_called()
                    taskkill.assert_not_called()
                else:
                    killpg.assert_not_called()
                    self.assertEqual(taskkill.call_args.args[0], ['taskkill', '/PID', '123', '/T', '/F'])
                    process.kill.assert_called_once()
                self.assertEqual(process.communicate.call_count, 2)

    def test_windows_timeout_retained_pipes_do_not_block_worker(self):
        process = Mock(pid=123)
        process.communicate.side_effect = subprocess.TimeoutExpired('hermes', 1)
        with patch.object(backend.subprocess, 'Popen', return_value=process), \
                patch.object(backend.os, 'name', 'nt'), \
                patch.object(backend.subprocess, 'run', side_effect=OSError('taskkill unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'timed out.*not retried'):
                self.app.cli(['cron', 'list'], timeout=1)
        process.kill.assert_called_once()
        process.wait.assert_called_once_with(timeout=5)
        process.stdout.close.assert_not_called()
        process.stderr.close.assert_not_called()

    def test_scheduler_marker_diagnostics_no_cli(self):
        self.cron_store([])
        marker = self.home / 'cron' / 'ticker_heartbeat'
        with patch.object(self.app, 'cli', side_effect=AssertionError('No CLI polls')):
            self.assertFalse(self.app.state()['status']['scheduler']['heartbeat_fresh'])
            marker.write_text(str(time.time() - 10) + ' 123')
            diagnostics = self.app.state()['status']['scheduler']
            self.assertTrue(diagnostics['heartbeat_fresh'])
            self.assertGreaterEqual(diagnostics['heartbeat_age_seconds'], 10)
            marker.write_text(str(time.time() - 600))
            self.assertFalse(self.app.state()['status']['scheduler']['heartbeat_fresh'])
            for invalid in ('broken', 'nan', 'inf', '-1'):
                marker.write_text(invalid)
                self.assertIsNone(self.app.state()['status']['scheduler']['heartbeat_at'])

    @unittest.skipUnless(backend.shutil.which('openssl'), 'TLS fixture generation needs openssl')
    def test_real_tls_listener_info_auth_and_secure_cookie(self):
        cert, key = self.home / 'cert.pem', self.home / 'key.pem'
        subprocess.run([backend.shutil.which('openssl'), 'req', '-x509', '-newkey', 'rsa:2048',
                        '-nodes', '-keyout', str(key), '-out', str(cert), '-days', '1',
                        '-subj', '/CN=localhost'], check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=30)
        server = backend.Server(self.app, 0, tls_cert=str(cert), tls_key=str(key))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            # Only this temporary test certificate skips verification; production clients must validate TLS.
            connection = http.client.HTTPSConnection('127.0.0.1', server.server_port,
                                                    context=ssl._create_unverified_context(), timeout=5)
            connection.request('GET', '/api/info')
            response = connection.getresponse()
            self.assertEqual(response.status, 401)
            response.read()
            connection.close()
            connection = http.client.HTTPSConnection('127.0.0.1', server.server_port,
                                                    context=ssl._create_unverified_context(), timeout=5)
            connection.request('GET', '/api/info', headers={'Authorization': 'Bearer ' + self.app.token})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertTrue(json.loads(response.read())['tls'])
            connection.close()
            connection = http.client.HTTPSConnection('127.0.0.1', server.server_port,
                                                    context=ssl._create_unverified_context(), timeout=5)
            connection.request('GET', '/?token=' + self.app.token)
            response = connection.getresponse()
            self.assertEqual(response.status, 303)
            self.assertIn('; Secure', response.getheader('Set-Cookie'))
            response.read()
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_read_only_analysis_rejects_tool_use(self):
        stream = '{"type":"tool_use","name":"terminal"}\n{"type":"result","text":"OK","exit_code":0}'
        with patch.object(self.app, 'cli', return_value=stream):
            with self.assertRaisesRegex(RuntimeError, 'unexpectedly used a tool'):
                self.app.chat('read only', analysis=True)


if __name__ == '__main__':
    unittest.main()
