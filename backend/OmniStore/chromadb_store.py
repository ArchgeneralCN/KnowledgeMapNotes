import json
from collections import defaultdict
import networkx as nx
import chromadb
import torch
from chromadb.utils import embedding_functions
import time
from embedding_tools.embedding_tools import BgeZhEmbeddingFunction
from transfer_package import graph_from_node_link_data, graph_to_node_link_data
from transformers import AutoModelForSequenceClassification, AutoTokenizer
from dotenv import load_dotenv
import os

load_dotenv()  #
device = os.getenv("DEVICE")

class StoreTool:
    def __init__(self, storage_path=os.getenv("CHROMADB_PATH"), embedding_function=None):
        # 初始化chromadb客户端
        self.client = chromadb.PersistentClient(path=storage_path)

        if embedding_function is None:
            # 使用默认的embedding函数（实际使用中可以替换）
            self.embedding_func = embedding_functions.DefaultEmbeddingFunction()
        else:

            if os.getenv("IS_USE_LOCAL") == "True":
                embedder = BgeZhEmbeddingFunction(
                    model_path=os.getenv("EMBEDDINGS_PATH"),
                    device=device
                )
            else:
                embedder = BgeZhEmbeddingFunction(model_path=os.getenv("EMBEDDINGS"),device=device)

            self.embedding_func = embedder


        model_name = os.getenv("RERANK_MODEL")
        rerank_model = AutoModelForSequenceClassification.from_pretrained(model_name)
        rerank_model.to(device)
        rerank_model.eval()
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.rerank_model = rerank_model


        # 获取图谱的三元组或创建集合
        self.collection = self.client.get_or_create_collection(
            name="kg_states",
            embedding_function=self.embedding_func
        )
        # 分块后的文本向量化结果，进行向量查询
        self.vector_collection = self.client.get_or_create_collection(
            name="bolt_vectors",
            embedding_function=self.embedding_func
        )
        # 考虑加入用户聊天记录,方便消息队列处理rag，而不是前端关闭，后端就不进行处理了，方便后端直接保存到数据库
        self.rag_history_collection = self.client.get_or_create_collection(
            name="history_vectors",
            embedding_function=self.embedding_func
        )

    def save_state(self, kg_manager):
        """保存文本块向量到chromadb，便于rag使用"""
        bolts = list(kg_manager.Bolts)
        persisted_count = getattr(kg_manager, "_persisted_bolt_count", 0)
        persisted_file = getattr(kg_manager, "_persisted_bolt_file", None)
        if persisted_file != kg_manager.file or not 0 <= persisted_count <= len(bolts):
            persisted_count = 0
        new_bolts = bolts[persisted_count:]
        bolt_count = len(bolts)
        metadatas = []
        for bid, text in new_bolts:
            entry_metadata = {
                "file": kg_manager.file,
                "operation_type": "add",
                "text_snippet": text[:50],
                "bolt_count": bolt_count,
                "original_file_type": kg_manager.original_file_type  # 存储原始文件名
            }
            metadatas.append(entry_metadata)

        if new_bolts:
            self.vector_collection.upsert(
                ids=[bid for bid, text in new_bolts],
                metadatas=metadatas,
                embeddings=self.embedding_func([text for bid, text in new_bolts]),
                documents=[text for bid, text in new_bolts]
            )

        """保存KgManager状态到chromadb"""
        # 序列化有向图
        graph_data = graph_to_node_link_data(kg_manager.current_G)

        # 准备需要存储的元数据
        metadata = {
            "file": kg_manager.file,
            "kg_triplet": json.dumps(kg_manager.kg_triplet),
            "bidirectional_mapping": json.dumps({
                "entity_to_label": dict(kg_manager.bidirectional_mapping["entity_to_label"]),
                "label_to_entities": dict(kg_manager.bidirectional_mapping["label_to_entities"])
            }),
            "current_G": json.dumps(graph_data),
            "Bolts": json.dumps(kg_manager.Bolts),
            "original_file_type": kg_manager.original_file_type  # 存储原始文件名
        }

        # 使用文件名作为ID，存入集合
        self.collection.upsert(
            ids=[kg_manager.file],
            metadatas=[metadata],
            documents=[kg_manager.file]  # 使用文件名作为文档内容
        )
        kg_manager._persisted_bolt_count = len(bolts)
        kg_manager._persisted_bolt_file = kg_manager.file

    def load_state(self, filename):
        """从chromadb加载指定文件名的状态"""
        results = self.collection.get(ids=[filename])
        if not results["metadatas"]:
            return None

        metadata = results["metadatas"][0]

        # 反序列化数据
        return {
            "file": metadata["file"],
            "kg_triplet": json.loads(metadata["kg_triplet"]),
            "bidirectional_mapping": {
                "entity_to_label": dict(json.loads(metadata["bidirectional_mapping"])["entity_to_label"]),
                "label_to_entities": defaultdict(list,
                                                 json.loads(metadata["bidirectional_mapping"])["label_to_entities"])
            },
            "current_G": graph_from_node_link_data(json.loads(metadata["current_G"])),
            "Bolts": json.loads(metadata["Bolts"]),
            "original_file_type": metadata.get("original_file_type", filename)  # 使用原始文件名
        }

    def delete_states(self, filenames: list):
        if not isinstance(filenames, list) or len(filenames) == 0:
            raise ValueError("filenames必须是非空列表")
        """批量删除多个文件状态"""
        self.vector_collection.delete(
            where={"file": {"$in": filenames}}
        )
        self.collection.delete(ids=filenames)
        return "delete_states success"

    def list_files(self):
        """获取所有存储的文件信息"""
        return self.collection.get()

    # rerank 重拍 向量检索结果
    def rerank_with_bge(self,query: str, documents: list, ids: list,metadata:list, top_k: int = 3):
        if not documents:
            return []

        # 准备query-doc对
        pairs = [[query, doc] for doc in documents]

        # 使用bge-reranker计算分数
        with torch.no_grad():
            inputs = self.tokenizer(pairs, padding=True, truncation=True, return_tensors='pt', max_length=512)
            inputs = inputs.to(device)
            scores = self.rerank_model(**inputs, return_dict=True).logits.view(-1).float().tolist()

        # 将分数与文档组合并排序
        reranked_results = list(zip(documents, ids, metadata,scores))
        reranked_results.sort(key=lambda x: x[2], reverse=True)

        return reranked_results[:top_k]

    # 查询向量
    def select_vectors(self, query: str, file: str, n_results: int = 3):

        """查询指定文件中最相似的文本块

        Args:
            query: 查询文本
            file: 要过滤的文件名
            n_results: 返回结果数量

        Returns:
            {
                "ids": 结果ID列表,
                "documents": 文本内容列表,
                "metadatas": 元数据列表,
                "distances": 相似度分数列表
            }
        """
        # 生成查询向量
        query_embedding = self.embedding_func([query])

        # 执行带元数据过滤的相似度查询
        results = self.vector_collection.query(
            query_embeddings=query_embedding,
            where={"file": file},  # 元数据过滤
            n_results=n_results,
            include=["documents", "metadatas", "distances"]
        )
        # 是否对检索文本进行重排
        rerank = True
        if rerank:
            retrieved_docs = results['documents'][0]
            retrieved_ids = results['ids'][0]
            retrieved_distances = results['distances'][0]
            rerank_list =  self.rerank_with_bge(query, retrieved_docs, retrieved_ids, retrieved_distances,n_results)
            ids = []
            documents = []
            distances = []
            metadatas = []
            # list(zip(documents, ids, metadata,scores))
            for i in rerank_list:
                ids.append(i[1])
                documents.append(i[0])
                metadatas.append(i[2])
                distances.append(i[3])
            return {
                "ids": ids,  # 第一层列表对应不同query
                "documents": documents,
                "metadatas": metadatas,
                "distances": distances
            }

        else:
            # 标准化返回结构（处理ChromaDB返回的嵌套列表）
            return {
                "ids": results["ids"][0],  # 第一层列表对应不同query
                "documents": results["documents"][0],
                "metadatas": results["metadatas"][0],
                "distances": results["distances"][0]
            }

    def save_rag_history(self, filename, messages):
        """保存RAG对话历史到数据库

        Args:
            filename: 文件ID，与kg_states集合中的ID保持一致
            messages: 消息列表，包含role和content字段的字典列表
        """
        if not messages:
            return

        # 准备元数据
        metadata = {
            "file": filename,
            "message_count": len(messages),
            "last_updated": str(int(time.time()))
        }

        # 将消息列表转换为JSON字符串
        message_json = json.dumps(messages, ensure_ascii=False)

        # 使用与文件名相同的ID，方便与知识图谱关联
        self.rag_history_collection.upsert(
            ids=[filename],
            metadatas=[metadata],
            documents=[message_json]
        )

        return "rag_history_saved"

    def get_rag_history(self, filename):
        """获取指定文件的RAG对话历史

        Args:
            filename: 文件ID

        Returns:
            消息列表或None（如果不存在）
        """
        results = self.rag_history_collection.get(ids=[filename])

        if not results["metadatas"]:
            return None

        try:
            # 解析消息JSON
            messages = json.loads(results["documents"][0])
            return messages
        except Exception as e:
            print(f"解析RAG历史记录失败: {e}")
            return None

    def delete_rag_history(self, filenames: list):
        """删除指定文件的RAG对话历史

        Args:
            filenames: 文件ID列表
        """
        if not isinstance(filenames, list) or len(filenames) == 0:
            raise ValueError("filenames必须是非空列表")

        self.rag_history_collection.delete(ids=filenames)
        return "delete_rag_history success"
