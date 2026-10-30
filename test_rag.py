import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

import httpx2

import llm
import rag
import state
from main import app


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.previous = rag._knowledge
        self.records = rag.load_knowledge()

    def tearDown(self):
        rag._knowledge = self.previous

    def test_all_plants_and_explicit_chinese_names(self):
        self.assertEqual({item['name'] for item in self.records}, {'绿萝', '多肉', '龟背竹', '发财树', '文竹', '仙人掌', '番茄'})
        self.assertEqual([item['name'] for item in rag.simple_search('绿萝怎么浇水？')], ['绿萝'])
        self.assertEqual([item['name'] for item in rag.simple_search('仙人掌喜阳吗？')], ['仙人掌'])
        self.assertEqual(len(rag.simple_search('绿萝、文竹、仙人掌如何养护？')), 2)

    def test_generic_keywords_no_match_and_limits(self):
        matches = rag.simple_search('积水', top_n=2)
        self.assertEqual(len(matches), 2)
        self.assertTrue(all('积水' in item['tips'] for item in matches))
        self.assertEqual(len(rag.simple_search('浇水', top_n=1)), 1)
        for query in ('', '   ', '量子计算机', '你好'):
            self.assertEqual(rag.simple_search(query), [])
        self.assertEqual(rag.simple_search('绿萝', top_n=0), [])

    def test_returned_records_do_not_mutate_cache(self):
        result = rag.get_knowledge()
        result[0]['tips'] = 'modified'
        matches = rag.simple_search('绿萝')
        matches[0]['tips'] = 'also modified'
        self.assertEqual(rag.get_knowledge(), self.records)

    def test_messages_include_knowledge_without_changing_history(self):
        history = [{'role': 'user', 'content': '之前的问题', 'timestamp': 'old', 'id': 1}]
        knowledge = rag.simple_search('绿萝怎么浇水？')
        messages = llm.build_messages(state.DEFAULT_STATE, '绿萝怎么浇水？', history, knowledge)
        self.assertEqual([item['role'] for item in messages], ['system', 'user', 'user'])
        self.assertEqual(messages[1], {'role': 'user', 'content': '之前的问题'})
        self.assertIn('参考知识：\n' + json.dumps(knowledge, ensure_ascii=False), messages[-1]['content'])
        self.assertIn('SIMULATED', messages[-1]['content'])
        self.assertTrue(messages[-1]['content'].endswith('用户问题：\n绿萝怎么浇水？'))
        self.assertNotIn('参考知识：', llm.build_messages(state.DEFAULT_STATE, '问题')[-1]['content'])


class KnowledgeEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        encoder_patch = patch('rag.get_embedding', return_value=[1.0] + [0.0] * 383)
        encoder_patch.start()
        self.addCleanup(encoder_patch.stop)
        self.previous_index = rag._index
        rag._index = None
        self.previous_state = state._current_state
        self.previous_knowledge = rag._knowledge
        self.records = rag.get_knowledge()
        self.temp_dir = TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / 'plants.json'
        self.write_records(self.records)
        self.db_patch = patch('db.DB_PATH', str(Path(self.temp_dir.name) / 'test.db'))
        self.path_patch = patch('rag.KNOWLEDGE_PATH', self.path)
        self.db_patch.start()
        self.path_patch.start()
        self.lifespan = app.router.lifespan_context(app)
        await self.lifespan.__aenter__()
        self.client = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url='http://greenmate.test')

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.lifespan.__aexit__(None, None, None)
        state._current_state = self.previous_state
        rag._knowledge = self.previous_knowledge
        rag._index = self.previous_index
        self.path_patch.stop()
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def write_records(self, records):
        self.path.write_text(json.dumps(records, ensure_ascii=False), encoding='utf-8')

    async def test_hot_reload_changes_next_ask_context(self):
        self.assertEqual((await self.client.get('/api/knowledge')).json(), self.records)
        self.records[0]['tips'] += ' 热加载测试：新版盆土检查建议。'
        self.write_records(self.records)
        self.assertNotEqual((await self.client.get('/api/knowledge')).json(), self.records)
        response = await self.client.post('/api/knowledge/reload')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['count'], len(self.records))
        self.assertTrue(response.json()['index_ready'])
        stored = json.loads(self.path.with_name('index.json').read_text(encoding='utf-8'))
        self.assertEqual(stored['items'][0]['record'], self.records[0])
        self.assertEqual((await self.client.get('/api/knowledge')).json(), self.records)
        generate = AsyncMock(return_value='根据知识库中的《绿萝》，请检查盆土。')
        with patch('main.generate_answer', generate):
            response = await self.client.post('/api/ask', json={'question': '绿萝怎么浇水？'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(generate.await_args.kwargs['knowledge'], rag.vector_search('绿萝怎么浇水？'))
        self.assertTrue(any(all(item.get(k) == v for k, v in self.records[0].items()) for item in generate.await_args.kwargs['knowledge']))
        self.assertEqual(generate.await_args.kwargs['knowledge'][0]['citation']['id'], self.records[0]['id'])

    async def test_bad_reload_keeps_previous_cache(self):
        for text in ('invalid JSON', '{}', '[{"name":"绿萝"}]'):
            self.path.write_text(text, encoding='utf-8')
            response = await self.client.post('/api/knowledge/reload')
            self.assertEqual(response.status_code, 400)
            self.assertEqual((await self.client.get('/api/knowledge')).json(), self.records)
        self.path.unlink()
        self.assertEqual((await self.client.post('/api/knowledge/reload')).status_code, 400)
        self.assertEqual(rag.get_knowledge(), self.records)

    async def test_unmatched_question_does_not_inject_knowledge(self):
        generate = AsyncMock(return_value='测试回答')
        with patch('main.generate_answer', generate), patch('main.vector_search', return_value=[]):
            response = await self.client.post('/api/ask', json={'question': '量子计算机'})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(generate.await_args.kwargs['knowledge'])

    async def test_ask_prioritizes_vector_search(self):
        question = '植物缺水怎么办？'
        self.assertEqual(rag.simple_search(question), [])
        generate = AsyncMock(return_value='向量检索测试回答')
        with patch('main.generate_answer', generate), patch('main.vector_search', wraps=rag.vector_search) as vector:
            response = await self.client.post('/api/ask', json={'question': question})
        self.assertEqual(response.status_code, 200)
        vector.assert_called_once_with(question)
        self.assertEqual(len(generate.await_args.kwargs['knowledge']), 2)

    async def test_reload_reports_index_failure_without_losing_knowledge(self):
        self.records[0]['tips'] += ' 新的知识版本。'
        self.write_records(self.records)
        with patch('main.build_knowledge_index', side_effect=OSError('model unavailable')), patch('builtins.print'):
            response = await self.client.post('/api/knowledge/reload')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['index_ready'])
        self.assertEqual((await self.client.get('/api/knowledge')).json(), self.records)
        with patch('rag.get_embedding', side_effect=OSError('model unavailable')), patch('builtins.print'):
            self.assertEqual(rag.vector_search('绿萝'), rag.simple_search('绿萝'))


if __name__ == '__main__':
    unittest.main()
