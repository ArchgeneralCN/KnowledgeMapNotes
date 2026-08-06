import json
import os
import re
import itertools
import math
import time
import html
from collections import defaultdict
from pathlib import Path
from dotenv import load_dotenv
from pyvis.network import Network
import networkx as nx
import concurrent.futures
import logging
from urllib.parse import quote
from KnowledgeGraphManager.graph_interactions import build_graph_interaction_html
from LLM.Openai_Agent import AIResponseFormatError, AIResponseTruncatedError

load_dotenv(dotenv_path="./.env")
prompt_vision = os.getenv("PROMPTVISION")
logger = logging.getLogger("知识图谱关系提取")


def _positive_int_env(name, default):
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default

PROCESSING_PROMPT_FILES = {
    "entity_extraction": "entity_extraction2.txt",
    "relationship_extraction": "relationship_extraction2.txt",
    "knowledge_fusion": "knowledge_fusion.txt",
}


class ProcessingPaused(Exception):
    """Raised after a safe checkpoint when a user requests file processing pause."""


class KgManager:
    def __init__(self,agent,splitter,embedding_model,store):
        self.store = store
        # 大模型的对象
        self.Agent = agent
        # 用于分割文本
        self.splitter = splitter
        # 文本嵌入模型
        self.embeddings = embedding_model
        # 文件名
        self.file = ""
        # 原始文件类型
        self.original_file_type = ""
        # 当前 文本块bid-对应的关系的表
        self.kg_triplet = []
        # 当前 实体-实体标签映射表
        self.bidirectional_mapping = {
            "entity_to_label": {},
            "label_to_entities": defaultdict(list)
        }
        # 当前 有向图
        self.current_G = nx.DiGraph()
        # 当前 文本分块
        self.Bolts = []
        # StoreTool uses this to avoid re-embedding every completed block at
        # each checkpoint. It is reset when an incremental update deletes data.
        self._persisted_bolt_count = 0
        self._persisted_bolt_file = None
        self.noteType = "general"
        self.custom_prompts = {}
        # Smaller independent responses prevent one oversized JSON document from
        # invalidating an otherwise completed source block.
        self.relationship_text_batch_chars = _positive_int_env(
            "RELATION_TEXT_BATCH_CHARS", 2000
        )
        self.relationship_source_batch_size = _positive_int_env(
            "RELATION_SOURCE_BATCH_SIZE", 20
        )
        self.relationship_max_split_depth = _positive_int_env(
            "RELATION_MAX_SPLIT_DEPTH", 10
        )
        # Keep the conservative serial mode by default. Providers that allow
        # concurrent requests can raise this to 2-4 for much higher throughput.
        self.processing_workers = _positive_int_env("KG_WORKER_COUNT", 1)
        self.knowledge_fusion_enabled = os.getenv(
            "KG_FUSION_ENABLED", "True"
        ).strip().lower() in {"true", "1", "yes", "on", "enabled"}

    def configure_processing_prompts(self, note_type="general", custom_prompts=None):
        """Use per-file custom prompts while falling back to the general templates."""
        self.noteType = note_type
        self.custom_prompts = {
            stage: value.strip()
            for stage, value in (custom_prompts or {}).items()
            if stage in PROCESSING_PROMPT_FILES and isinstance(value, str) and value.strip()
        }

    def _processing_prompt(self, stage):
        if self.noteType == "custom" and stage in self.custom_prompts:
            return self.custom_prompts[stage]
        prompt_file = PROCESSING_PROMPT_FILES[stage]
        return Path(f"./prompt/{prompt_vision}/{prompt_file}").read_text(encoding="utf-8")


    def form_default(self,filename):
        default_data = self.store.load_state(filename)
        if default_data:
            self.file = default_data['file']
            self.kg_triplet = default_data['kg_triplet']
            self.bidirectional_mapping = default_data['bidirectional_mapping']
            self.current_G = default_data['current_G']
            self.Bolts = default_data['Bolts']
            self.original_file_type = default_data.get('original_file_type', '.txt')
        else:
            return None


    # 实体与实体类型的字典建立
    def _build_bidirectional_mapping(self, data):
        mapping = {
            "entity_to_label": {},
            "label_to_entities": defaultdict(list)
        }
        seen_entities = set()

        for entity, label in data:
            if entity not in seen_entities:
                mapping["entity_to_label"][entity] = label
                mapping["label_to_entities"][label].append(entity)
                seen_entities.add(entity)

        return mapping

    # 实体-标签表 利用实体获取标签
    def get_entity_label(self, knowledge_graph, entity):
        return knowledge_graph["entity_to_label"].get(entity, "未知标签")

    # 实体-标签表 利用标签获取实体
    def get_entities_by_label(self, knowledge_graph, label):
            return knowledge_graph["label_to_entities"].get(label, [])

    # 用于将文本分块处理
    def _Txt2Bolts(self,text):
        # begin  存入向量数据库
        documents = []
        embed = []
        ids = []
        self.Bolts = self.splitter.split_text(text)
        for bid, Bolt in self.Bolts:
            ids.append(bid)
            documents.append(Bolt)
            embed.append(self.embeddings.encode(Bolt))
        return self.Bolts


    def 实体提取(self,input_parameter):
        entity_label = []
        prompt = self._processing_prompt("entity_extraction")
        output = self.Agent.agent_safe_generate_response(
            prompt,
            input_parameter,
            expected_key="entities",
        )
        logger.debug("实体提取响应: %s", output)
        if not isinstance(output, dict):
            raise RuntimeError("实体提取请求失败或返回格式无效")
        entity_label = output.get("entities",[])
        # print(output)
        return entity_label

    @staticmethod
    def _unique_entity_names(entities):
        names = []
        seen = set()
        for entity in entities or []:
            name = entity[0] if isinstance(entity, (list, tuple)) and entity else entity
            if not isinstance(name, str):
                continue
            name = name.strip()
            if name and name not in seen:
                names.append(name)
                seen.add(name)
        return names

    @staticmethod
    def _split_long_relation_segment(segment, max_chars):
        """Split an exceptionally long sentence near punctuation when possible."""
        pieces = []
        remaining = segment
        while len(remaining) > max_chars:
            search_from = max_chars // 2
            cut = max(
                remaining.rfind(marker, search_from, max_chars + 1)
                for marker in ("，", ",", "、", "：", ":")
            )
            if cut < search_from:
                cut = max_chars
            else:
                cut += 1
            pieces.append(remaining[:cut])
            remaining = remaining[cut:]
        if remaining:
            pieces.append(remaining)
        return pieces

    def _split_relation_text(self, text, max_chars=None):
        """Create sentence-aligned chunks whose model outputs stay bounded."""
        text = (text or "").strip()
        if not text:
            return []
        max_chars = max_chars or self.relationship_text_batch_chars
        sentences = [
            part for part in re.split(r"(?<=[。！？!?；;\n])", text) if part
        ]
        chunks = []
        current = ""
        for sentence in sentences:
            parts = (
                self._split_long_relation_segment(sentence, max_chars)
                if len(sentence) > max_chars
                else [sentence]
            )
            for part in parts:
                if current and len(current) + len(part) > max_chars:
                    chunks.append(current.strip())
                    current = ""
                current += part
        if current.strip():
            chunks.append(current.strip())
        return chunks

    @staticmethod
    def _relation_batches(items, batch_size):
        return [
            items[index:index + batch_size]
            for index in range(0, len(items), batch_size)
        ]

    @staticmethod
    def _normalise_relations(relations, candidate_entities, source_entities):
        if not isinstance(relations, list):
            raise AIResponseFormatError("模型返回的 relations 必须是列表")

        candidates = set(candidate_entities)
        sources = set(source_entities)
        normalised = []
        for relation in relations:
            if not isinstance(relation, dict):
                logger.warning("跳过非对象关系: %r", relation)
                continue
            if not all(
                isinstance(relation.get(key), str) and relation[key].strip()
                for key in ("source", "target", "relation", "context")
            ):
                logger.warning("跳过字段不完整的关系: %r", relation)
                continue

            source = relation["source"].strip()
            target = relation["target"].strip()
            if source not in candidates or target not in candidates:
                logger.warning("跳过实体列表之外的关系: %s -> %s", source, target)
                continue
            if source not in sources:
                logger.warning("跳过当前 source 批次之外的关系: %s -> %s", source, target)
                continue

            try:
                weight = float(relation.get("weight", 0.5))
            except (TypeError, ValueError):
                weight = 0.5
            normalised.append({
                "source": source,
                "target": target,
                "relation": relation["relation"].strip(),
                "context": relation["context"].strip(),
                "weight": min(1.0, max(0.5, weight)),
            })
        return normalised

    def _request_relation_batch(
        self,
        prompt,
        text,
        candidate_entities,
        source_entities,
        depth=0,
    ):
        request_text = (
            "笔记内容：" + text
            + "\n实体列表：" + json.dumps(candidate_entities, ensure_ascii=False)
            + "\n本批允许作为 source 的实体列表："
            + json.dumps(source_entities, ensure_ascii=False)
            + "\n只输出 source 位于本批 source 列表中的关系；target 仍可使用完整实体列表。"
        )
        try:
            output = self.Agent.agent_safe_generate_response(
                prompt,
                request_text,
                repeat=1,
                expected_key="relations",
                raise_on_failure=True,
            )
            return self._normalise_relations(
                output.get("relations", []), candidate_entities, source_entities
            )
        except (AIResponseTruncatedError, AIResponseFormatError) as exc:
            if depth >= self.relationship_max_split_depth:
                raise RuntimeError("关系抽取多次拆分后仍返回不完整 JSON") from exc

            logger.warning(
                "关系批次响应过长或格式不完整，自动二分: depth=%d chars=%d "
                "candidates=%d sources=%d error=%s",
                depth,
                len(text),
                len(candidate_entities),
                len(source_entities),
                exc,
            )
            if len(source_entities) > 1:
                middle = len(source_entities) // 2
                return self._request_relation_batch(
                    prompt,
                    text,
                    candidate_entities,
                    source_entities[:middle],
                    depth + 1,
                ) + self._request_relation_batch(
                    prompt,
                    text,
                    candidate_entities,
                    source_entities[middle:],
                    depth + 1,
                )

            smaller_texts = self._split_relation_text(
                text, max(200, len(text) // 2)
            )
            if len(smaller_texts) <= 1:
                raise RuntimeError("最小关系批次仍返回不完整 JSON") from exc

            recovered = []
            for smaller_text in smaller_texts:
                smaller_candidates = [
                    name for name in candidate_entities if name in smaller_text
                ]
                smaller_sources = [
                    name for name in source_entities if name in smaller_text
                ]
                if len(smaller_candidates) < 2 or not smaller_sources:
                    continue
                recovered.extend(self._request_relation_batch(
                    prompt,
                    smaller_text,
                    smaller_candidates,
                    smaller_sources,
                    depth + 1,
                ))
            return recovered

    @staticmethod
    def _deduplicate_relations(relations):
        unique = {}
        for relation in relations:
            key = (
                relation["source"],
                relation["target"],
                relation["relation"],
                relation["context"],
            )
            previous = unique.get(key)
            if previous is None or relation["weight"] > previous["weight"]:
                unique[key] = relation
        return list(unique.values())

    def 关系提取(self, input_parameter, entity):
        prompt = self._processing_prompt("relationship_extraction")
        entities = self._unique_entity_names(entity)
        if len(entities) < 2:
            return []

        all_relations = []
        for text_batch in self._split_relation_text(input_parameter):
            candidates = [name for name in entities if name in text_batch]
            if len(candidates) < 2:
                continue
            for source_batch in self._relation_batches(
                candidates, self.relationship_source_batch_size
            ):
                all_relations.extend(self._request_relation_batch(
                    prompt,
                    text_batch,
                    candidates,
                    source_batch,
                ))

        return self._deduplicate_relations(all_relations)


    def 知识融合(self,relations):
        if not self.knowledge_fusion_enabled:
            logger.info("已通过 KG_FUSION_ENABLED 关闭关系融合")
            return relations
        # 创建一个字典来存储实体对及其关系
        entity_pairs = defaultdict(list)

        # 收集所有具有相同实体的关系
        for relation in relations:
            for relation_index, rel in enumerate(relation['relation']):
                source = rel['source']
                target = rel['target']
                # 使用排序后的实体对作为键，确保(source,target)和(target,source)被视为相同
                entity_pair = tuple(sorted([source, target]))
                entity_pairs[entity_pair].append({
                    'bid': relation['bid'],
                    'relation': rel
                })

        # 处理需要融合的关系
        merged_relations = []
        for entity_pair, rel_list in entity_pairs.items():
            if len(rel_list) > 1:  # 只处理有多个关系的实体对
                logger.debug("关系融合实体对: %s, 关系数: %d", entity_pair, len(rel_list))
                # 构建输入文本
                input_text = f"实体1：{entity_pair[0]}\n实体2：{entity_pair[1]}\n"
                input_text += "现有关系：\n"
                for rel in rel_list:
                    # 确保获取到的权重是浮点数
                    try:
                        weight = float(rel['relation'].get('weight', 0.5))
                    except (ValueError, TypeError):
                        weight = 0.5
                    input_text += f"- {rel['relation']['relation']}（上下文：{rel['relation']['context']}，权重：{weight}）\n"

                # 读取提示词模板
                prompt = self._processing_prompt("knowledge_fusion")
                prompt = prompt.replace("{input_text}", input_text)
                # print(input_text,"input_text")
                # 使用Agent进行关系融合
                merged_result = self.Agent.agent_safe_generate_response(
                    prompt,
                    input_text,
                    expected_key="relations",
                )
                logger.debug("关系融合结果: %s", merged_result)

                # 确保融合后的关系中包含权重
                if not isinstance(merged_result, dict):
                    raise RuntimeError("知识融合请求失败或返回格式无效")
                for rel in merged_result.get('relations', []):
                    if 'weight' not in rel:
                        rel['weight'] = 0.5
                    else:
                        # 确保weight是浮点数
                        try:
                            rel['weight'] = float(rel['weight'])
                        except (ValueError, TypeError):
                            rel['weight'] = 0.5

                # 将融合后的关系添加到结果中
                for rel in rel_list:
                    if isinstance(rel, dict) and isinstance(merged_result, dict):
                        merged_relations.append({
                            'bid': rel['bid'],
                            'relation': merged_result.get('relations', [])  # 使用完整的融合后关系列表
                        })
                    else:
                        continue
            else:
                # 对于只有一个关系的实体对，直接保留原关系
                merged_relations.append({
                    'bid': rel_list[0]['bid'],
                    'relation': [rel_list[0]['relation']]  # 保持列表格式一致
                })

        # 确保返回的关系格式正确
        formatted_relations = []
        for relation in merged_relations:
            formatted_relation = {
                'bid': relation['bid'],
                'relation': []
            }
            for rel in relation['relation']:
                if isinstance(rel, dict) and all(k in rel for k in ['source', 'target', 'relation', 'context']):
                    # 确保权重字段存在且为浮点数
                    if 'weight' not in rel:
                        rel['weight'] = 0.5
                    else:
                        try:
                            rel['weight'] = float(rel['weight'])
                        except (ValueError, TypeError):
                            logger.warning(
                                "无法将权重 '%s' 转换为浮点数，使用默认值0.5",
                                rel['weight'],
                            )
                            rel['weight'] = 0.5

                    formatted_relation['relation'].append(rel)
                    # print(f"添加关系: {rel['source']} -> {rel['target']}, 权重: {rel['weight']}")
                else:
                    logger.warning("跳过格式不正确的关系: %r", rel)
            if formatted_relation['relation']:  # 只添加有效的关系
                formatted_relations.append(formatted_relation)

        return formatted_relations

    # 输入处理好的分割文本，输出bid与实体-关系三元集合
    def 知识图谱的构建(
        self,
        text=None,
        progress_callback=None,
        checkpoint_callback=None,
        append=False,
        completed_offset=0,
        total_chunks=None,
        pause_callback=None,
    ):
        """构建图谱，并在每个文本块完成后暴露一致的检查点。

        ``append`` 用于中断恢复：保留已经落库的块和三元组，只把传入的
        剩余块交给模型处理。检查点回调看到的 ``Bolts`` 永远只包含已完成块。
        """
        if isinstance(text, str):
            blocks_to_process = self.splitter.split_text(text)
        elif isinstance(text, list):
            blocks_to_process = text
        elif text is None:
            blocks_to_process = list(self.Bolts)
        else:
            raise TypeError("text 必须是字符串、分块列表或 None")

        existing_bolts = list(self.Bolts) if append else []
        kg_triplet = list(self.kg_triplet) if append else []
        entity_labels = (
            list(self.bidirectional_mapping.get("entity_to_label", {}).items())
            if append
            else []
        )
        self.Bolts = existing_bolts
        self.kg_triplet = kg_triplet
        num_blocks = len(blocks_to_process)
        overall_total = total_chunks if total_chunks is not None else completed_offset + num_blocks
        if num_blocks == 0:
            self.bidirectional_mapping = self._build_bidirectional_mapping(entity_labels)
            self.kg_triplet = kg_triplet
            return kg_triplet

        def process_block(block):
            entity_label = self.实体提取(block[1])
            entity = [item[0] for item in entity_label]
            return entity_label, self.关系提取(block[1], entity)

        def commit_block(index, entity_label, relation, block_started_at):
            entity_labels.extend(entity_label)
            result = {"bid": blocks_to_process[index][0], "relation": relation}
            self.Bolts.append(blocks_to_process[index])
            self.kg_triplet.append(result)
            self.bidirectional_mapping = self._build_bidirectional_mapping(entity_labels)
            completed = completed_offset + index + 1
            if checkpoint_callback:
                checkpoint_callback(self, completed, overall_total)
            if progress_callback:
                progress_callback(completed, overall_total, time.monotonic() - block_started_at)

        if self.processing_workers == 1:
            executor_context = None
        else:
            executor_context = concurrent.futures.ThreadPoolExecutor(
                max_workers=self.processing_workers
            )

        try:
            # Concurrent batches preserve commit order and pause checkpoints.
            for batch_start in range(0, num_blocks, self.processing_workers):
                if pause_callback and pause_callback():
                    raise ProcessingPaused("用户已暂停文件处理")
                batch_end = min(batch_start + self.processing_workers, num_blocks)
                batch_started_at = time.monotonic()
                if executor_context is None:
                    results = [process_block(blocks_to_process[batch_start])]
                else:
                    futures = [
                        executor_context.submit(process_block, blocks_to_process[index])
                        for index in range(batch_start, batch_end)
                    ]
                    results = [future.result() for future in futures]

                for offset, (entity_label, relation) in enumerate(results):
                    index = batch_start + offset
                    commit_block(index, entity_label, relation, batch_started_at)
                    if pause_callback and pause_callback():
                        raise ProcessingPaused("用户已暂停文件处理")
        finally:
            if executor_context is not None:
                executor_context.shutdown(wait=True)
        self.bidirectional_mapping = self._build_bidirectional_mapping(entity_labels)
        self.kg_triplet = kg_triplet
        # print(kg_triplet)
        return kg_triplet



    def 三元组转有向图nx(self,relations):
        knowledge_graph = self.bidirectional_mapping
        self.current_G = nx.DiGraph()
        for relation in relations:
            for relation_index, rel in enumerate(relation['relation']):
                source = rel['source']
                target = rel['target']
                context = rel['context']
                relation_text = rel['relation']
                # 获取权重，确保是浮点数
                try:
                    weight = float(rel.get('weight', 0.5))
                except (ValueError, TypeError):
                    logger.warning(
                        "无法转换权重值 '%s' 为浮点数，使用默认值0.5",
                        rel.get('weight'),
                    )
                    weight = 0.5

                # print(f"添加边 {source} -> {target} 权重: {weight}")

                # 添加节点
                self.current_G.add_node(source,
                                        title=self.get_entity_label(knowledge_graph, source),
                                        group=self.get_entity_label(knowledge_graph, source))
                self.current_G.add_node(target,
                                        title=self.get_entity_label(knowledge_graph, target),
                                        group=self.get_entity_label(knowledge_graph, target))

                # 添加边（初始状态）
                self.current_G.add_edge(source, target,
                                        title=context,
                                        label=relation_text,
                                        edit_id=rel.get('edit_id') or self._graph_edge_id(
                                            relation.get('bid'), relation_index, rel
                                        ),
                                        weight=weight,  # 添加权重
                                        font={"size": 0},  # 初始标签隐藏
                                        color='#97c2fc',
                                        width=1 + weight * 3,  # 根据权重调整边的粗细
                                        hoverWidth=3 + weight * 2,
                                        chosen={  # 点击选中样式
                                            "edge": {
                                                "color": "#00FF00",
                                                "width": 4
                                            }
                                        })
        return self.current_G

    @staticmethod
    def _graph_edge_id(bid, index, relation):
        """Use the same stable edge key as the graph editor/history API."""
        import hashlib

        payload = json.dumps({
            "bid": bid,
            "index": index,
            "source": relation.get("source"),
            "target": relation.get("target"),
            "relation": relation.get("relation"),
            "context": relation.get("context"),
        }, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return "edge-" + hashlib.sha1(payload).hexdigest()[:20]

    # 增量更新找到要处理的块
    def _replace_blocks_and_find_changes(self, original_blocks, new_text, split_text_fun):
        def normalize_text(text):
            """去除首尾空格、合并多余空格、换行转换为空格"""
            return re.sub(r'\s+', ' ', text.strip())

        """用原文块替换未变部分，找出新增和删除的块"""
        normalized_new_text = normalize_text(new_text)  # 归一化新文本
        replaced_text = normalized_new_text  # 复制新文本
        matched_blocks = set()  # 记录匹配的块文本

        # **第一步**：替换未变的部分
        for bid, text in original_blocks:
            norm_text = normalize_text(text)
            if norm_text in replaced_text:
                replaced_text = replaced_text.replace(norm_text, bid, 1)
                matched_blocks.add(norm_text)

        # **第二步**：计算删除的块（原文本中未出现在新文本中的部分）
        deleted_blocks = [(bid, text) for bid, text in original_blocks if
                          normalize_text(text) not in normalized_new_text]

        # **第三步**：用 `block_id` 作为分隔符，分割出变动部分
        split_pattern = '|'.join(re.escape(bid) for bid, _ in original_blocks)
        unmatched_parts = re.split(split_pattern, replaced_text)  # 只保留变动部分
        unmatched_parts = [normalize_text(part) for part in unmatched_parts if part.strip()]  # 清理空格

        # **第四步**：用你的 `split_text()` 切割新增内容
        added_texts = []
        for part in unmatched_parts:
            added_texts.extend([t for t in split_text_fun(part) if t])

        # **第五步**：分配新增块 ID
        added_blocks = [text for i, text in enumerate(added_texts)]

        return replaced_text, deleted_blocks, added_blocks

    def 增量更新(
        self,
        new_text: str,
        progress_callback=None,
        checkpoint_callback=None,
        pause_callback=None,
    ):
        replaced_new_text, deleted_blocks, added_blocks = self._replace_blocks_and_find_changes(
            self.Bolts,
            new_text,
            self.splitter.split_text)

        bids_to_remove = []

        # 被删除的块
        for bid, text in deleted_blocks:
            bids_to_remove.append(bid)

        filtered_data = [item for item in self.kg_triplet if item['bid'] not in bids_to_remove]

        # 只有在有需要删除的ID时才执行删除操作
        if bids_to_remove:
            self.store.vector_collection.delete(
                where={"file": self.file},
                ids=bids_to_remove
            )
            self._persisted_bolt_count = 0
            self._persisted_bolt_file = self.file

        add_data = list(added_blocks)
        logger.info(
            "增量更新: 新增块=%d, 删除块=%d",
            len(add_data),
            len(bids_to_remove),
        )
        retained_blocks = [item for item in self.Bolts if item[0] not in bids_to_remove]
        self.Bolts = retained_blocks
        self.kg_triplet = filtered_data
        new_kg_triplet = self.知识图谱的构建(
            add_data,
            progress_callback=progress_callback,
            checkpoint_callback=checkpoint_callback,
            append=True,
            completed_offset=len(retained_blocks),
            total_chunks=len(retained_blocks) + len(add_data),
            pause_callback=pause_callback,
        )

        return new_kg_triplet

    def 绘制知识图谱(
        self,
        name,
        聚类算法="louvain",
        物理引擎="forceAtlas2Based",
        输出目录="results",
        页面路由前缀=None,
        社区最小规模=None,
    ):
        """
        优化版知识图谱可视化（支持社区分页渲染）

        参数:
            name: 图谱名称（主页面将保存为 <输出目录>/<name>/<name>.html）
            聚类算法: "louvain"(社区发现) | "kmeans" | None
            物理引擎: "forceAtlas2Based"(推荐) | "barnesHut" | "force"
            输出目录: 图谱结果根目录；每个图谱在其中使用独立的同名目录
            页面路由前缀: 可选的浏览器访问路由前缀。未指定时使用同目录相对链接，
                生成的 HTML 可直接从结果目录打开。
            社区最小规模: 生成社区详情页的最小节点数；未指定时读取
                GRAPH_COMMUNITY_MIN_SIZE，默认为 20。设置为 1 可查看所有社区。
        """
        self.file = name

        图谱目录 = Path(输出目录) / name
        图谱目录.mkdir(parents=True, exist_ok=True)
        主页面名称 = f"{name}.html"
        主页面路径 = 图谱目录 / 主页面名称

        # 1. 社区发现
        社区分配 = {}
        if 聚类算法 == "louvain":
            try:
                import community as community_louvain
                社区分配 = community_louvain.best_partition(self.current_G.to_undirected())
            except ImportError:
                社区分配 = {n: 0 for n in self.current_G.nodes()}
                print("提示: pip install python-louvain 可启用社区发现聚类")
        else:
            社区分配 = {n: 0 for n in self.current_G.nodes()}

        # 2. 分析社区规模，决定是否分页
        社区节点计数 = {}
        for n, cid in 社区分配.items():
            社区节点计数[cid] = 社区节点计数.get(cid, 0) + 1

        最大社区大小 = max(社区节点计数.values()) if 社区节点计数 else 0
        社区数量 = len(社区节点计数)
        if 社区最小规模 is None:
            MIN_SIZE = _positive_int_env("GRAPH_COMMUNITY_MIN_SIZE", 20)
        else:
            MIN_SIZE = max(1, int(社区最小规模))

        # 为原图节点建立稳定的出处文本块索引。社区子图复制节点时会
        # 一并携带该字段，右键查看节点即可定位它在本社区中的原文出处。
        节点出处文本块 = defaultdict(list)
        for block in self.kg_triplet or []:
            if not isinstance(block, dict):
                continue
            bid = str(block.get("bid", ""))
            if not bid:
                continue
            for relation in block.get("relation") or []:
                if not isinstance(relation, dict):
                    continue
                for endpoint in (relation.get("source"), relation.get("target")):
                    if endpoint and bid not in 节点出处文本块[endpoint]:
                        节点出处文本块[endpoint].append(bid)
        for node in self.current_G.nodes:
            self.current_G.nodes[node]["source_blocks"] = list(
                节点出处文本块.get(node, self.current_G.nodes[node].get("source_blocks", []))
            )

        # 分页后首页只包含社区节点，不能用首页节点数判断是否为大图。
        # 原图超过 50 个节点时，首页和所有社区子页面都使用静态布局。
        原图强制静态布局 = len(self.current_G) > 50

        启用分页 = (聚类算法 == "louvain") and (社区数量 > 1) and (最大社区大小 >= MIN_SIZE)

        if not 启用分页:
            # 原逻辑：生成单一全图页面
            self._渲染图(
                self.current_G,
                主页面路径,
                社区分配,
                物理引擎,
                导航HTML="",
                强制静态布局=原图强制静态布局,
            )
            print(f"✅ 知识图谱已生成: {主页面路径}")
            print(f"   节点数: {len(self.current_G.nodes())}, 边数: {len(self.current_G.edges())}")
            return self.current_G

        # ---------- 分页模式 ----------
        大社区 = [cid for cid, size in 社区节点计数.items() if size >= MIN_SIZE]
        # 确定文件名
        子页面名称 = {cid: f"{name}_community_{cid}.html" for cid in 大社区}
        子页面路径 = {cid: 图谱目录 / filename for cid, filename in 子页面名称.items()}

        def 页面链接(page_name):
            if 页面路由前缀:
                return (
                    f"{页面路由前缀.rstrip('/')}/{quote(str(name), safe='')}/"
                    f"{quote(page_name, safe='')}"
                )
            return page_name

        # ---- 3. 构建概览图（社区间关系） ----
        # 计算每个社区的代表节点
        社区节点列表 = {}
        for n, cid in 社区分配.items():
            社区节点列表.setdefault(cid, []).append(n)

        节点度数全图 = dict(self.current_G.degree())
        社区代表节点 = {}
        for cid, nodes in 社区节点列表.items():
            if nodes:
                代表 = max(nodes, key=lambda n: 节点度数全图.get(n, 0))
                社区代表节点[cid] = 代表
            else:
                社区代表节点[cid] = f"社区{cid}"

        def 节点实体类型(node):
            return str(
                self.current_G.nodes[node].get("entity_type")
                or self.current_G.nodes[node].get("group")
                or self.current_G.nodes[node].get("title")
                or "未分类"
            )

        # 社区首页使用主节点的原始实体类型，避免概览图所有节点都显示为“社区”。
        社区主节点类型 = {
            cid: 节点实体类型(代表)
            for cid, 代表 in 社区代表节点.items()
            if 代表 in self.current_G
        }
        # 快速查找原图中的边（无向处理，保留权重最大的一条）
        edge_lookup = {}
        for u, v, data in self.current_G.edges(data=True):
            key = (u, v) if u < v else (v, u)
            if key not in edge_lookup or data.get('weight', 0.5) > edge_lookup[key].get('weight', 0.5):
                edge_lookup[key] = data

        ov_G = nx.Graph()
        for cid, size in 社区节点计数.items():
            代表节点名 = 社区代表节点.get(cid, str(cid))
            ov_G.add_node(cid,
                          label=代表节点名,
                          size=size,
                          group=社区主节点类型.get(cid, "未分类"),
                          entity_type=社区主节点类型.get(cid, "未分类"),
                          source_blocks=节点出处文本块.get(代表节点名, []),
                          representative_node=代表节点名,
                          title=f"社区 {cid}\n节点数: {size}\n代表节点: {代表节点名}\n"
                                f"主节点类型: {社区主节点类型.get(cid, '未分类')}")

        # 构建跨社区边（使用代表节点间的真实关系）
        for cu, cv in itertools.combinations(社区节点计数.keys(), 2):
            rep_u = 社区代表节点[cu]
            rep_v = 社区代表节点[cv]
            # 优先取代表节点之间的边
            lookup_key = (rep_u, rep_v) if rep_u < rep_v else (rep_v, rep_u)
            edge_data = edge_lookup.get(lookup_key)
            if edge_data is None:
                # 若代表节点间没有直接边，则取两个社区间任意一条权重最大的边
                best_edge = None
                best_weight = -1
                for u in 社区节点列表.get(cu, []):
                    for v in 社区节点列表.get(cv, []):
                        key = (u, v) if u < v else (v, u)
                        data = edge_lookup.get(key)
                        if data and data.get('weight', 0.5) > best_weight:
                            best_edge = data
                            best_weight = data.get('weight', 0.5)
                edge_data = best_edge

            if edge_data:
                ov_G.add_edge(cu, cv,
                              weight=edge_data.get('weight', 0.5),
                              title=edge_data.get('title', ''),
                              label=edge_data.get('label', ''),
                              arrows='none')  # 无向概览图不显示箭头

        # ---- 4. 生成主页面（概览图） ----
        社区类型选项 = sorted({
            社区主节点类型.get(cid, "未分类")
            for cid in 大社区
        })
        社区类型选项HTML = "".join(
            f'<option value="{html.escape(entity_type, quote=True)}">'
            f'{html.escape(entity_type)}</option>'
            for entity_type in 社区类型选项
        )
        导航链接列表 = "".join(
            f'<div class="community-list-item" '
            f'data-name="{html.escape(str(社区代表节点.get(cid, f"社区{cid}")), quote=True)}" '
            f'data-types="{html.escape(社区主节点类型.get(cid, "未分类"), quote=True)}">'
            f'<a class="community-item-link" href="{html.escape(页面链接(子页面名称[cid]), quote=True)}">'
            f'<span class="community-item-name">{html.escape(str(社区代表节点.get(cid, f"社区{cid}")))}</span>'
            f'<span class="community-item-meta">{社区节点计数.get(cid, 0)} 个节点 · '
            f'主节点类型：{html.escape(社区主节点类型.get(cid, "未分类"))}</span></a>'
            f'<button type="button" class="community-source-link" '
            f'data-node-id="{html.escape(str(社区代表节点.get(cid, f"社区{cid}")), quote=True)}" '
            f'data-source-blocks="{html.escape(json.dumps(节点出处文本块.get(社区代表节点.get(cid), []), ensure_ascii=False), quote=True)}">'
            f'查看原文文本块</button></div>'
            for cid in 大社区
        )

        # 主页面底部导航HTML
        导航HTML_主 = f"""
        <div class="community-directory graph-floating-panel" id="communityDirectory">
            <div class="graph-panel-header">
                <span>📂 社区详情</span>
                <button class="graph-panel-collapse" type="button" aria-label="收起社区详情">−</button>
            </div>
            <div class="graph-panel-body">
                <input id="communitySearchInput" class="graph-text-input" type="search" placeholder="搜索社区代表实体...">
                <select id="communityTypeFilter" class="graph-select">
                    <option value="">全部实体类型</option>{社区类型选项HTML}
                </select>
                <div class="community-list" id="communityList">{导航链接列表}</div>
                <div class="graph-empty-state" id="communityEmptyState" hidden>没有匹配的社区</div>
            </div>
        </div>
        """
        self._渲染图(
            ov_G,
            主页面路径,
            社区分配={},
            物理引擎=物理引擎,
            导航HTML=导航HTML_主,
            强制静态布局=原图强制静态布局,
        )

        # ---- 5. 为每个大社区生成子页面 ----
        for cid in 大社区:
            子节点 = [n for n, c in 社区分配.items() if c == cid]
            子图 = self.current_G.subgraph(子节点).copy()

            代表名 = 社区代表节点.get(cid, f"社区{cid}")
            导航HTML_子 = f"""
            <div class="community-back-bar">
                <a href="{html.escape(页面链接(主页面名称), quote=True)}">← 返回社区列表</a>
                <span>{html.escape(str(代表名))}（{len(子节点)} 个节点）</span>
            </div>
            """
            self._渲染图(
                子图,
                子页面路径[cid],
                社区分配={},
                物理引擎=物理引擎,
                导航HTML=导航HTML_子,
                强制静态布局=原图强制静态布局,
            )

        print(f"✅ 知识图谱已生成（社区分页）:")
        print(f"   主页面（跨社区关系）: {主页面路径}  ({社区数量} 个社区, {ov_G.number_of_edges()} 条跨社区边)")
        for cid in 大社区:
            print(f"   社区 {cid} 详情页: {子页面路径[cid]}  ({社区节点计数[cid]} 个节点)")
        return self.current_G

    @staticmethod
    def _计算静态力导向布局(G):
        """在服务端一次性计算原始 ForceAtlas2 风格布局。

        浏览器不再运行物理引擎，避免打开页面后节点持续弹动；坐标仍由
        力导向算法生成，因此保留原先自然分布的视觉效果，而不是规则网格
        或按距离排列的同心环。没有任何连接的节点不参加力导向计算，
        关系节点会经过碰撞消解，最后再把孤立节点统一放到关系图外围。
        """
        if not G:
            return {}

        无向图 = G.to_undirected()
        有连接节点 = [node for node, degree in 无向图.degree() if degree > 0]
        孤立节点 = sorted(
            (node for node, degree in 无向图.degree() if degree == 0),
            key=lambda node: str(node),
        )
        positions = {}

        if 有连接节点:
            布局图 = 无向图.subgraph(有连接节点).copy()
            布局节点数 = len(布局图)
            最大迭代次数 = 80 if 布局节点数 <= 500 else 50 if 布局节点数 <= 2000 else 30
            forceatlas2 = getattr(nx, "forceatlas2_layout", None)
            try:
                if forceatlas2 is not None:
                    raw_positions = forceatlas2(
                        布局图,
                        max_iter=最大迭代次数,
                        scaling_ratio=2.0,
                        gravity=1.0,
                        weight="weight",
                        seed=42,
                    )
                else:
                    raw_positions = nx.spring_layout(
                        布局图,
                        seed=42,
                        iterations=最大迭代次数,
                        weight="weight",
                    )
            except Exception as error:
                logger.warning("静态力导向布局计算失败，改用弹簧布局: %s", error)
                raw_positions = nx.spring_layout(
                    布局图,
                    seed=42,
                    iterations=max(30, 最大迭代次数),
                    weight="weight",
                )

            # ForceAtlas2 的输出通常是归一化坐标，直接写入 vis-network
            # 会让几十像素大小的节点挤在一起。先放大到适合画布的尺度。
            center_x = sum(float(position[0]) for position in raw_positions.values()) / len(raw_positions)
            center_y = sum(float(position[1]) for position in raw_positions.values()) / len(raw_positions)
            centered = {
                node: (float(position[0]) - center_x, float(position[1]) - center_y)
                for node, position in raw_positions.items()
            }
            max_extent = max(
                (max(abs(x), abs(y)) for x, y in centered.values()),
                default=1.0,
            ) or 1.0
            desired_extent = max(280.0, math.sqrt(布局节点数) * 90.0)
            scale = max(1.0, desired_extent / max_extent)
            positions = {
                node: (x * scale, y * scale)
                for node, (x, y) in centered.items()
            }

            # ForceAtlas2 只负责给出整体结构；用空间网格做轻量碰撞消解，
            # 避免节点标签和关系端点重叠，同时避免 O(n^2) 的全量两两比较。
            degrees = dict(布局图.degree())
            max_degree = max(degrees.values(), default=1) or 1
            node_radii = {
                node: 28.0 + 22.0 * degrees.get(node, 0) / max_degree
                for node in positions
            }
            positions = KgManager._消除静态节点重叠(positions, node_radii)
            connected_radius = max(
                math.hypot(x, y) for x, y in positions.values()
            )
        else:
            connected_radius = 0.0

        if 孤立节点:
            # 分批放在外围多个环上，避免大量孤立节点挤在同一圈。
            ring_spacing = 180.0
            radius = max(connected_radius + 260.0, 360.0)
            remaining = list(孤立节点)
            ring_index = 0
            while remaining:
                ring_radius = radius + ring_index * ring_spacing
                capacity = max(8, int(2 * math.pi * ring_radius / ring_spacing))
                ring_nodes = remaining[:capacity]
                del remaining[:capacity]
                for index, node in enumerate(ring_nodes):
                    angle = (2 * math.pi * index / len(ring_nodes)) - math.pi / 2
                    positions[node] = (
                        ring_radius * math.cos(angle),
                        ring_radius * math.sin(angle),
                    )
                ring_index += 1

        return positions

    @staticmethod
    def _消除静态节点重叠(positions, node_radii, gap=24.0):
        """Resolve overlaps in a static layout using a spatial hash grid."""
        if len(positions) < 2:
            return positions

        nodes = list(positions)
        max_radius = max((float(node_radii.get(node, 30.0)) for node in nodes), default=30.0)
        cell_size = max(2.0 * max_radius + gap, 1.0)
        max_iterations = 140 if len(nodes) <= 500 else 50 if len(nodes) <= 2000 else 25

        for _ in range(max_iterations):
            buckets = defaultdict(list)
            for index, node in enumerate(nodes):
                x, y = positions[node]
                cell = (math.floor(x / cell_size), math.floor(y / cell_size))
                buckets[cell].append(index)

            moved = False
            for index, node in enumerate(nodes):
                x, y = positions[node]
                cell_x = math.floor(x / cell_size)
                cell_y = math.floor(y / cell_size)
                radius = float(node_radii.get(node, 30.0))
                for neighbour_x in range(cell_x - 1, cell_x + 2):
                    for neighbour_y in range(cell_y - 1, cell_y + 2):
                        for other_index in buckets.get((neighbour_x, neighbour_y), ()):
                            if other_index <= index:
                                continue
                            other = nodes[other_index]
                            other_x, other_y = positions[other]
                            dx = other_x - x
                            dy = other_y - y
                            distance = math.hypot(dx, dy)
                            required = radius + float(node_radii.get(other, 30.0)) + gap
                            if distance >= required:
                                continue
                            if distance < 1e-9:
                                angle = (index + 1) * 2.399963229728653
                                dx, dy = math.cos(angle), math.sin(angle)
                                distance = 0.0
                            else:
                                dx, dy = dx / distance, dy / distance
                            push = (required - distance) * 0.5
                            positions[node] = (x - dx * push, y - dy * push)
                            positions[other] = (other_x + dx * push, other_y + dy * push)
                            x, y = positions[node]
                            moved = True
            if not moved:
                break

        # The iterative pass is intentionally local and fast. For the graph
        # sizes rendered in one page, finish with one uniform expansion so the
        # requested clearance is mathematically satisfied for every pair.
        if len(nodes) <= 2000:
            center_x = sum(positions[node][0] for node in nodes) / len(nodes)
            center_y = sum(positions[node][1] for node in nodes) / len(nodes)
            expansion = 1.0
            for index, node in enumerate(nodes):
                x, y = positions[node]
                radius = float(node_radii.get(node, 30.0))
                for other in nodes[index + 1:]:
                    other_x, other_y = positions[other]
                    distance = math.hypot(other_x - x, other_y - y)
                    required = radius + float(node_radii.get(other, 30.0)) + gap
                    if distance > 1e-9:
                        expansion = max(expansion, required / distance)
            if expansion > 1.0:
                positions = {
                    node: (
                        center_x + (x - center_x) * expansion,
                        center_y + (y - center_y) * expansion,
                    )
                    for node, (x, y) in positions.items()
                }
        return positions

    def _渲染图(self, G, 文件名, 社区分配, 物理引擎, 导航HTML="", 强制静态布局=False):
        """
        内部渲染函数：将图 G 渲染为单个 HTML 文件
        社区分配: 节点 -> 社区ID 的字典，空字典则全部归为0组
        """
        if not 社区分配:
            社区分配 = {n: 0 for n in G.nodes()}

        # 节点重要性计算
        节点度数 = dict(G.degree())
        最大度数 = max(节点度数.values(), default=0) or 1
        max_pagerank_nodes = _positive_int_env("GRAPH_PAGERANK_MAX_NODES", 5000)
        if len(G) > max_pagerank_nodes or G.number_of_edges() > max_pagerank_nodes * 10:
            # PageRank is visual decoration; skip its iterative solve for very
            # large graphs so rendering remains bounded by graph serialization.
            pagerank = {n: 0.0 for n in G.nodes()}
        else:
            try:
                pagerank = nx.pagerank(G)
            except Exception:
                pagerank = {n: 1.0 for n in G.nodes()}

        # 创建PyVis网络
        is_directed = G.is_directed()  # 根据图类型自适应
        net = Network(
            notebook=True,
            height="800px",
            width="100%",
            bgcolor="#ffffff",
            font_color="#1a1a1a",
            directed=is_directed,
            # Keep the stored checkpoint compact. The result endpoint replaces
            # this reference with the installed local asset before delivery.
            cdn_resources='remote'
        )

        # 物理引擎配置
        # 大图或包含孤立节点的图不启动物理模拟：ForceAtlas2 在节点数较多时会持续占用主线程，
        # 造成页面打开后长时间弹动、拖拽卡顿。节点会在下方获得一次性计算的
        # 静态力导向位置，但不设置 fixed，因此用户仍可以自由拖动节点。
        # 初始位置，但不设置 fixed，因此用户仍可以自由拖动节点。
        节点总数 = len(G.nodes())
        包含孤立节点 = any(degree == 0 for degree in 节点度数.values())
        大图静态布局 = 强制静态布局 or 节点总数 > 50 or 包含孤立节点
        if 大图静态布局:
            physics = {
                "enabled": False,
                "stabilization": {"enabled": False}
            }
        else:
            # 50 个及以下且没有孤立节点：保留原有物理布局作为备用
            physics = {
                "forceAtlas2Based": {
                    "gravitationalConstant": -80,
                    "centralGravity": 0.005,
                    "springLength": 200,
                    "springConstant": 0.08,
                    "damping": 0.4,
                    "avoidOverlap": 1.0
                },
                "solver": "forceAtlas2Based",
                "stabilization": {
                    "enabled": True,
                    "iterations": 120,
                    "updateInterval": 25,
                    "fit": True,
                }
            }

        options = {
            "nodes": {
                "shape": "dot",
                "scaling": {"min": 10, "max": 40, "label": {"enabled": True, "min": 14, "max": 24}},
                "font": {"size": 14, "face": "Microsoft YaHei, SimHei, sans-serif", "color": "#1a1a1a"},
                "borderWidth": 2, "borderWidthSelected": 4,
                "shadow": {"enabled": not 大图静态布局, "size": 10, "x": 3, "y": 3}
            },
            "edges": {
                "width": 1,
                "color": {"color": "#a0a0a0", "highlight": "#ff6b35", "hover": "#ff6b35", "opacity": 0.6},
                "smooth": False if 大图静态布局 else {"type": "continuous", "roundness": 0.5},
                "selectionWidth": 3, "hoverWidth": 2,
                "arrows": {
                    "to": {"enabled": is_directed, "scaleFactor": 0.5}
                },
                "font": {"size": 0, "face": "Microsoft YaHei", "color": "#666666",
                         "align": "middle", "background": "rgba(255,255,255,0.9)"}
            },
            "interaction": {
                "hover": True, "tooltipDelay": 100, "hideEdgesOnDrag": True,
                "hideNodesOnDrag": False, "dragNodes": True, "dragView": True,
                "zoomView": True, "multiselect": True, "navigationButtons": False,
                "keyboard": True
            },
            "layout": {"improvedLayout": not 大图静态布局}
        }
        options.update({"physics": physics})
        net.set_options(json.dumps(options, indent=2))

        # 添加节点。关闭物理引擎后必须提供分散的初始位置，否则部分旧版
        # vis-network 会把尚未定位的节点堆在画布中心。这里不设置 fixed，
        # 所以静态布局只是初始位置，用户仍然可以拖动。
        if 大图静态布局:
            静态节点坐标 = self._计算静态力导向布局(G)
        else:
            静态节点坐标 = {}

        for node, attr in G.nodes(data=True):
            degree = 节点度数.get(node, 0)
            pr = pagerank.get(node, 0)
            size = 15 + (degree / 最大度数) * 25 + pr * 20
            is_hub = degree > 最大度数 * 0.3 if 最大度数 > 0 else False
            group = attr.get('group', 社区分配.get(node, 0))
            entity_type = str(
                attr.get('entity_type')
                or attr.get('group')
                or attr.get('title')
                or '未分类'
            )

            # 优先使用节点属性中的 label
            node_label = str(attr.get('label', node))

            node_options = {
                "title": attr.get('title', f'节点: {node}\n连接数: {degree}\nPageRank: {pr:.3f}'),
                "value": size,
                "group": group,
                "entityType": entity_type,
                "source_blocks": list(attr.get('source_blocks') or []),
                "color": {
                    "background": "#ff6b35" if is_hub else "#2196F3",
                    "border": "#e55a2b" if is_hub else "#1976D2",
                    "highlight": {"background": "#ff8a5c" if is_hub else "#64B5F6",
                                  "border": "#ff6b35" if is_hub else "#2196F3"},
                    "hover": {"background": "#ff8a5c" if is_hub else "#64B5F6",
                              "border": "#ff6b35" if is_hub else "#2196F3"}
                }
            }
            if 大图静态布局 and node in 静态节点坐标:
                x, y = 静态节点坐标[node]
                node_options.update({
                    "x": x,
                    "y": y,
                })
            if is_hub:
                node_options["font"] = {
                    "size": 16, "color": "#1a1a1a",
                    "background": "rgba(255,255,255,0.9)",
                    "strokeWidth": 1, "strokeColor": "#ffffff"
                }

            # 使用提取出的标签
            net.add_node(node, label=node_label, **node_options)

        # 添加边
        for source, target, attr in G.edges(data=True):
            weight = attr.get('weight', 0.5)
            width = 1 + weight * 3
            source_degree = 节点度数.get(source, 0)
            target_degree = 节点度数.get(target, 0)
            is_hub_edge = source_degree > 最大度数 * 0.3 or target_degree > 最大度数 * 0.3

            edge_options = {
                "title": attr.get('title', ''),
                "label": attr.get('label', ''),
                "weight": weight,
                "width": width,
                "font": {"size": 0},
                "color": {
                    "color": "rgba(160,160,160,0.3)" if is_hub_edge else "#a0a0a0",
                    "highlight": "#ff6b35", "hover": "#ff6b35",
                    "opacity": 0.3 if is_hub_edge else 0.6
                },
                "hoverWidth": 1.5 + weight * 2,
                "selectionWidth": 2 + weight * 2
            }
            if is_hub_edge and not 大图静态布局:
                edge_options["smooth"] = {"type": "curvedCW", "roundness": 0.3}
            if attr.get('edit_id'):
                edge_options['id'] = attr['edit_id']
            net.add_edge(source, target, **edge_options)

        # 写入HTML
        net.write_html(str(文件名), notebook=False)

        # 注入交互增强（含导航栏）
        self._注入交互增强(文件名, len(G.nodes()), len(G.edges()), 导航HTML)

    def _注入交互增强(self, html_file, 节点总数, 边总数, nav_html=""):
        """注入高级交互功能 + 可选导航HTML（修复版）"""
        # Community pages live beside the main page, so their parent directory
        # is the stable file identifier used by the edit/history API.
        graph_name = Path(html_file).parent.name
        interaction_html = build_graph_interaction_html(节点总数, 边总数, graph_name)
        with open(html_file, "r+", encoding="utf-8") as graph_html:
            content = graph_html.read()
            content = content.replace(
                "</body>",
                interaction_html + nav_html + "</body>",
            )
            # PyVis includes Bootstrap even though this page does not use its
            # controls. Remove those remaining remote dependencies.
            content = re.sub(
                r'\s*<link\b[^>]*href="https://cdn\.jsdelivr\.net/npm/bootstrap@[^\"]+"[^>]*>',
                '',
                content,
                flags=re.IGNORECASE | re.DOTALL,
            )
            content = re.sub(
                r'\s*<script\b[^>]*src="https://cdn\.jsdelivr\.net/npm/bootstrap@[^\"]+"[^>]*>\s*</script>',
                '',
                content,
                flags=re.IGNORECASE | re.DOTALL,
            )
            content = content.replace(' <script src="lib/bindings/utils.js"></script>', '')
            graph_html.seek(0)
            graph_html.write(content)
            graph_html.truncate()
        return

        js_injection = f"""
        <style>
            /* 隐藏pyvis自带控制面板 */
            div.vis-configuration-wrapper,
            div.vis-network div.vis-manipulation,
            div.vis-network div.vis-edit-mode-btn,
            div.vis-network div.vis-close-btn {{
                display: none !important;
            }}
            .control-panel {{
                position: absolute; top: 6px; right: 6px; z-index: 1000;
                background: rgba(255,255,255,0.95); padding: 6px 8px; border-radius: 6px;
                box-shadow: 0 1px 4px rgba(0,0,0,0.1); border: 1px solid #e8e8e8;
                min-width: auto; width: auto; backdrop-filter: blur(8px);
            }}
            .search-panel {{
                position: absolute; top: 6px; left: 6px; z-index: 1000;
                background: rgba(255,255,255,0.95); padding: 6px 8px; border-radius: 6px;
                box-shadow: 0 1px 4px rgba(0,0,0,0.1); border: 1px solid #e8e8e8;
                width: 180px; backdrop-filter: blur(8px);
            }}
            .panel-title {{
                color: #333; font-size: 10px; font-weight: 600; margin-bottom: 4px;
                border-bottom: 1px solid #f0f0f0; padding-bottom: 3px;
            }}
            .search-input {{
                width: 100%; padding: 4px 6px; border: 1px solid #ddd; border-radius: 4px;
                background: #fff; color: #333; font-size: 11px; box-sizing: border-box;
            }}
            .search-input:focus {{ outline: none; border-color: #2196F3; }}
            .search-results {{
                max-height: 150px; overflow-y: auto; margin-top: 4px;
                border: 1px solid #eee; border-radius: 4px; background: #fff; display: none;
            }}
            .search-result-item {{
                padding: 4px 6px; cursor: pointer; border-bottom: 1px solid #f5f5f5;
                color: #555; font-size: 10px; transition: all 0.15s; display: flex; align-items: center; gap: 4px;
            }}
            .search-result-item:hover {{ background: #f8f8f8; color: #2196F3; }}
            .search-result-item .type-badge {{
                font-size: 8px; padding: 1px 3px; border-radius: 2px; background: #2196F3; color: white; flex-shrink: 0;
            }}
            .search-result-item .type-badge.edge {{ background: #9C27B0; }}
            .control-btn {{
                display: inline-block; width: auto; min-width: 0; padding: 3px 8px; margin: 2px 1px;
                border: 1px solid #e0e0e0; border-radius: 4px; cursor: pointer; font-size: 10px;
                transition: all 0.15s; background: #fafafa; color: #555; font-weight: 500; white-space: nowrap;
            }}
            .control-btn:hover {{ background: #f0f0f0; border-color: #2196F3; color: #2196F3; }}
            .control-btn.active {{ background: #2196F3; border-color: #2196F3; color: white; }}
            .status-bar {{ margin-top: 4px; padding-top: 3px; border-top: 1px solid #f0f0f0; font-size: 9px; color: #999; }}
            .status-bar span {{ color: #2196F3; font-weight: 600; }}
            .filter-panel {{
                position: absolute; bottom: 6px; left: 6px; z-index: 1000;
                background: rgba(255,255,255,0.95); padding: 6px 8px; border-radius: 6px;
                border: 1px solid #e8e8e8; max-width: 150px; box-shadow: 0 1px 4px rgba(0,0,0,0.1);
            }}
            .filter-group {{ margin: 3px 0; }}
            .filter-label {{ font-size: 9px; color: #999; margin-bottom: 1px; }}
            .filter-slider {{ width: 100%; accent-color: #2196F3; height: 3px; }}
            .perf-tip {{
                position: absolute; bottom: 6px; right: 6px;
                background: rgba(255,255,255,0.9); padding: 3px 6px; border-radius: 3px;
                font-size: 8px; color: #bbb; border: 1px solid #eee;
            }}
            #edge-tooltip {{
                position: fixed; background: rgba(255,255,255,0.98); color: #333; padding: 6px 8px;
                border-radius: 5px; z-index: 10000; max-width: 220px; border: 1px solid #e0e0e0;
                font-size: 10px; box-shadow: 0 3px 10px rgba(0,0,0,0.12); pointer-events: none;
            }}
            /* 节点关系卡片 */
            #node-tooltip {{
                position: fixed;
                background: rgba(255,255,255,0.98);
                color: #333;
                padding: 8px 10px;
                border-radius: 6px;
                z-index: 10001;
                max-width: 300px;
                max-height: 260px;
                overflow-y: auto;
                border: 1px solid #e0e0e0;
                font-size: 10px;
                box-shadow: 0 3px 10px rgba(0,0,0,0.12);
                pointer-events: auto;          /* 允许鼠标事件，才能滚动 */
                line-height: 1.4;
            }}
            #node-tooltip .edge-item {{
                margin-bottom: 4px;
                padding-bottom: 4px;
                border-bottom: 1px dashed #eee;
            }}
            #node-tooltip .edge-item:last-child {{
                margin-bottom: 0;
                padding-bottom: 0;
                border-bottom: none;
            }}
            #node-tooltip .edge-label {{
                font-weight: 600;
                color: #2196F3;
            }}
            #node-tooltip .edge-meta {{
                color: #888;
                font-size: 9px;
            }}
        </style>
        <script>
        (function() {{
            const edgeStates = {{}};
            let globalHideMode = true;
            let focusMode = false;
            let searchTimeout = null;
            let hubNodes = new Set();
            const edgeOriginalWidths = {{}};
            const nodeDegrees = {{}};
            network.body.data.nodes.get().forEach(node => {{
                const connected = network.getConnectedNodes(node.id);
                nodeDegrees[node.id] = connected.length;
            }});
            const degreeValues = Object.values(nodeDegrees).sort((a,b) => b-a);
            const hubThreshold = degreeValues[Math.floor(degreeValues.length * 0.2)] || 0;
            Object.entries(nodeDegrees).forEach(([id, deg]) => {{
                if (deg >= hubThreshold && deg > 3) hubNodes.add(id);
            }});
            network.body.data.edges.get().forEach(edge => {{
                edgeStates[edge.id] = {{ clicked: false, labelVisible: false }};
                edgeOriginalWidths[edge.id] = edge.width || 1;
            }});

            document.addEventListener("DOMContentLoaded", function() {{
                const container = document.getElementById("mynetwork");
                // 搜索面板
                const searchPanel = document.createElement("div");
                searchPanel.className = "search-panel";
                searchPanel.innerHTML = `
                    <div class="panel-title">🔍 搜索</div>
                    <input type="text" id="searchInput" class="search-input" placeholder="搜索实体或关系...">
                    <div class="search-results" id="searchResults"></div>
                    <div class="status-bar"><span>{节点总数}</span> 节点, <span>{边总数}</span> 边</div>
                `;
                container.parentNode.insertBefore(searchPanel, container);
                // 控制面板
                const panel = document.createElement("div");
                panel.className = "control-panel";
                panel.innerHTML = `
                    <div class="panel-title">⚙️ 控制</div>
                    <div style="display:flex;flex-wrap:wrap;gap:2px;">
                        <button id="showAllBtn" class="control-btn">📋 显示</button>
                        <button id="hideAllBtn" class="control-btn active">👁️ 隐藏</button>
                        <button id="toggleHubsBtn" class="control-btn">🎯 折叠</button>
                        <button id="focusModeBtn" class="control-btn">🔦 聚焦</button>
                        <button id="resetBtn" class="control-btn">🔄 重置</button>
                    </div>
                    <div class="status-bar">已标记: <span id="counter">0</span></div>
                `;
                container.parentNode.insertBefore(panel, container);
                // 筛选面板
                const filterPanel = document.createElement("div");
                filterPanel.className = "filter-panel";
                filterPanel.innerHTML = `
                    <div class="panel-title">🔧 筛选</div>
                    <div class="filter-group">
                        <div class="filter-label">最小权重: <span id="weightValue">0.5</span></div>
                        <input type="range" id="weightFilter" class="filter-slider" min="0.5" max="1" step="0.1" value="0.5">
                    </div>
                    <div class="filter-group">
                        <div class="filter-label">Hub透明度</div>
                        <input type="range" id="hubOpacity" class="filter-slider" min="0" max="1" step="0.1" value="0.3">
                    </div>
                `;
                container.parentNode.insertBefore(filterPanel, container);
                const perfTip = document.createElement("div");
                perfTip.className = "perf-tip";
                perfTip.innerHTML = "💡 拖拽隐藏边线 | 滚轮缩放";
                container.parentNode.insertBefore(perfTip, container);

                const searchInput = document.getElementById("searchInput");
                const searchResults = document.getElementById("searchResults");
                searchInput.addEventListener("input", function() {{
                    clearTimeout(searchTimeout);
                    searchTimeout = setTimeout(() => {{
                        const term = this.value.toLowerCase().trim();
                        if (term.length < 1) {{ searchResults.style.display = "none"; return; }}
                        const results = [];
                        network.body.data.nodes.get().forEach(node => {{
                            if (node.label && node.label.toLowerCase().includes(term))
                                results.push({{ type:"node", id:node.id, label:node.label, extra: nodeDegrees[node.id] + "连接" }});
                        }});
                        network.body.data.edges.get().forEach(edge => {{
                            if (edge.label && edge.label.toLowerCase().includes(term))
                                results.push({{ type:"edge", id:edge.id, label:edge.label, extra: edge.weight ? edge.weight.toFixed(2) : "0.5" }});
                        }});
                        if (results.length === 0) {{
                            searchResults.innerHTML = '<div style="padding:4px;color:#999;font-size:10px;">无结果</div>';
                        }} else {{
                            searchResults.innerHTML = results.slice(0,8).map(r => `
                                <div class="search-result-item" data-type="${{r.type}}" data-id="${{r.id}}">
                                    <span class="type-badge ${{r.type}}">${{r.type==="node"?"节点":"关系"}}</span>
                                    <div style="flex:1;overflow:hidden;text-overflow:ellipsis;">${{r.label}}</div>
                                </div>`).join("");
                        }}
                        searchResults.style.display = "block";
                        searchResults.querySelectorAll(".search-result-item").forEach(item => {{
                            item.addEventListener("click", function() {{
                                const type = this.dataset.type, id = this.dataset.id;
                                if (type === "node") {{
                                    network.selectNodes([id]);
                                    network.focus(id, {{ scale:1.5, animation:{{ duration:400 }} }});
                                }} else {{
                                    network.selectEdges([id]);
                                    const edge = network.body.data.edges.get(id);
                                    network.fit({{ nodes:[edge.from, edge.to], animation:{{ duration:400 }} }});
                                }}
                            }});
                        }});
                    }}, 200);
                }});
                document.addEventListener("click", (e) => {{ if (!searchPanel.contains(e.target)) searchResults.style.display = "none"; }});

                document.getElementById("weightFilter").addEventListener("input", function() {{
                    const minWeight = parseFloat(this.value);
                    document.getElementById("weightValue").textContent = minWeight.toFixed(1);
                    network.body.data.edges.get().forEach(edge => {{
                        edge.hidden = (edge.weight || 0.5) < minWeight;
                        network.body.data.edges.update(edge);
                    }});
                }});
                document.getElementById("hubOpacity").addEventListener("input", function() {{
                    const opacity = parseFloat(this.value);
                    network.body.data.edges.get().forEach(edge => {{
                        if (hubNodes.has(edge.from) || hubNodes.has(edge.to)) {{
                            edge.color = edge.color || {{}}; edge.color.opacity = opacity;
                            network.body.data.edges.update(edge);
                        }}
                    }});
                }});

                function updateCounter() {{
                    document.getElementById("counter").innerText = Object.values(edgeStates).filter(s=>s.clicked).length;
                }}
                document.getElementById("showAllBtn").onclick = function() {{
                    network.body.data.edges.get().forEach(edge => {{
                        edge.font = {{ size:10, color:"#666" }};
                        network.body.data.edges.update(edge);
                        edgeStates[edge.id].labelVisible = true;
                    }});
                    globalHideMode = false;
                    document.querySelectorAll(".control-btn").forEach(b => b.classList.remove("active"));
                    this.classList.add("active");
                    updateCounter();
                }};
                document.getElementById("hideAllBtn").onclick = function() {{
                    network.body.data.edges.get().forEach(edge => {{
                        if (!edgeStates[edge.id].clicked) {{
                            edge.font = {{ size:0 }};
                            network.body.data.edges.update(edge);
                            edgeStates[edge.id].labelVisible = false;
                        }}
                    }});
                    globalHideMode = true;
                    document.querySelectorAll(".control-btn").forEach(b => b.classList.remove("active"));
                    this.classList.add("active");
                    updateCounter();
                }};
                let hubsCollapsed = false;
                document.getElementById("toggleHubsBtn").onclick = function() {{
                    hubsCollapsed = !hubsCollapsed;
                    this.classList.toggle("active");
                    hubNodes.forEach(hubId => {{
                        const connectedEdges = network.body.data.edges.get().filter(e => e.from===hubId || e.to===hubId);
                        if (hubsCollapsed) {{
                            const sorted = connectedEdges.sort((a,b)=>(b.weight||0)-(a.weight||0));
                            sorted.slice(3).forEach(e => {{ e.hidden = true; network.body.data.edges.update(e); }});
                        }} else {{
                            connectedEdges.forEach(e => {{ e.hidden = false; network.body.data.edges.update(e); }});
                        }}
                    }});
                }};
                document.getElementById("focusModeBtn").onclick = function() {{
                    focusMode = !focusMode;
                    this.classList.toggle("active");
                    if (!focusMode) {{
                        network.body.data.nodes.get().forEach(n => {{
                            n.hidden = false; n.color = n.color||{{}}; delete n.color.opacity; network.body.data.nodes.update(n);
                        }});
                        network.body.data.edges.get().forEach(e => {{ e.hidden = false; network.body.data.edges.update(e); }});
                        return;
                    }}
                    const selected = network.getSelectedNodes();
                    if (selected.length === 0) {{
                        alert("请先选中一个节点"); focusMode = false; this.classList.remove("active"); return;
                    }}
                    const keepNodes = new Set(selected);
                    selected.forEach(id => {{ network.getConnectedNodes(id).forEach(n => keepNodes.add(n)); }});
                    network.body.data.nodes.get().forEach(n => {{
                        if (!keepNodes.has(n.id)) {{ n.hidden = true; network.body.data.nodes.update(n); }}
                    }});
                }};
                document.getElementById("resetBtn").onclick = function() {{
                    network.body.data.edges.get().forEach(edge => {{
                        edge.font = {{ size:0 }};
                        edge.hidden = false;
                        edge.color = edge.color||{{}}; edge.color.opacity = 0.6;
                        edge.width = edgeOriginalWidths[edge.id];
                        network.body.data.edges.update(edge);
                        edgeStates[edge.id] = {{ clicked:false, labelVisible:false }};
                    }});
                    network.body.data.nodes.get().forEach(n => {{
                        n.hidden = false; n.color = n.color||{{}}; delete n.color.opacity;
                        network.body.data.nodes.update(n);
                    }});
                    globalHideMode = true; focusMode = false; hubsCollapsed = false;
                    document.querySelectorAll(".control-btn").forEach(b => b.classList.remove("active"));
                    document.getElementById("hideAllBtn").classList.add("active");
                    network.fit({{ animation:{{ duration:400 }} }});
                    updateCounter();
                }};

                // 边选中
                network.on("selectEdge", function(params) {{
                    if (params.edges.length === 0) return;
                    const edge = network.body.data.edges.get(params.edges[0]);
                    edgeStates[edge.id].clicked = true;
                    edge.font = {{ size:10, color:"#2196F3" }};
                    edge.color = edge.color||{{}}; edge.color.color = "#2196F3";
                    network.body.data.edges.update(edge);
                    updateCounter();
                }});

                // 优化后的节点选择批量更新
                network.on("selectNode", function(params) {{
                    if (focusMode) return;
                    const selectedId = params.nodes[0];
                    const neighbors = new Set(network.getConnectedNodes(selectedId));
                    neighbors.add(selectedId);

                    const allNodes = network.body.data.nodes.get();
                    const allEdges = network.body.data.edges.get();

                    const nodesToUpdate = [];
                    allNodes.forEach(n => {{
                        const shouldHighlight = neighbors.has(n.id);
                        const currentOpacity = n.color?.opacity;
                        const targetOpacity = shouldHighlight ? undefined : 0.15;
                        if (shouldHighlight && currentOpacity !== undefined) {{
                            n.color = {{ ...n.color }};
                            delete n.color.opacity;
                            nodesToUpdate.push(n);
                        }} else if (!shouldHighlight && currentOpacity !== 0.15) {{
                            n.color = {{ ...n.color, opacity: 0.15 }};
                            nodesToUpdate.push(n);
                        }}
                    }});

                    const edgesToUpdate = [];
                    allEdges.forEach(e => {{
                        const isConnectedEdge = (e.from === selectedId || e.to === selectedId);
                        const targetOpacity = isConnectedEdge ? 1 : 0.1;
                        const targetWidth = isConnectedEdge ? (edgeOriginalWidths[e.id] + 1.5) : undefined;
                        const currentOpacity = e.color?.opacity;
                        const currentWidth = e.width;

                        let needsUpdate = false;
                        if (currentOpacity !== targetOpacity) needsUpdate = true;
                        if (isConnectedEdge && currentWidth !== targetWidth) needsUpdate = true;
                        if (!isConnectedEdge && currentWidth !== edgeOriginalWidths[e.id]) needsUpdate = true;

                        if (needsUpdate) {{
                            const updatedEdge = {{ ...e, color: {{ ...e.color, opacity: targetOpacity }} }};
                            if (isConnectedEdge) {{
                                updatedEdge.width = targetWidth;
                            }} else {{
                                updatedEdge.width = edgeOriginalWidths[e.id];
                            }}
                            edgesToUpdate.push(updatedEdge);
                        }}
                    }});

                    if (nodesToUpdate.length > 0) network.body.data.nodes.update(nodesToUpdate);
                    if (edgesToUpdate.length > 0) network.body.data.edges.update(edgesToUpdate);
                }});

                // 取消选择恢复
                network.on("deselectNode", function() {{
                    if (focusMode) return;
                    const allNodes = network.body.data.nodes.get();
                    const allEdges = network.body.data.edges.get();

                    const nodesToUpdate = [];
                    allNodes.forEach(n => {{
                        if (n.color?.opacity !== undefined) {{
                            n.color = {{ ...n.color }};
                            delete n.color.opacity;
                            nodesToUpdate.push(n);
                        }}
                    }});

                    const edgesToUpdate = [];
                    allEdges.forEach(e => {{
                        const defaultOpacity = (hubNodes.has(e.from) || hubNodes.has(e.to)) ? 0.3 : 0.6;
                        const currentOpacity = e.color?.opacity;
                        const currentWidth = e.width;
                        const originalWidth = edgeOriginalWidths[e.id];
                        if (currentOpacity !== defaultOpacity || currentWidth !== originalWidth) {{
                            edgesToUpdate.push({{ ...e, color: {{ ...e.color, opacity: defaultOpacity }}, width: originalWidth }});
                        }}
                    }});

                    if (nodesToUpdate.length > 0) network.body.data.nodes.update(nodesToUpdate);
                    if (edgesToUpdate.length > 0) network.body.data.edges.update(edgesToUpdate);
                }});

                // 边悬停提示
                network.on("hoverEdge", function(params) {{
                    const edge = network.body.data.edges.get(params.edge);
                    let tooltip = document.getElementById('edge-tooltip');
                    if (!tooltip) {{ tooltip = document.createElement('div'); tooltip.id = 'edge-tooltip'; document.body.appendChild(tooltip); }}
                    tooltip.innerHTML = `
                        <div style="font-weight:600;margin-bottom:2px;color:#2196F3;">${{edge.label || '未命名关系'}}</div>
                        <div style="color:#666;font-size:9px;">${{edge.title || '无描述'}}</div>
                        <div style="margin-top:3px;padding-top:3px;border-top:1px solid #eee;">
                            <span style="color:#ff6b35;">权重: ${{edge.weight?.toFixed(2) || '0.50'}}</span>
                            <span style="margin-left:6px;color:#4CAF50;">${{edge.from}} → ${{edge.to}}</span>
                        </div>`;
                    tooltip.style.left = (window.event?.clientX + 12 || 100) + 'px';
                    tooltip.style.top = (window.event?.clientY + 12 || 100) + 'px';
                    tooltip.style.display = 'block';
                }});
                network.on("blurEdge", function() {{
                    const tooltip = document.getElementById('edge-tooltip');
                    if (tooltip) tooltip.style.display = 'none';
                }});

                // ========== 节点悬停关系卡片（可滚动） ==========
                const nodeTooltip = document.getElementById('node-tooltip') || document.createElement('div');
                if (!nodeTooltip.id) {{
                    nodeTooltip.id = 'node-tooltip';
                    document.body.appendChild(nodeTooltip);
                }}
                let nodeTooltipHideTimer = null;
                let currentNodeId = null;

                function showNodeTooltip(nodeId, clientX, clientY) {{
                    const connectedEdges = network.getConnectedEdges(nodeId);
                    if (connectedEdges.length === 0) {{
                        nodeTooltip.style.display = 'none';
                        return;
                    }}

                    let html = `<div style="font-weight:600;margin-bottom:4px;color:#333;">节点关系（共 ${{connectedEdges.length}} 条）</div>`;
                    const maxShow = 20;
                    const edgesToShow = connectedEdges.slice(0, maxShow);

                    edgesToShow.forEach(edgeId => {{
                        const edge = network.body.data.edges.get(edgeId);
                        const label = edge.label || `${{edge.from}} → ${{edge.to}}`;
                        const title = edge.title || '';
                        const weight = edge.weight ? edge.weight.toFixed(2) : '0.50';
                        html += `
                            <div class="edge-item">
                                <div class="edge-label">${{label}}</div>
                                <div class="edge-meta">
                                    权重: ${{weight}} ${{title ? ' | ' + title : ''}}
                                </div>
                            </div>
                        `;
                    }});

                    if (connectedEdges.length > maxShow) {{
                        html += `<div style="font-size:9px;color:#999;margin-top:4px;">...等 ${{connectedEdges.length - maxShow}} 条更多</div>`;
                    }}

                    nodeTooltip.innerHTML = html;
                    nodeTooltip.style.left = (clientX + 15) + 'px';
                    nodeTooltip.style.top = (clientY + 15) + 'px';
                    nodeTooltip.style.display = 'block';
                }}

                network.on("hoverNode", function(params) {{
                    clearTimeout(nodeTooltipHideTimer);
                    currentNodeId = params.node;
                    const event = params.event;
                    showNodeTooltip(params.node, event.clientX, event.clientY);
                }});

                network.on("blurNode", function() {{
                    nodeTooltipHideTimer = setTimeout(() => {{
                        nodeTooltip.style.display = 'none';
                        currentNodeId = null;
                    }}, 300);
                }});

                nodeTooltip.addEventListener('mouseenter', function() {{
                    clearTimeout(nodeTooltipHideTimer);
                }});

                nodeTooltip.addEventListener('mouseleave', function() {{
                    nodeTooltip.style.display = 'none';
                    currentNodeId = null;
                }});

                nodeTooltip.addEventListener('mousemove', function(e) {{
                    e.stopPropagation();
                }});

                updateCounter();
            }});
        }})();
        </script>
        """

        with open(html_file, "r+", encoding="utf-8") as f:
            content = f.read()
            content = content.replace("</body>", js_injection + nav_html + "</body>")
            content = content.replace(' <script src="lib/bindings/utils.js"></script>', '')
            f.seek(0)
            f.write(content)
            f.truncate()

    # 获取提问的实体（存在与知识图谱的）
    def text2entity(self, text):
        prompt = open(f"./prompt/{prompt_vision}/entity_q2merge.txt", encoding='utf-8').read()
        entity = [str(i) for i in self.current_G]
        input_parameter = f"实体列表：{entity}\n问题：{text}"
        output = self.Agent.agent_safe_generate_response(
            prompt,
            input_parameter,
            expected_key="entities",
        )
        return output['entities']

    # 对比两个有向图对象的差异
    def compare_and_visualize(self, G2, output_file="diff_graph"):
        G1 = self.current_G.to_undirected()
        """比较两个有向图并用pyvis高亮差异"""
        # 创建合并图（包含G1和G2的所有节点和边）
        G_diff = nx.DiGraph()

        # 记录差异
        diff = {
            "added_nodes": set(G2.nodes()) - set(G1.nodes()),
            "removed_nodes": set(G1.nodes()) - set(G2.nodes()),
            "added_edges": set(G2.edges()) - set(G1.edges()),
            "removed_edges": set(G1.edges()) - set(G2.edges()),
            "node_attr_changes": {},
            "edge_attr_changes": {}
        }

        # 检查节点属性变化
        common_nodes = set(G1.nodes()) & set(G2.nodes())
        for node in common_nodes:
            if G1.nodes[node] != G2.nodes[node]:
                diff["node_attr_changes"][node] = {
                    "old": G1.nodes[node],
                    "new": G2.nodes[node]
                }

        # 检查边属性变化
        common_edges = set(G1.edges()) & set(G2.edges())
        for u, v in common_edges:
            if G1.edges[u, v] != G2.edges[u, v]:
                diff["edge_attr_changes"][(u, v)] = {
                    "old": G1.edges[u, v],
                    "new": G2.edges[u, v]
                }

        # 将差异信息添加到图
        for node in G1.nodes() | G2.nodes():
            G_diff.add_node(node)

            # 设置节点颜色和标题（悬停显示详情）
            if node in diff["added_nodes"]:
                G_diff.nodes[node]["color"] = "green"
                G_diff.nodes[node]["title"] = f"新增节点: {node}"
            elif node in diff["removed_nodes"]:
                G_diff.nodes[node]["color"] = "red"
                G_diff.nodes[node]["title"] = f"删除节点: {node}"
            elif node in diff["node_attr_changes"]:
                G_diff.nodes[node]["color"] = "yellow"
                changes = diff["node_attr_changes"][node]
                G_diff.nodes[node]["title"] = (
                    f"节点属性修改: {node}\n"
                    f"旧值: {changes['old']}\n"
                    f"新值: {changes['new']}"
                )
            else:
                G_diff.nodes[node]["color"] = "skyblue"

        for u, v in G1.edges() | G2.edges():
            if (u, v) in diff["added_edges"]:
                G_diff.add_edge(u, v, color="green", title=f"新增边: ({u}→{v})")
            elif (u, v) in diff["removed_edges"]:
                G_diff.add_edge(u, v, color="red", title=f"删除边: ({u}→{v})")
            elif (u, v) in diff["edge_attr_changes"]:
                changes = diff["edge_attr_changes"][(u, v)]
                G_diff.add_edge(u, v, color="yellow",
                                title=f"边属性修改: ({u}→{v})\n旧值: {changes['old']}\n新值: {changes['new']}")
            else:
                G_diff.add_edge(u, v, color="gray")

        # 用pyvis绘制动态图
        nt = Network(height="900px", width="100%", notebook=True)
        nt.from_nx(G_diff)

        # 保存并显示
        nt.show(f"{output_file}.html")

    def save_store(self):
        """将当前状态保存到存储"""
        if self.store:
            self.store.save_state(self)

    def load_store(self, filename):
        """从存储加载指定文件名的状态"""
        if self.store:
            state = self.store.load_state(filename)
            if state:
                self.file = state["file"]
                self.kg_triplet = state["kg_triplet"]
                self.bidirectional_mapping = state["bidirectional_mapping"]
                self.current_G = state["current_G"]
                self.Bolts = state["Bolts"]
                self.original_file_type = state.get('original_file_type', '.txt')
                self._persisted_bolt_count = len(self.Bolts)
                self._persisted_bolt_file = self.file
                return True
        return False

    def delete_store(self, filenames: list):
        return self.store.delete_states(filenames)


    def list_files(self):
        return self.store.list_files()


    def select_vectors(self,query,n_results):
        results = self.store.select_vectors(
            query=query,
            file=self.file,
            n_results=n_results
        )
        return results["documents"]
