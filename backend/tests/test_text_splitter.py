import unittest

from TextSlicer.SimpleTextSplitter import SimpleTextSplitter


class SimpleTextSplitterTests(unittest.TestCase):
    def test_large_text_is_split_without_reencoding_the_remaining_document(self):
        splitter = SimpleTextSplitter(max_tokens=32, min_tokens=12)
        text = "计算机科学研究计算与信息。" * 2_000

        blocks = splitter.split_text(text)

        self.assertGreater(len(blocks), 1)
        self.assertEqual("".join(chunk for _, chunk in blocks), text)
        self.assertLessEqual(
            max(len(splitter.encoder.encode(chunk)) for _, chunk in blocks),
            32,
        )
        self.assertTrue(all(chunk for _, chunk in blocks))


if __name__ == "__main__":
    unittest.main()
