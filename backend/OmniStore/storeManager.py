import os
import random
from community import community_louvain
from dotenv import load_dotenv

load_dotenv()  # 默认会加载根目录下的.env文件
prompt_vision = os.getenv("PROMPTVISION")

class  storeManager:
    def __init__(self,store,agent):
        self.store = store
        self.agent = agent

    def list_files(self):
        return self.store.list_files()


    def get_G(self, file):
        try:
            state = self.store.load_state(file)
            if state is None or 'current_G' not in state:
                print(f"找不到文件的知识图谱状态: {file}")
                return None

            current_G = state['current_G']
            return current_G
        except Exception as e:
            print(f"加载知识图谱出错: {file}, 错误: {str(e)}")
            return None

    def get_n_entity(self,file,n):
        # "bidirectional_mapping": {
        #     "entity_to_label": dict(json.l
        try:
            state = self.store.load_state(file)
            if state is None or 'bidirectional_mapping' not in state:
                print(f"找不到文件的实体状态: {file}")
                return None

            entity = list(state['bidirectional_mapping']['entity_to_label'].keys())
            if len(entity) <= n:
                return entity
            return random.sample(entity, n)

        except Exception as e:
            print(f"加载知识图谱出错: {file}, 错误: {str(e)}")
            return None

    def edge_max_node(self,file,n):
        current_g = self.get_G(file)
        degrees = current_g.degree()
        sorted_degrees = sorted(degrees, key=lambda x: x[1], reverse=True)
        return sorted_degrees[:n]



    def text2entity(self, query: str, file: str):
        current_g = self.get_G(file)
        # 添加对current_G为None的检查
        if current_g is None:
            print(f"无法获取知识图谱数据: {file}")
            return []

        prompt = open(f"./prompt/{prompt_vision}/entity_q2merge.txt", encoding='utf-8').read()
        entity = [str(i) for i in current_g]
        input_parameter = f"实体列表：{entity}\n问题：{query}"
        output = self.agent.agent_safe_generate_response(
            prompt,
            input_parameter,
            expected_key="entities",
        )
        # A truncated/invalid entity response must not abort the whole RAG
        # queue. Vector retrieval can still answer the question without graph
        # context, while the caller can continue with an empty entity set.
        if not isinstance(output, dict):
            return []
        entities = output.get("entities", [])
        if not isinstance(entities, list):
            return []
        return entities


    def select_vectors(self, query, file, n_results):
        try:
            results = self.store.select_vectors(
                query=query,
                file=file,
                n_results=n_results
            )
            # print(results)
            return results.get("documents", [])
        except Exception as e:
            print(f"选择向量失败: {file}, 错误: {str(e)}")
            return []


    def community_louvain_G(self, file, entity_names, weight_threshold=0.3, top_n=20):
        """
        基于社区算法和权重阈值查找相关知识
        
        Args:
            file: 文件名
            entity_names: 输入的实体名称列表
            weight_threshold: 权重阈值，默认0.3，只返回权重大于此值的关系
            top_n: 返回的最大关系数量，默认20
            
        Returns:
            知识库列表
        """
        current_G = self.get_G(file)
        if current_G is None:
            print(f"无法获取知识图谱数据进行社区检测: {file}")
            return []

        knowledge_base = []

        # 执行社区检测（在整个图上）
        partition = community_louvain.best_partition(current_G.to_undirected())
        
        # 获取每个输入实体的社区编号
        community_ids = set()
        for entity in entity_names:
            if entity in partition:
                community_ids.add(partition[entity])

        # 提取特定社区内的所有节点
        community_nodes = [node for node, comm_id in partition.items() if comm_id in community_ids]

        # 构建包含选定社区内所有节点的子图
        subgraph = current_G.subgraph(community_nodes)

        # 收集所有边信息并根据权重排序
        edges_with_weight = []
        for edge in subgraph.edges(data=True):
            source, target = edge[0], edge[1]
            edge_data = edge[2]
            # 从边属性中获取数据
            relation = edge_data.get('label', 'Unknown')
            context = edge_data.get('title', 'No Context')
            weight = edge_data.get('weight', 0.5)  # 获取权重，默认0.5
            
            # 只添加权重大于等于阈值的边
            if weight >= weight_threshold:
                edges_with_weight.append({
                    'source': source,
                    'target': target,
                    'relation': relation,
                    'context': context,
                    'weight': weight
                })
        
        # 按权重降序排序
        edges_with_weight.sort(key=lambda x: x['weight'], reverse=True)
        # print(edges_with_weight, "test")
        # 如果指定了top_n，则只取前top_n个关系
        if top_n > 0:
            edges_with_weight = edges_with_weight[:top_n]
        # 转换为知识库格式
        print(edges_with_weight,'edges')
        if not edges_with_weight:
            return []

        for edge in edges_with_weight:
            knowledge_base.append(
                f"Edge from {edge['source']} to {edge['target']}, Relation: {edge['relation']}, context:{edge['context']}, weight:{edge['weight']}"
            )
        modularity = community_louvain.modularity(partition, current_G.to_undirected())
        print(f"\nModularity of the entire graph: {modularity}")

        return knowledge_base


