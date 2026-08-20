from typing import List, Optional
from sentence_transformers import SentenceTransformer
from chromadb import Documents, EmbeddingFunction, Embeddings
import numpy as np
import logging
import os

# 配置日志记录
logger = logging.getLogger(__name__)


class BgeZhEmbeddingFunction(EmbeddingFunction):
    """基于BAAI/bge-base-zh模型的ChromaDB嵌入函数

    特性：
    - 单例模式加载模型
    - 自动设备检测（CPU/GPU）
    - 输入文本规范化
    - 错误处理机制
    - 可配置的编码参数
    """

    _instance = None  # 单例实例

    def __new__(cls, model_path: str, **kwargs):
        """单例模式确保只加载一次模型"""
        if not cls._instance:
            cls._instance = super().__new__(cls)
            cls._instance._initialize_model(model_path, **kwargs)
        return cls._instance

    def _initialize_model(self, model_path: str, **kwargs):
        """初始化模型并配置编码参数"""
        try:
            # 模型初始化
            local_model = os.path.isdir(os.path.expanduser(model_path))
            if local_model:
                kwargs.setdefault("local_files_only", True)
            self.model = SentenceTransformer(os.path.expanduser(model_path), **kwargs)

            # 设备自动检测
            self.device = "cuda" if self.model.device.type == "cuda" else "cpu"

            # 默认编码参数
            self.encode_kwargs = {
                "normalize_embeddings": True,
                "batch_size": 32,
                "show_progress_bar": False
            }

            logger.info(f"成功加载模型到 {self.device} 设备")

        except Exception as e:
            logger.error(f"模型初始化失败: {str(e)}")
            raise RuntimeError("无法初始化嵌入模型") from e

    def _preprocess_texts(self, texts: Documents) -> List[str]:
        """文本预处理"""
        return [
            # 移除多余空格并截断长度
            " ".join(t.strip().split())[:512]  # BGE模型最大支持512 tokens
            for t in texts
        ]

    def __call__(self, texts: Documents, **encode_params) -> Embeddings:
        """生成文本嵌入

        Args:
            texts: 需要编码的文本列表
            encode_params: 可覆盖的编码参数，例如：
                - batch_size: 批处理大小
                - convert_to_numpy: 是否返回numpy数组

        Returns:
            形状为 (len(texts), embedding_dim) 的嵌入矩阵
        """
        # 输入验证
        if not texts or not all(isinstance(t, str) for t in texts):
            raise ValueError("输入必须是非空字符串列表")

        try:
            # 合并编码参数
            params = {**self.encode_kwargs, **encode_params}

            # 文本预处理
            processed_texts = self._preprocess_texts(texts)

            # 生成嵌入
            embeddings = self.model.encode(
                processed_texts,
                **params
            )

            # 转换为Python原生类型
            if isinstance(embeddings, np.ndarray):
                embeddings = embeddings.tolist()

            return embeddings

        except Exception as e:
            logger.error(f"编码过程中发生错误: {str(e)}")
            raise RuntimeError("嵌入生成失败") from e

