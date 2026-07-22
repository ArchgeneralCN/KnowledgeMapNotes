import asyncio
from openai import OpenAI
from pydantic import BaseModel
from fastapi import FastAPI, File, UploadFile, BackgroundTasks, Form
from fastapi.middleware.cors import CORSMiddleware
from pyvis.network import Network
import networkx as nx
import itertools
import logging
from typing import Dict, List, Optional, AsyncGenerator
from OmniText.PDFProcessor import PDFProcessor
from OmniText.MDProcessor import MDProcessor
from concurrent.futures import ThreadPoolExecutor
import json
from dotenv import load_dotenv
import os
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'

load_dotenv(dotenv_path="../.env")

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("../app.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("文件处理服务")


class rag_item(BaseModel):
    request: str
    model: str
    flow: bool = False
    top_k: int = 1
    weight_threshold: float = 0.3  # 添加权重阈值参数
    max_relations: int = 20  # 添加最大关系数量参数
    filename: Optional[str] = None
    messages: Optional[List[Dict[str, str]]] = None  # 确保消息格式正确
    session_id: Optional[str] = None  # 会话ID，用于跟踪特定文件的对话


app = FastAPI(title="图谱笔记", description="大模型知识图谱笔记软件")

UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER")
TXT_FOLDER = os.getenv("TXT_FOLDER")
RESULT_FOLDER = os.getenv("RESULT_FOLDER")

PROCESS_STATUS: Dict[str, str] = {}

# 确保目录存在
for folder in [UPLOAD_FOLDER, TXT_FOLDER, RESULT_FOLDER]:
    os.makedirs(folder, exist_ok=True)

# 初始化知识图谱组件
from OmniStore.chromadb_store import StoreTool
from sentence_transformers import SentenceTransformer
from KnowledgeGraphManager.KGManager import KgManager



device = os.getenv("DEVICE")


if os.getenv("IS_USE_LOCAL") == "True":
    embeddings = SentenceTransformer(
        os.getenv("EMBEDDINGS_PATH")
    ).to(device)
else:
    # 初始化模型和组件
    embeddings = SentenceTransformer(os.getenv("EMBEDDINGS")).to(device)


# 创建两个独立的存储工具
chromadb_store = StoreTool(storage_path= '../chroma_data', embedding_function=embeddings)

client = OpenAI(
    api_key=os.getenv("API_KEY"),
    base_url=os.getenv("BASE_URL")
)

# 多模态模型
vl_client = OpenAI(
    # 若没有配置环境变量，请用百炼API Key将下行替换为：api_key="sk-xxx"
    api_key=os.getenv("VL_API_KEY"),
    base_url=os.getenv("VL_BASE_URL")
)
from LLM.Openai_Agent import OpenaiAgent
# 创建两个独立的agent
rag_agent = OpenaiAgent(client)
kg_agent = OpenaiAgent(client)

# 创建两个独立的splitter
simple_files = os.getenv("SIMPLE", "").split(",")
semantic_files = os.getenv("SEMANTIC", "").split(",")
character_files = os.getenv("CHARACTER", "").split(",")

# 初始化默认分割器
kg_splitter = None

# 创建默认分割器
if len(simple_files) > 0:
    from TextSlicer.SimpleTextSplitter import SimpleTextSplitter
    kg_splitter = SimpleTextSplitter(2048, 1024)
elif len(semantic_files) > 0:
    from TextSlicer.SemanticTextSplitter import SemanticTextSplitter
    kg_splitter = SemanticTextSplitter(2048, 1024)
elif len(character_files) > 0:
    from TextSlicer.CharacterTextSplitter import CharacterTextSplitter
    kg_splitter = CharacterTextSplitter(separator="</end>", keep_separator=False, max_tokens=2048, min_tokens=1024)

# 创建两个独立的kg_manager
kg_manager = KgManager(agent=kg_agent, splitter=kg_splitter, embedding_model=embeddings, store=chromadb_store)

FILE_PROCESSORS = {
    '.pdf': PDFProcessor,
    '.md': MDProcessor,
    # 可扩展，不想写了。。。
}
# 添加CORS支持
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 添加线程池
executor = ThreadPoolExecutor(max_workers=16)  # 增加线程池大小以处理更多并发请求
# 添加专用于RAG的线程池
rag_executor = ThreadPoolExecutor(max_workers=16)  # RAG专用线程池
# 添加文件处理锁
file_locks = {}
# 添加RAG问答锁
rag_locks = {}

# 消息队列系统
# 存储结构: {session_id: deque([消息1, 消息2, ...]), ...}
message_queues = {}
# 每个会话的事件: {session_id: Event(), ...}
session_events = {}
# 每个会话的响应状态: {session_id: {"status": "processing/completed/error", "response": [..]}, ...}
session_responses = {}




class 知识图谱可视化:
    def __init__(self, graph=None):
        self.current_G = graph or nx.DiGraph()
        self.file = None

    def 绘制知识图谱(self, name, 聚类算法="louvain", 物理引擎="forceAtlas2Based"):
        """
        优化版知识图谱可视化（支持社区分页渲染）

        参数:
            name: 输出文件名（主页面将保存为 name.html）
            聚类算法: "louvain"(社区发现) | "kmeans" | None
            物理引擎: "forceAtlas2Based"(推荐) | "barnesHut" | "force"
        """
        self.file = name

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
        MIN_SIZE = 20  # 可调：大于此值才单独生成页面

        启用分页 = (聚类算法 == "louvain") and (社区数量 > 1) and (最大社区大小 >= MIN_SIZE)

        if not 启用分页:
            # 原逻辑：生成单一全图页面
            self._渲染图(self.current_G, f"{name}.html", 社区分配, 物理引擎, 导航HTML="")
            print(f"✅ 知识图谱已生成: {name}.html")
            print(f"   节点数: {len(self.current_G.nodes())}, 边数: {len(self.current_G.edges())}")
            return self.current_G

        # ---------- 分页模式 ----------
        大社区 = [cid for cid, size in 社区节点计数.items() if size >= MIN_SIZE]
        # 确定文件名
        主文件名 = f"{name}.html"
        子文件名 = {cid: f"{name}_community_{cid}.html" for cid in 大社区}

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
                          group=cid,
                          title=f"社区 {cid}\n节点数: {size}\n代表节点: {代表节点名}")

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
        导航链接列表 = "".join(
            f'<a href="{子文件名[cid]}" style="margin:0 8px;color:#2196F3;">'
            f'{社区代表节点.get(cid, f"社区{cid}")}</a>'
            for cid in 大社区
        )

        # 主页面底部导航HTML
        导航HTML_主 = f"""
        <div style="position:fixed;bottom:12px;left:50%;transform:translateX(-50%);z-index:2000;
                    background:rgba(255,255,255,0.95);padding:6px 16px;border-radius:20px;
                    box-shadow:0 2px 8px rgba(0,0,0,0.15);font-size:13px;">
            📂 <b>社区详情页：</b>{导航链接列表}
        </div>
        """
        self._渲染图(ov_G, 主文件名, 社区分配={}, 物理引擎=物理引擎, 导航HTML=导航HTML_主)

        # ---- 5. 为每个大社区生成子页面 ----
        for cid in 大社区:
            子节点 = [n for n, c in 社区分配.items() if c == cid]
            子图 = self.current_G.subgraph(子节点).copy()

            代表名 = 社区代表节点.get(cid, f"社区{cid}")
            导航HTML_子 = f"""
            <div style="position:fixed;bottom:12px;left:50%;transform:translateX(-50%);z-index:2000;
                        background:rgba(255,255,255,0.95);padding:5px 14px;border-radius:20px;
                        box-shadow:0 2px 8px rgba(0,0,0,0.15);font-size:13px;">
                ⬅️ <a href="{主文件名}" style="color:#2196F3;">返回总览图</a> &nbsp;|&nbsp;
                {代表名}（{len(子节点)} 个节点）
            </div>
            """
            self._渲染图(子图, 子文件名[cid], 社区分配={}, 物理引擎=物理引擎, 导航HTML=导航HTML_子)

        print(f"✅ 知识图谱已生成（社区分页）:")
        print(f"   主页面（跨社区关系）: {主文件名}  ({社区数量} 个社区, {ov_G.number_of_edges()} 条跨社区边)")
        for cid in 大社区:
            print(f"   社区 {cid} 详情页: {子文件名[cid]}  ({社区节点计数[cid]} 个节点)")
        return self.current_G

    def _渲染图(self, G, 文件名, 社区分配, 物理引擎, 导航HTML=""):
        """
        内部渲染函数：将图 G 渲染为单个 HTML 文件
        社区分配: 节点 -> 社区ID 的字典，空字典则全部归为0组
        """
        if not 社区分配:
            社区分配 = {n: 0 for n in G.nodes()}

        # 节点重要性计算
        节点度数 = dict(G.degree())
        最大度数 = max(节点度数.values()) if 节点度数 else 1
        try:
            pagerank = nx.pagerank(G)
        except:
            pagerank = {n: 1.0 for n in G.nodes()}

        # 创建PyVis网络
        is_directed = G.is_directed()  # 根据图类型自适应
        net = Network(
            notebook=True,
            height="750px",
            width="100%",
            bgcolor="#ffffff",
            font_color="#1a1a1a",
            directed=is_directed,
            cdn_resources='remote'
        )

        # 物理引擎配置
        # ===== 动态物理引擎配置 =====
        节点总数 = len(G.nodes())
        if 节点总数 > 200:
            # 大图：强重力、短弹簧、更多迭代，快速稳定
            physics = {
                "forceAtlas2Based": {
                    "gravitationalConstant": -120,
                    "centralGravity": 0.01,
                    "springLength": 100,
                    "springConstant": 0.12,
                    "damping": 0.5,
                    "avoidOverlap": 1.0
                },
                "solver": "forceAtlas2Based",
                "stabilization": {
                    "enabled": True,
                    "iterations": 500,  # 增加迭代次数
                    "updateInterval": 25,
                    "onlyDynamicEdges": False,
                    "fit": True
                },
                "maxVelocity": 30,
                "minVelocity": 0.1,
                "timestep": 0.25
            }
        elif 节点总数 > 100:
            # 中图：适度调整
            physics = {
                "forceAtlas2Based": {
                    "gravitationalConstant": -100,
                    "centralGravity": 0.008,
                    "springLength": 150,
                    "springConstant": 0.1,
                    "damping": 0.45,
                    "avoidOverlap": 1.0
                },
                "solver": "forceAtlas2Based",
                "stabilization": {"iterations": 400}
            }
        else:
            # 小图：保留原精美配置
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
                "stabilization": {"iterations": 300}
            }

        options = {
            "nodes": {
                "shape": "dot",
                "scaling": {"min": 10, "max": 40, "label": {"enabled": True, "min": 14, "max": 24}},
                "font": {"size": 14, "face": "Microsoft YaHei, SimHei, sans-serif", "color": "#1a1a1a"},
                "borderWidth": 2, "borderWidthSelected": 4,
                "shadow": {"enabled": True, "size": 10, "x": 3, "y": 3}
            },
            "edges": {
                "width": 1,
                "color": {"color": "#a0a0a0", "highlight": "#ff6b35", "hover": "#ff6b35", "opacity": 0.6},
                "smooth": {"type": "continuous", "roundness": 0.5},
                "selectionWidth": 3, "hoverWidth": 2,
                "arrows": {
                    "to": {"enabled": is_directed, "scaleFactor": 0.5}
                },
                "font": {"size": 0, "face": "Microsoft YaHei", "color": "#666666",
                         "align": "middle", "background": "rgba(255,255,255,0.9)"}
            },
            "interaction": {
                "hover": True, "tooltipDelay": 100, "hideEdgesOnDrag": True,
                "hideNodesOnDrag": False, "multiselect": True, "navigationButtons": False,
                "keyboard": True
            },
            "layout": {"improvedLayout": True}
        }
        options.update({"physics": physics})
        net.set_options(json.dumps(options, indent=2))

        # 添加节点
        for node, attr in G.nodes(data=True):
            degree = 节点度数.get(node, 0)
            pr = pagerank.get(node, 0)
            size = 15 + (degree / 最大度数) * 25 + pr * 20
            is_hub = degree > 最大度数 * 0.3 if 最大度数 > 0 else False
            group = attr.get('group', 社区分配.get(node, 0))

            # 优先使用节点属性中的 label
            node_label = str(attr.get('label', node))

            node_options = {
                "title": attr.get('title', f'节点: {node}\n连接数: {degree}\nPageRank: {pr:.3f}'),
                "value": size,
                "group": group,
                "color": {
                    "background": "#ff6b35" if is_hub else "#2196F3",
                    "border": "#e55a2b" if is_hub else "#1976D2",
                    "highlight": {"background": "#ff8a5c" if is_hub else "#64B5F6",
                                  "border": "#ff6b35" if is_hub else "#2196F3"},
                    "hover": {"background": "#ff8a5c" if is_hub else "#64B5F6",
                              "border": "#ff6b35" if is_hub else "#2196F3"}
                }
            }
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
            if is_hub_edge:
                edge_options["smooth"] = {"type": "curvedCW", "roundness": 0.3}
            net.add_edge(source, target, **edge_options)

        # 写入HTML
        net.write_html(文件名, notebook=False)

        # 注入交互增强（含导航栏）
        self._注入交互增强(文件名, len(G.nodes()), len(G.edges()), 导航HTML)

    def _注入交互增强(self, html_file, 节点总数, 边总数, nav_html=""):
        """注入高级交互功能 + 可选导航HTML（修复版）"""
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


# ========== 使用示例 ==========
if __name__ == "__main__":
    kg_manager.load_store("result")
    G = kg_manager.current_G.to_undirected()
    visualizer = 知识图谱可视化(G)
    visualizer.绘制知识图谱("result")