import unittest
from unittest.mock import MagicMock, patch

import embeddings


class EmbeddingTests(unittest.TestCase):
    def test_cosine_values(self):
        self.assertAlmostEqual(embeddings.cosine_sim([1, 2], [2, 4]), 1)
        self.assertAlmostEqual(embeddings.cosine_sim([1, 0], [0, 1]), 0)
        self.assertAlmostEqual(embeddings.cosine_sim([1, 0], [-1, 0]), -1)
        self.assertEqual(embeddings.cosine_sim([0, 0], [1, 2]), 0)
        self.assertEqual(embeddings.cosine_sim([], []), 0)

    def test_invalid_cosine_vectors(self):
        for a, b in (([1], [1, 2]), ([float('nan')], [1]), ([float('inf')], [1])):
            with self.assertRaises(ValueError):
                embeddings.cosine_sim(a, b)

    def test_embedding_uses_local_model_encoding(self):
        model = MagicMock()
        model.encode.return_value.tolist.return_value = [0.5, 0.5]
        with patch('embeddings._get_model', return_value=model):
            self.assertEqual(embeddings.get_embedding('测试句子'), [0.5, 0.5])
        model.encode.assert_called_once_with('测试句子', normalize_embeddings=True, show_progress_bar=False)


if __name__ == '__main__':
    unittest.main()
