import codecs
import unittest

from text_encoding import decode_text_bytes


class TextEncodingTests(unittest.TestCase):
    def test_decodes_utf8(self):
        text, encoding = decode_text_bytes("三国志".encode("utf-8"))

        self.assertEqual(text, "三国志")
        self.assertEqual(encoding, "utf-8")

    def test_decodes_gb18030(self):
        source = "三国志 白话文，天下大势，分久必合。"

        text, encoding = decode_text_bytes(source.encode("gb18030"))

        self.assertEqual(text, source)
        self.assertEqual(encoding, "gb18030")

    def test_decodes_big5_without_gb18030_mojibake(self):
        source = "三國志 白話文，天下大勢，分久必合。"

        text, encoding = decode_text_bytes(source.encode("big5"))

        self.assertEqual(text, source)
        self.assertEqual(encoding, "big5")

    def test_decodes_utf16_bom(self):
        source = "三国志"

        text, encoding = decode_text_bytes(codecs.BOM_UTF16_LE + source.encode("utf-16-le"))

        self.assertEqual(text, source)
        self.assertEqual(encoding, "utf-16")


if __name__ == "__main__":
    unittest.main()
