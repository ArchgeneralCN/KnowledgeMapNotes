import json
import logging
import re
import time
from dotenv import load_dotenv
import os
from threading import Lock

load_dotenv()  # 默认会加载根目录下的.env文件
prompt_vision = os.getenv("PROMPTVISION")
logger = logging.getLogger("AI 请求服务")


class AIResponseError(RuntimeError):
    """Base error for a response that cannot be consumed safely."""


class AIResponseTruncatedError(AIResponseError):
    """Raised when the provider reports that the output token limit was hit."""


class AIResponseFormatError(AIResponseError):
    """Raised when every provider attempt returned an unusable JSON payload."""


class OpenaiAgent:
    def __init__(
        self,
        client,
        model_name=None,
        temperature=None,
        enable_thinking=False,
        fallback_client=None,
        fallback_model_name=None,
        max_output_tokens=None,
        max_output_parameter=None,
    ):
        self._config_lock = Lock()
        self.max_output_tokens = self._positive_int(
            max_output_tokens
            if max_output_tokens is not None
            else os.getenv("AI_MAX_OUTPUT_TOKENS", "8192"),
            default=8192,
        )
        configured_output_parameter = (
            max_output_parameter
            or os.getenv("AI_MAX_OUTPUT_PARAMETER", "max_tokens")
        ).strip()
        self.max_output_parameter = (
            configured_output_parameter
            if configured_output_parameter in {"max_tokens", "max_completion_tokens"}
            else "max_tokens"
        )
        self.configure(
            client=client,
            model_name=model_name or os.getenv("MODEL_NAME", ""),
            temperature=(
                temperature
                if temperature is not None
                else float(os.getenv("TEMPERATURE", "0"))
            ),
            enable_thinking=enable_thinking,
            fallback_client=fallback_client,
            fallback_model_name=fallback_model_name,
        )

    def configure(
        self,
        client,
        model_name,
        temperature,
        enable_thinking,
        fallback_client=None,
        fallback_model_name=None,
    ):
        """Atomically replace the client and request options used by new calls."""
        with self._config_lock:
            self.client = client
            self.rag_client = client
            self.fallback_client = fallback_client
            self.fallback_rag_client = fallback_client
            self.model_name = model_name
            self.fallback_model_name = fallback_model_name or model_name
            self.temperature = temperature
            self.enable_thinking = enable_thinking

    def _request_config(self, rag=False, fallback=False):
        with self._config_lock:
            if fallback:
                client = self.fallback_rag_client if rag else self.fallback_client
                model_name = self.fallback_model_name
            else:
                client = self.rag_client if rag else self.client
                model_name = self.model_name
            return (
                client,
                model_name,
                self.temperature,
                self.enable_thinking,
            )

    def _has_fallback(self):
        """Return whether a separately configured backup provider is available."""
        lock = getattr(self, "_config_lock", None)
        if lock is None:
            return bool(getattr(self, "fallback_client", None))
        with lock:
            return bool(self.fallback_client and self.fallback_model_name)

    def _request_attempts(self, repeat):
        """Try the primary once, then let the backup finish the request retries."""
        if self._has_fallback():
            return [False] + [True] * max(1, repeat)
        return [False] * max(1, repeat)

    @staticmethod
    def _thinking_options(enable_thinking):
        return {
            "thinking": {
                "type": "enabled" if enable_thinking else "disabled"
            }
        }

    def temp_sleep(self, seconds=0.1):
        time.sleep(seconds)

    @staticmethod
    def _positive_int(value, default):
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    @staticmethod
    def _parse_json_response(response):
        """Parse model JSON returned raw, fenced, or surrounded by prose."""
        if isinstance(response, (dict, list)):
            return response
        if not isinstance(response, str) or not response.strip():
            raise ValueError("模型返回内容为空或不是文本")

        text = response.strip()
        fenced_match = re.search(
            r"```(?:json)?\s*([\s\S]*?)\s*```",
            text,
            flags=re.IGNORECASE,
        )
        candidates = [fenced_match.group(1).strip()] if fenced_match else []
        candidates.append(text)

        decoder = json.JSONDecoder()
        last_error = None
        for candidate in candidates:
            try:
                return json.loads(candidate)
            except (json.JSONDecodeError, TypeError) as exc:
                last_error = exc

            starts = [
                position
                for marker in ("{", "[")
                if (position := candidate.find(marker)) >= 0
            ]
            if starts:
                try:
                    parsed, _ = decoder.raw_decode(candidate[min(starts):])
                    return parsed
                except json.JSONDecodeError as exc:
                    last_error = exc

        raise ValueError("未找到有效的 JSON 内容") from last_error

    def agent_safe_generate_response(
        self,
        prompt,
        input_parameter,
        repeat=3,
        expected_key=None,
        raise_on_failure=False,
    ):
        last_error = None
        last_response_error = None
        for use_fallback in self._request_attempts(repeat):
            try:
                if use_fallback:
                    curr_gpt_response = self.agent_request(
                        prompt,
                        input_parameter,
                        fallback=True,
                    )
                else:
                    curr_gpt_response = self.agent_request(prompt, input_parameter)
                logger.debug("AI JSON 响应长度: %d", len(curr_gpt_response))
                try:
                    parsed = self._parse_json_response(curr_gpt_response)
                except (TypeError, ValueError) as exc:
                    raise AIResponseFormatError(str(exc)) from exc
                if not isinstance(parsed, dict):
                    raise AIResponseFormatError("模型返回的 JSON 顶层必须是对象")
                if expected_key and expected_key not in parsed:
                    raise AIResponseFormatError(f"模型返回缺少字段: {expected_key}")
                return parsed
            except Exception as exc:
                last_error = exc
                if isinstance(exc, AIResponseError):
                    last_response_error = exc
                provider = "备用 AI" if use_fallback else "主 AI"
                logger.warning("%s JSON 响应解析或请求失败: %s", provider, exc)
        if raise_on_failure:
            if last_response_error is not None:
                raise last_response_error
            if last_error is not None:
                raise last_error
        return -1

    def agent_request(self, prompt, input_parameter, fallback=False):
        self.temp_sleep()
        client, model_name, temperature, enable_thinking = self._request_config(
            fallback=fallback
        )
        if client is None:
            raise RuntimeError("未配置可用的 AI 客户端")
        request_options = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": input_parameter},
            ],
            "temperature": temperature,
            "extra_body": self._thinking_options(enable_thinking),
            self.max_output_parameter: self.max_output_tokens,
        }
        response = client.chat.completions.create(**request_options)
        if not response.choices:
            raise AIResponseFormatError("AI 返回中没有 choices")
        choice = response.choices[0]
        output = choice.message.content or ""
        finish_reason = getattr(choice, "finish_reason", None)
        logger.info(
            "AI 响应完成: provider=%s model=%s finish_reason=%s chars=%d",
            "备用 AI" if fallback else "主 AI",
            model_name,
            finish_reason,
            len(output),
        )
        if finish_reason in {"length", "max_tokens"}:
            raise AIResponseTruncatedError(
                f"AI 输出达到 token 上限（finish_reason={finish_reason}，"
                f"已返回 {len(output)} 字符）"
            )
        if not output.strip():
            raise AIResponseFormatError(
                f"AI 返回内容为空（finish_reason={finish_reason}）"
            )
        return output

    def agent_safe_generate_response_rag(self, prompt, input_parameter, messages, stream, repeat=3):
        for use_fallback in self._request_attempts(repeat):
            try:
                if stream:
                    # 流式输出需要特殊处理
                    response_content = ""
                    response_stream = self.agent_request_rag_stream(
                        prompt,
                        input_parameter,
                        messages,
                        fallback=use_fallback,
                    )
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
                    curr_gpt_response = self.agent_request_rag(
                        prompt,
                        input_parameter,
                        messages,
                        stream,
                        fallback=use_fallback,
                    )
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
                provider = "备用 AI" if use_fallback else "主 AI"
                print(f"{provider} ERROR: {str(e)}")
                import traceback
                traceback.print_exc()
        return -1

    def agent_request_rag_stream(self, prompt, input_parameter, messages, fallback=False):
        """流式请求方法"""
        # 确保消息格式正确
        formatted_messages = [{"role": "system", "content": prompt}]
        if messages:
            formatted_messages.extend(messages)
        formatted_messages.append({'role': 'user', 'content': input_parameter})
        client, model_name, temperature, enable_thinking = self._request_config(
            rag=True,
            fallback=fallback,
        )
        if client is None:
            raise RuntimeError("未配置可用的 AI 客户端")
        response = client.chat.completions.create(
            model=model_name,
            messages=formatted_messages,
            temperature=temperature,
            stream=True,
            extra_body=self._thinking_options(enable_thinking)
        )
        return response

    def agent_request_rag(self, prompt, input_parameter, messages, stream, fallback=False):
        """非流式请求方法"""
        # 确保消息格式正确
        formatted_messages = [{"role": "system", "content": prompt}]
        if messages:
            formatted_messages.extend(messages)
        formatted_messages.append({'role': 'user', 'content': input_parameter})

        client, model_name, temperature, enable_thinking = self._request_config(
            rag=True,
            fallback=fallback,
        )
        if client is None:
            raise RuntimeError("未配置可用的 AI 客户端")
        response = client.chat.completions.create(
            model=model_name,
            messages=formatted_messages,
            temperature=temperature,
            stream=False,
            extra_body=self._thinking_options(enable_thinking)
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
        try:
            return self.agent_request_rag_stream(prompt, input_parameter, messages)
        except Exception:
            if not self._has_fallback():
                raise
            return self.agent_request_rag_stream(
                prompt,
                input_parameter,
                messages,
                fallback=True,
            )

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
