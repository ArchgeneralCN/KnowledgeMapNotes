"""Decode uploaded text files without assuming they are UTF-8."""

import codecs
from pathlib import Path
from typing import Tuple


def _text_quality(text: str) -> float:
    """Prefer readable CJK text and strongly reject controls/private-use glyphs."""
    if not text:
        return 0.0
    cjk = sum("\u3400" <= char <= "\u9fff" for char in text)
    private_use = sum("\ue000" <= char <= "\uf8ff" for char in text)
    controls = sum(ord(char) < 32 and char not in "\n\r\t" for char in text)
    readable = sum(char.isprintable() or char in "\n\r\t" for char in text)
    return (cjk * 3 + readable * 0.1 - private_use * 8 - controls * 12) / len(text)


def decode_text_bytes(data: bytes) -> Tuple[str, str]:
    """Return decoded text and its detected encoding for common document formats."""
    if not data:
        return "", "utf-8"

    bom_encodings = (
        (codecs.BOM_UTF8, "utf-8-sig"),
        (codecs.BOM_UTF32_LE, "utf-32"),
        (codecs.BOM_UTF32_BE, "utf-32"),
        (codecs.BOM_UTF16_LE, "utf-16"),
        (codecs.BOM_UTF16_BE, "utf-16"),
    )
    for bom, encoding in bom_encodings:
        if data.startswith(bom):
            return data.decode(encoding), encoding

    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass

    candidates = []
    candidate_encodings = ["gb18030", "big5"]
    if data.count(b"\x00") / len(data) > 0.1:
        candidate_encodings = ["utf-16-le", "utf-16-be", *candidate_encodings]

    for encoding in candidate_encodings:
        try:
            text = data.decode(encoding)
            candidates.append((_text_quality(text), text, encoding))
        except UnicodeDecodeError:
            continue

    if not candidates:
        raise ValueError("无法识别文本编码，请将文件转换为 UTF-8、GB18030 或 Big5 后重试")

    _, text, encoding = max(candidates, key=lambda item: item[0])
    return text, encoding


def read_text_file(path) -> Tuple[str, str]:
    """Read one path as text and report the selected source encoding."""
    return decode_text_bytes(Path(path).read_bytes())
