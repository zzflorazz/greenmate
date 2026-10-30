"""Deterministic index/route tests; real-model quality is checked separately."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import rag


def fake_embedding(text):
    if text.startswith('植物：绿萝') or text == '植物缺水怎么办？':
        head = [1.0, 0.0]
    elif text.startswith('植物：多肉'):
        head = [0.8, 0.2]
    else:
        head = [0.0, 1.0]
    return head + [0.0] * (rag.EMBEDDING_DIM - 2)


class VectorIndexTests(unittest.TestCase):
    def setUp(self):
        self.previous_knowledge = rag._knowledge
        self.previous_index = rag._index
        self.records = rag.get_knowledge()
        self.temp_dir = TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / 'plants.json'
        self.path.write_text(json.dumps(self.records, ensure_ascii=False), encoding='utf-8')
        self.index_path = self.path.with_name('index.json')
        self.path_patch = patch('rag.KNOWLEDGE_PATH', self.path)
        self.path_patch.start()
        self.encoder_patch = patch('rag.get_embedding', side_effect=fake_embedding)
        self.encoder = self.encoder_patch.start()
        rag._knowledge = None
        rag._index = None
        rag.load_knowledge()

    def tearDown(self):
        rag._knowledge = self.previous_knowledge
        rag._index = self.previous_index
        self.encoder_patch.stop()
        self.path_patch.stop()
        self.temp_dir.cleanup()

    def test_json_index_and_restart_reuse_without_reencoding(self):
        built = rag.build_knowledge_index()
        self.assertEqual(self.encoder.call_count, len(self.records))
        self.assertEqual(json.loads(self.index_path.read_text()), built)
        self.assertEqual(built['model'], rag.MODEL_NAME)
        self.assertEqual(len(built['items'][0]['embedding']), 384)
        rag._index = None
        self.encoder.reset_mock()
        self.assertEqual(rag.build_knowledge_index(), built)
        self.encoder.assert_not_called()

    def test_force_and_knowledge_changes_rebuild(self):
        before = rag.build_knowledge_index()
        self.encoder.reset_mock()
        rag.build_knowledge_index(force=True)
        self.assertEqual(self.encoder.call_count, len(self.records))
        self.encoder.reset_mock()
        self.records[0]['tips'] += ' 更新的知识。'
        self.path.write_text(json.dumps(self.records, ensure_ascii=False), encoding='utf-8')
        rag.load_knowledge()
        rebuilt = rag.build_knowledge_index()
        self.assertNotEqual(rebuilt['knowledge_hash'], before['knowledge_hash'])
        self.assertEqual(self.encoder.call_count, len(self.records))
        self.assertEqual(rebuilt['items'][0]['record']['tips'], self.records[0]['tips'])

    def test_corrupt_or_wrong_model_index_rebuilds(self):
        good = rag.build_knowledge_index()
        corrupt = json.loads(json.dumps(good))
        corrupt['items'][0]['embedding'] = [1.0]
        wrong_model = {**good, 'model': 'different-model'}
        for content in ('invalid JSON', json.dumps(corrupt), json.dumps(wrong_model)):
            rag._index = None
            self.index_path.write_text(content, encoding='utf-8')
            self.encoder.reset_mock()
            rebuilt = rag.build_knowledge_index()
            self.assertEqual(self.encoder.call_count, len(self.records))
            self.assertTrue(rag._valid_index(rebuilt, self.records))

    def test_cosine_ranking_works_without_keyword_match(self):
        query = '植物缺水怎么办？'
        self.assertEqual(rag.simple_search(query), [])
        result = rag.vector_search(query)
        self.assertEqual([record['name'] for record in result], ['绿萝', '多肉'])
        self.assertEqual(len(rag.vector_search(query, top_n=1)), 1)
        # The index is cached; only the query is encoded after the first build.
        self.encoder.reset_mock()
        rag.vector_search(query)
        self.encoder.assert_called_once_with(query)

    def test_model_failure_falls_back_to_keyword_search(self):
        rag.build_knowledge_index()
        with patch('rag.get_embedding', side_effect=RuntimeError('model unavailable')), patch('builtins.print') as log:
            result = rag.vector_search('绿萝怎么浇水？')
        self.assertEqual(result, rag.simple_search('绿萝怎么浇水？'))
        log.assert_called_once()

    def test_failed_rebuild_preserves_existing_index(self):
        original = rag.build_knowledge_index()
        before = self.index_path.read_bytes()
        with patch('rag.get_embedding', side_effect=OSError('unavailable')):
            with self.assertRaises(OSError):
                rag.build_knowledge_index(force=True)
        self.assertEqual(self.index_path.read_bytes(), before)
        self.assertEqual(rag._index, original)

    def test_empty_query_or_zero_limit_does_not_encode(self):
        self.assertEqual(rag.vector_search(''), [])
        self.assertEqual(rag.vector_search('绿萝', top_n=0), [])
        self.encoder.assert_not_called()


if __name__ == '__main__':
    unittest.main()
