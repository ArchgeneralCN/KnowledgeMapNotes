import tiktoken
from typing import List, Dict, Tuple, Optional

class SimpleTextSplitter:
    def __init__(self, max_tokens: int = 512, min_tokens: int = 128,
                 overlap_tokens: int = 0):
        self.encoder = tiktoken.get_encoding("cl100k_base")
        self.max_tokens = max_tokens  # 最大令牌数限制
        self.min_tokens = min_tokens  # 最小令牌数阈值
        self.overlap_tokens = overlap_tokens  # 块间重叠令牌数
        self.SPLIT_PUNCTUATION = [".", "!", "?", "\n\n", ";", "。", "！", "？", "；"]  # 分割标点列表

    def split_text(self, text: str, doc_id: Optional[str] = None) -> List[Tuple[str, str]]:
        """
        基于令牌数量和标点边界分割文本

        参数:
            text: 待分割的文本
            doc_id: 可选文档标识符

        返回:
            元组列表 (块ID, 文本块)
        """
        chunks = []
        chunk_counter = 1  # 块计数器
        # Encode once. The old implementation encoded the entire remaining
        # document on every iteration, which made large files approach O(n^2).
        tokens = self.encoder.encode(text)
        start_token = 0
        total_tokens = len(tokens)

        while start_token < total_tokens:
            window_end = min(start_token + self.max_tokens, total_tokens)
            window_tokens = tokens[start_token:window_end]
            chunk_text = self.encoder.decode(window_tokens)

            if window_end < total_tokens:
                split_tokens = self._find_last_punctuation(chunk_text)
                if split_tokens >= self.min_tokens:
                    window_tokens = window_tokens[:split_tokens]
                    chunk_text = self.encoder.decode(window_tokens)

            consumed = len(window_tokens)
            if consumed <= 0:
                # Defensive guard for unusual tokenizer/decoder combinations.
                consumed = min(self.max_tokens, total_tokens - start_token)
                chunk_text = self.encoder.decode(tokens[start_token:start_token + consumed])

            bid = self._generate_block_id(chunk_text, chunk_counter, doc_id)
            chunks.append((bid, chunk_text.strip()))

            chunk_counter += 1
            next_start = start_token + consumed - self.overlap_tokens
            start_token = next_start if next_start > start_token else start_token + consumed

        return chunks

    def _find_last_punctuation(self, text: str) -> int:
        """
        查找文本中最后一个分割标点的位置
        返回对应的令牌数量位置
        """
        # 查找所有标点位置
        punct_positions = []
        for punct in self.SPLIT_PUNCTUATION:
            pos = text.rfind(punct)
            if pos != -1:
                punct_positions.append(pos + len(punct))  # 包含标点符号

        if not punct_positions:
            return len(self.encoder.encode(text))

        # 获取最后一个标点位置
        last_pos = max(punct_positions)
        tokens_up_to_pos = self.encoder.encode(text[:last_pos])
        return len(tokens_up_to_pos)

    def _generate_block_id(self, text: str, counter: int, doc_id: Optional[str]) -> str:
        """生成块ID"""
        prefix = f"{doc_id}_" if doc_id else ""
        return f"{prefix}block_{counter}_{hash(text[:50])}"
