"""Fault-injected native SDK requests; no provider or real retry delays needed."""
import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx2
from openai import AsyncOpenAI

import agent
import db
import test_agent


class RetryTests(test_agent.AgentCase):
    def native_client(self, target, handler):
        def wrapped(request):
            self.sent.append(json.loads(request.content))
            return handler(request)
        def factory(**kwargs):
            self.assertEqual(kwargs['max_retries'], 0)
            return AsyncOpenAI(**kwargs, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(wrapped)))
        return patch(target + '.AsyncOpenAI', side_effect=factory)

    def save_evidence(self, name, response, output):
        destination = os.environ.get('GREENMATE_RETRY_EVIDENCE')
        if destination:
            path = Path(destination)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('a', encoding='utf-8') as file:
                file.write(json.dumps({'case': name, 'mode': 'injected_sdk_http_transport_real_python_tools',
                                       'http_status': response.status_code, 'result': response.json(),
                                       'logs': output.getvalue()}, ensure_ascii=False) + '\n')

    async def test_agent_summary_502_three_attempts_retains_tool_once(self):
        executions = []
        original = agent.TOOL_FUNCTIONS['get_current_environment']
        def current():
            executions.append(True)
            return original()
        def handler(request):
            if len(self.sent) == 1:
                return test_agent.completion(calls=[test_agent.tool_call('get_current_environment')])
            return httpx2.Response(502, json={'error': {'message': 'private injected provider message'}})
        output = io.StringIO()
        delay = AsyncMock()
        with self.native_client('agent', handler), patch.dict(agent.TOOL_FUNCTIONS, {'get_current_environment': current}), patch('llm_retry.asyncio.sleep', delay), redirect_stdout(output):
            response = await self.client.post('/api/agent', json={'question': '查看当前环境'})
        body = response.json()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(len(self.sent), 4)
        self.assertEqual(len(executions), 1)
        self.assertEqual(body['iterations'], 2)
        self.assertEqual(len(body['tool_calls']), 1)
        self.assertEqual(body['tool_calls'][0]['status'], 'ok')
        self.assertEqual(body['llm_error']['status_code'], 502)
        self.assertEqual(self.sent[1:], [self.sent[1]] * 3)
        self.assertEqual([call.args[0] for call in delay.await_args_list], [1, 2])
        failures = [line for line in output.getvalue().splitlines() if 'status_code=502' in line]
        self.assertEqual(len(failures), 3)
        for attempt, line in enumerate(failures, 1):
            self.assertIn(f'attempt={attempt}', line)
            self.assertIn('error_type=InternalServerError', line)
        self.assertNotIn('private injected', response.text)
        self.save_evidence('agent_summary_502_retains_tool_once', response, output)

    async def test_ask_502_three_attempts_preserves_snapshot_and_history_once(self):
        output = io.StringIO()
        with self.native_client('llm', lambda request: httpx2.Response(502, json={'error': {'message': 'injected'}})), patch('llm_retry.asyncio.sleep', AsyncMock()), patch('main.vector_search', return_value=[]), redirect_stdout(output):
            response = await self.client.post('/api/ask', json={'question': '要浇水吗？'})
        self.assertEqual(len(self.sent), 3)
        self.assertEqual(response.json()['llm_error']['status_code'], 502)
        self.assertEqual(response.json()['tool_calls'], [])
        self.assertIn('used_state', response.json())
        self.assertEqual([row['role'] for row in db.load_recent_chat()], ['user'])
        self.save_evidence('ask_502_three_attempts', response, output)

    async def test_transient_failures_recover_in_both_paths(self):
        for endpoint, target in [('/api/ask', 'llm'), ('/api/agent', 'agent')]:
            with self.subTest(endpoint=endpoint):
                self.sent = []
                def handler(request):
                    if len(self.sent) <= 2:
                        return httpx2.Response([502, 503][len(self.sent) - 1], json={'error': {'message': 'injected'}})
                    return test_agent.completion('正常回答')
                delay = AsyncMock()
                with self.native_client(target, handler), patch('llm_retry.asyncio.sleep', delay), patch('main.vector_search', return_value=[]), redirect_stdout(io.StringIO()):
                    response = await self.client.post(endpoint, json={'question': '查看模拟状态'})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['answer'], '正常回答')
                self.assertNotIn('llm_error', response.json())
                self.assertEqual([call.args[0] for call in delay.await_args_list], [1, 2])
                self.assertEqual(len(self.sent), 3)

    async def test_other_http_errors_are_never_retried(self):
        for endpoint, target in [('/api/ask', 'llm'), ('/api/agent', 'agent')]:
            for code in (400, 401, 403, 429, 500):
                with self.subTest(endpoint=endpoint, code=code):
                    self.sent = []
                    delay = AsyncMock()
                    with self.native_client(target, lambda request: httpx2.Response(code, json={'error': {'message': 'private'}})), patch('llm_retry.asyncio.sleep', delay), patch('main.vector_search', return_value=[]), redirect_stdout(io.StringIO()):
                        response = await self.client.post(endpoint, json={'question': '测试'})
                    self.assertEqual(len(self.sent), 1)
                    delay.assert_not_awaited()
                    self.assertEqual(response.json()['llm_error']['status_code'], code)
                    self.assertNotIn('private', response.text)

    async def test_503_504_timeout_and_connection_have_bounded_retries(self):
        for endpoint, target in [('/api/ask', 'llm'), ('/api/agent', 'agent')]:
            for kind in (503, 504, 'timeout', 'connection'):
                with self.subTest(endpoint=endpoint, kind=kind):
                    self.sent = []
                    def handler(request):
                        if kind == 'timeout':
                            raise httpx2.ReadTimeout('injected', request=request)
                        if kind == 'connection':
                            raise httpx2.ConnectError('injected', request=request)
                        return httpx2.Response(kind, json={'error': {'message': 'injected'}})
                    delay = AsyncMock()
                    with self.native_client(target, handler), patch('llm_retry.asyncio.sleep', delay), patch('main.vector_search', return_value=[]), redirect_stdout(io.StringIO()):
                        response = await self.client.post(endpoint, json={'question': '测试'})
                    self.assertEqual(len(self.sent), 3)
                    self.assertEqual([call.args[0] for call in delay.await_args_list], [1, 2])
                    self.assertEqual(response.json()['llm_error']['status_code'], kind if isinstance(kind, int) else None)
                    if endpoint == '/api/agent':
                        self.assertEqual(response.json()['tool_calls'], [])
