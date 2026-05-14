import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


class ChunkerTests(unittest.TestCase):
    def test_short_text_returns_single_chunk(self):
        from knowledge_ingest.chunker import chunk_text
        chunks = chunk_text("Hello world. This is short.", base_metadata={})
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["content"], "Hello world. This is short.")

    def test_long_text_splits_with_overlap(self):
        from knowledge_ingest.chunker import chunk_text
        sentences = [f"Sentence number {i}." for i in range(300)]
        text = " ".join(sentences)
        chunks = chunk_text(text, base_metadata={})
        self.assertGreater(len(chunks), 1)
        for c in chunks:
            self.assertLessEqual(len(c["content"].split()), 500)

    def test_chunks_preserve_base_metadata(self):
        from knowledge_ingest.chunker import chunk_text
        chunks = chunk_text("A. B. C.", base_metadata={"page": 3, "heading": "Intro"})
        self.assertEqual(chunks[0]["metadata"]["page"], 3)
        self.assertEqual(chunks[0]["metadata"]["heading"], "Intro")

    def test_chunks_have_sequential_indices(self):
        from knowledge_ingest.chunker import chunk_text
        text = " ".join([f"S{i}." for i in range(500)])
        chunks = chunk_text(text, base_metadata={})
        for i, c in enumerate(chunks):
            self.assertEqual(c["chunk_index"], i)

    def test_table_marker_preserved_as_single_chunk(self):
        from knowledge_ingest.chunker import chunk_text
        big_table = "| A | B |\n" + "\n".join([f"| row{i} | val{i} |" for i in range(100)])
        chunks = chunk_text(big_table, base_metadata={"is_table": True})
        self.assertEqual(len(chunks), 1)
        self.assertTrue(chunks[0]["metadata"]["is_table"])


if __name__ == "__main__":
    unittest.main()
