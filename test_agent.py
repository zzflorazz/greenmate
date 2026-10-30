"""Deterministic SDK protocol tests; registered Python tools execute for real."""
import io
import json
import os
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import httpx2
from openai import AsyncOpenAI

import agent
import db
import state
import tools
from main import app


def tool_call(name, arguments='{}', call_id='call_1'):
    return {'id': call_id, 'type': 'function', 'function': {'name': name, 'arguments': arguments}}


def completion(content=None, calls=None):
    message = {'role': 'assistant', 'content': content}
    if calls:
        message['tool_calls'] = calls
    return httpx2.Response(200, json={
        'id': 'agent-test', 'object': 'chat.completion', 'created': 0, 'model': 'test',
        'choices': [{'index': 0, 'message': message, 'finish_reason': 'tool_calls' if calls else 'stop'}],
    })


class AgentCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.previous = state._current_state
        self.temp_dir = TemporaryDirectory()
        self.db_patch = patch('db.DB_PATH', str(Path(self.temp_dir.name) / 'agent.db'))
        self.db_patch.start()
        self.key_patch = patch.dict(os.environ, {'GREENMATE_API_KEY': 'offline-agent-test'})
        self.key_patch.start()
        db.init_db()
        state.load_state()
        self.client = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url='http://greenmate.test')
        self.sent = []

    async def asyncTearDown(self):
        await self.client.aclose()
        state._current_state = self.previous
        self.key_patch.stop()
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def sdk_client(self, handler):
        def wrapped(request):
            payload = json.loads(request.content)
            self.sent.append(payload)
            self.assertEqual(payload['tools'], tools.TOOL_SCHEMAS)
            self.assertFalse(payload['parallel_tool_calls'])
            return handler(payload)
        def factory(**kwargs):
            return AsyncOpenAI(**kwargs, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(wrapped)))
        return patch('agent.AsyncOpenAI', side_effect=factory)


class AgentTests(AgentCase):
    async def test_direct_answer_without_tools(self):
        with self.sdk_client(lambda payload: completion('你好，我是 GreenMate。')):
            response = await self.client.post('/api/agent', json={'question': '你好'})
        self.assertEqual(response.json(), {'answer': '你好，我是 GreenMate。', 'tool_calls': [], 'iterations': 1})
        self.assertEqual([m['role'] for m in self.sent[0]['messages']], ['system', 'user'])

    async def test_tool_ids_envelope_trace_and_observable_log(self):
        snapshot = state.get_state()
        def handler(payload):
            if len(self.sent) == 1:
                return completion(calls=[tool_call('get_current_environment', call_id='state_1')])
            messages = payload['messages']
            self.assertEqual([m['role'] for m in messages], ['system', 'user', 'assistant', 'tool'])
            self.assertEqual(messages[-1]['tool_call_id'], 'state_1')
            self.assertEqual(json.loads(messages[-1]['content'])['data'], snapshot)
            return completion('当前是模拟环境。')
        output = io.StringIO()
        with self.sdk_client(handler), redirect_stdout(output):
            result = await agent.run_agent('查看当前环境')
        record = result['tool_calls'][0]
        self.assertEqual(set(record), {'sequence', 'tool', 'arguments', 'status', 'result', 'elapsed_ms'})
        self.assertEqual(record['sequence'], 1)
        self.assertEqual(record['status'], 'ok')
        self.assertEqual(record['result']['data'], snapshot)
        self.assertGreaterEqual(record['elapsed_ms'], 0)
        logged = json.loads(next(line.removeprefix('[agent.tool] ') for line in output.getvalue().splitlines() if line.startswith('[agent.tool] ')))
        self.assertEqual(logged, record)

    async def test_multiple_calls_are_serial_and_sequence_is_contiguous(self):
        events = []
        def current():
            events.append('current')
            return tools.tool_result('ok', 'SIMULATED', state.get_state())
        def history(hours=24):
            self.assertEqual(events, ['current'])
            events.append('history')
            return tools.tool_result('ok', 'SQLITE', {'items': []})
        def handler(payload):
            if len(self.sent) == 1:
                return completion(calls=[tool_call('get_current_environment', call_id='a'), tool_call('get_environment_history', call_id='b')])
            self.assertEqual([m['tool_call_id'] for m in payload['messages'] if m['role'] == 'tool'], ['a', 'b'])
            return completion('历史数据为空。')
        with patch.dict(agent.TOOL_FUNCTIONS, {'get_current_environment': current, 'get_environment_history': history}), self.sdk_client(handler), redirect_stdout(io.StringIO()):
            result = await agent.run_agent('查看环境和历史')
        self.assertEqual(events, ['current', 'history'])
        self.assertEqual([entry['sequence'] for entry in result['tool_calls']], [1, 2])

    async def test_five_evidence_tools_even_with_legacy_write_flag(self):
        expected = {'get_current_environment', 'get_environment_history', 'get_weather_forecast', 'search_plant_knowledge', 'predict_next_attention'}
        self.assertEqual(set(tools.TOOL_FUNCTIONS), expected)
        self.assertEqual({schema['function']['name'] for schema in tools.TOOL_SCHEMAS}, expected)
        before = state.get_state()
        with self.sdk_client(lambda payload: completion('本工具集不支持修改环境。')):
            response = await self.client.post('/api/agent', json={'question': '把温度调到30度', 'allow_write': True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(state.get_state(), before)
        _, denied = agent._execute_tool('set_environment', '{"temperature":30,"humidity":65,"light":12000}')
        self.assertEqual(denied['status'], 'error')

    async def test_invalid_calls_and_tool_exceptions_use_uniform_error(self):
        for name, raw in [('unknown', '{}'), ('get_current_environment', '[]'), ('get_current_environment', '{bad'), ('get_current_environment', '{"extra":1}'), ('search_plant_knowledge', '{}'), ('get_environment_history', '{"hours":NaN}')]:
            _, result = agent._execute_tool(name, raw)
            self.assertEqual(result['status'], 'error')
            self.assertEqual(set(result), {'status', 'source', 'time', 'data', 'error'})
        def broken():
            raise RuntimeError('private details')
        with patch.dict(agent.TOOL_FUNCTIONS, {'get_current_environment': broken}):
            _, result = agent._execute_tool('get_current_environment', '{}')
        self.assertNotIn('private details', result['error'])

    async def test_limit_is_five_model_requests(self):
        with self.sdk_client(lambda payload: completion(calls=[tool_call('get_current_environment', call_id=f'call_{len(self.sent)}')])), redirect_stdout(io.StringIO()):
            result = await agent.run_agent('持续检查环境')
        self.assertEqual(len(self.sent), 5)
        self.assertEqual(result['iterations'], 5)
        self.assertEqual([call['sequence'] for call in result['tool_calls']], [1, 2, 3, 4, 5])
        self.assertIn('上限', result['answer'])

    async def test_api_error_keeps_executed_trace(self):
        def handler(payload):
            if len(self.sent) == 1:
                return completion(calls=[tool_call('get_current_environment')])
            return httpx2.Response(500, json={'error': {'message': 'private upstream details'}})
        with self.sdk_client(handler), redirect_stdout(io.StringIO()):
            response = await self.client.post('/api/agent', json={'question': '查看环境'})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()['tool_calls'][0]['result']['data'], state.get_state())
        self.assertNotIn('private upstream details', response.text)

    async def test_missing_key_and_question_validation(self):
        with patch.dict(os.environ, {'GREENMATE_API_KEY': ''}):
            response = await self.client.post('/api/agent', json={'question': '查看环境'})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['iterations'], 0)
        self.assertEqual((await self.client.post('/api/agent', json={'question': '   '})).status_code, 422)


if __name__ == '__main__':
    unittest.main()
