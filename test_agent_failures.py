"""Failure injection: real tool functions, deterministic SDK replies, observable logs."""
import io
import json
import os
from contextlib import nullcontext, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import requests

import rag
import test_agent


class AgentFailureTests(test_agent.AgentCase):
    async def exercise(self, case, tool, arguments, expected_status, evidence_label, injection=None):
        def handler(payload):
            if len(self.sent) == 1:
                return test_agent.completion(calls=[test_agent.tool_call(tool, json.dumps(arguments, ensure_ascii=False))])
            returned = json.loads(payload['messages'][-1]['content'])
            self.assertEqual(returned['status'], expected_status)
            # Deliberately generic: production code must still expose missing evidence.
            return test_agent.completion('分析已完成；现有结果不足以支持完整判断。')
        output = io.StringIO()
        with self.sdk_client(handler), (injection or nullcontext()), redirect_stdout(output):
            response = await self.client.post('/api/agent', json={'question': '请基于实际工具证据回答，不要猜测缺失的信息。'})
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result['iterations'], 2)
        self.assertEqual(len(result['tool_calls']), 1)
        call = result['tool_calls'][0]
        self.assertEqual(call['tool'], tool)
        self.assertEqual(call['arguments'], arguments)
        self.assertEqual(call['status'], expected_status)
        self.assertEqual(call['result']['status'], expected_status)
        self.assertEqual(call['sequence'], 1)
        self.assertGreaterEqual(call['elapsed_ms'], 0)
        self.assertIn(evidence_label, result['answer'])
        self.assertIn('证据缺失', result['answer'])
        logs = [json.loads(line.removeprefix('[agent.tool] ')) for line in output.getvalue().splitlines() if line.startswith('[agent.tool] ')]
        self.assertEqual(logs, result['tool_calls'])
        path = os.environ.get('GREENMATE_FAILURE_EVIDENCE')
        if path:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('a', encoding='utf-8') as file:
                file.write(json.dumps({'case': case, 'mode': 'real_python_tools_with_mocked_llm_transport', 'result': result, 'observable_logs': logs}, ensure_ascii=False) + '\n')
        print(f'[failure-verification] {case}: status={expected_status}; actual_tool={tool}; sequence=1; elapsed_ms={call["elapsed_ms"]}; missing_evidence={evidence_label}', flush=True)
        return result

    async def test_history_negative_hours_is_error(self):
        result = await self.exercise('invalid_history_hours', 'get_environment_history', {'hours': -1}, 'error', '历史数据')
        self.assertIn('hours', result['tool_calls'][0]['result']['error'])

    async def test_weather_timeout_is_unavailable(self):
        result = await self.exercise(
            'weather_timeout', 'get_weather_forecast', {'location': '北京'}, 'unavailable', '未来12小时天气预报',
            patch('tools.requests.get', side_effect=requests.Timeout('injected timeout: no actual waiting')),
        )
        self.assertIn('超时', result['tool_calls'][0]['result']['error'])

    async def test_unknown_knowledge_is_ok_with_empty_items(self):
        # No hardcoded empty result: run the real vector retriever/model/fallback.
        with patch('tools.vector_search', wraps=rag.vector_search) as search:
            result = await self.exercise('empty_knowledge', 'search_plant_knowledge', {'query': '不存在的内容xyz'}, 'ok', '匹配的本地植物知识')
        search.assert_called_once_with('不存在的内容xyz')
        self.assertEqual(result['tool_calls'][0]['result']['data']['items'], [])
        self.assertIsNone(result['tool_calls'][0]['result']['error'])


if __name__ == '__main__':
    import unittest
    unittest.main()
