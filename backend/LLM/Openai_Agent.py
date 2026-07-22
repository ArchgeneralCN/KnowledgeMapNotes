import json
import re
import time
from dotenv import load_dotenv
import os

load_dotenv()  # 默认会加载根目录下的.env文件
model = os.getenv("MODEL_NAME")
temperature  =  float(os.getenv("TEMPERATURE"))
prompt_vision = os.getenv("PROMPTVISION")
class OpenaiAgent:
    def __init__(self, client):
        # 大模型
        self.client = client
        self.rag_client = client

    def temp_sleep(self, seconds=0.1):
        time.sleep(seconds)

    def agent_safe_generate_response(self, prompt, input_parameter, repeat=3):
        for i in range(repeat):
            try:
                curr_gpt_response = self.agent_request(prompt, input_parameter)
                x = ""
                if 'json' in curr_gpt_response:
                    pattern = r"```json\s*({.*?})\s*```"
                    match = re.search(pattern, curr_gpt_response, re.DOTALL)
                    if match:
                        json_content = match.group(1)
                        x = json.loads(json_content)
                    else:
                        print("未找到匹配的 JSON 内容")
                        continue
                return x
            except:
                print("ERROR")
        return -1

    def agent_request(self, prompt, input_parameter):
        self.temp_sleep()
        response = self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": prompt},
                {'role': 'user', 'content': input_parameter}],
            temperature=temperature,
            extra_body={"thinking": {"type": "disabled"}},

        )
        output = response.choices[0].message.content
        return output

    def agent_safe_generate_response_rag(self, prompt, input_parameter, messages, stream, repeat=3):
        for i in range(repeat):
            try:
                if stream:
                    # 流式输出需要特殊处理
                    response_content = ""
                    response_stream = self.agent_request_rag_stream(prompt, input_parameter, messages)
                    for chunk in response_stream:
                        if hasattr(chunk.choices[0].delta, 'content') and chunk.choices[0].delta.content is not None:
                            response_content += chunk.choices[0].delta.content

                    # 构建类似非流式输出的结构
                    if 'json' in response_content:
                        pattern = r"```json\s*({.*?})\s*```"
                        match = re.search(pattern, response_content, re.DOTALL)
                        if match:
                            json_content = match.group(1)
                            try:
                                return json.loads(json_content)
                            except json.JSONDecodeError:
                                print(f"JSON解析错误: {json_content}")
                                continue
                        else:
                            print("未找到匹配的 JSON 内容")
                            print(f"原始内容: {response_content[:100]}...")

                    # 如果没有JSON格式，尝试解析普通文本
                    # 尝试从文本中提取答案和参考资料
                    answer = response_content
                    material = ""

                    # 尝试寻找参考资料部分
                    material_match = re.search(r"参考资料[：:]([\s\S]+)$", response_content)
                    if material_match:
                        material = material_match.group(1).strip()
                        # 从答案中移除参考资料部分
                        answer = response_content[:material_match.start()].strip()

                    return {"answer": answer, "material": material}
                else:
                    # 非流式输出处理方式不变
                    curr_gpt_response = self.agent_request_rag(prompt, input_parameter, messages, stream)
                    x = ""
                    if 'json' in curr_gpt_response:
                        pattern = r"```json\s*({.*?})\s*```"
                        match = re.search(pattern, curr_gpt_response, re.DOTALL)
                        if match:
                            json_content = match.group(1)
                            try:
                                x = json.loads(json_content)
                            except json.JSONDecodeError:
                                print(f"JSON解析错误: {json_content}")
                                continue
                        else:
                            print("未找到匹配的 JSON 内容")
                            continue
                    else:
                        # 如果没有JSON格式，尝试解析普通文本
                        # 尝试从文本中提取答案和参考资料
                        answer = curr_gpt_response
                        material = ""

                        # 尝试寻找参考资料部分
                        material_match = re.search(r"参考资料[：:]([\s\S]+)$", curr_gpt_response)
                        if material_match:
                            material = material_match.group(1).strip()
                            # 从答案中移除参考资料部分
                            answer = curr_gpt_response[:material_match.start()].strip()

                        x = {"answer": answer, "material": material}
                    return x
            except Exception as e:
                print(f"ERROR: {str(e)}")
                import traceback
                traceback.print_exc()
        return -1

    def agent_request_rag_stream(self, prompt, input_parameter, messages):
        """流式请求方法"""
        # 确保消息格式正确
        formatted_messages = [{"role": "system", "content": prompt}]
        if messages:
            formatted_messages.extend(messages)
        formatted_messages.append({'role': 'user', 'content': input_parameter})
        response = self.rag_client.chat.completions.create(
            model=model,
            messages=formatted_messages,
            temperature=temperature,
            stream=True,
            extra_body={"thinking": {"type": "disabled"}}
        )
        return response

    def agent_request_rag(self, prompt, input_parameter, messages, stream):
        """非流式请求方法"""
        # 确保消息格式正确
        formatted_messages = [{"role": "system", "content": prompt}]
        if messages:
            formatted_messages.extend(messages)
        formatted_messages.append({'role': 'user', 'content': input_parameter})

        response = self.rag_client.chat.completions.create(
            model=model,
            messages=formatted_messages,
            temperature=temperature,
            stream=False,
            extra_body={"thinking": {"type": "disabled"}}
        )
        output = response.choices[0].message.content
        return output

    def hybrid_rag(self, query, graph, vectors, messages, stream=False):
        prompt = open(f"./prompt/{prompt_vision}/rag_v1_hybrid.txt", encoding='utf-8').read()
        input_parameter = open(f"./prompt/{prompt_vision}/rag_v1_query_hy.txt", encoding='utf-8').read()
        graph_relation = "\n".join(graph)
        context = "\n".join(vectors)
        input_parameter = input_parameter.replace("{{query}}", query)
        input_parameter = input_parameter.replace("{{relation}}", graph_relation)
        input_parameter = input_parameter.replace("{{context}}", context)

        # 确保 messages 是列表且格式正确
        if not isinstance(messages, list):
            messages = []
        if messages and isinstance(messages[0], dict):
            messages = [{"role": msg.get("role", ""), "content": msg.get("content", "")} for msg in messages]

        output = self.agent_safe_generate_response_rag(prompt, input_parameter, messages, stream)
        return output

    def hybrid_rag_stream(self, query, graph, vectors, messages):
        """
        处理混合RAG请求并以流式方式返回响应流
        参数与hybrid_rag保持一致，但直接返回流对象以供迭代
        """
        # 构建提示和输入参数
        prompt = open(f"./prompt/{prompt_vision}/rag_v1_hybrid.txt", encoding='utf-8').read()
        input_parameter = open(f"./prompt/{prompt_vision}/rag_v1_query_hy.txt", encoding='utf-8').read()
        graph_relation = "\n".join(graph)
        context = "\n".join(vectors)
        input_parameter = input_parameter.replace("{{query}}", query)
        input_parameter = input_parameter.replace("{{relation}}", graph_relation)
        input_parameter = input_parameter.replace("{{context}}", context)

        # 确保 messages 是列表且格式正确
        if not isinstance(messages, list):
            messages = []
        if messages and isinstance(messages[0], dict):
            messages = [{"role": msg.get("role", ""), "content": msg.get("content", "")} for msg in messages]

        # 直接返回流对象，不进行封装处理
        return self.agent_request_rag_stream(prompt, input_parameter, messages)

    def process_hybrid_rag_stream_chunk(self, chunk):
        """
        处理流式响应的单个块，返回格式化的内容
        便于上层应用统一处理
        """
        if hasattr(chunk.choices[0].delta, 'content') and chunk.choices[0].delta.content is not None:
            return chunk.choices[0].delta.content
        return ""

    def extract_material_from_text(self, text):
        """
        从文本中提取答案和参考资料部分
        返回 (answer, material) 元组
        """
        material_match = re.search(r"参考资料[：:]([\s\S]+)$", text)
        if material_match:
            material = material_match.group(1).strip()
            answer = text[:material_match.start()].strip()
            return answer, material
        return text, ""