import unittest
from types import SimpleNamespace

from LLM.Openai_Agent import (
    AIResponseFormatError,
    AIResponseTruncatedError,
    OpenaiAgent,
)


class OpenaiAgentJsonParsingTests(unittest.TestCase):
    def test_parses_raw_json_object(self):
        response = '{"entities":[["计算机科学","学科"]]}'

        parsed = OpenaiAgent._parse_json_response(response)

        self.assertEqual(parsed["entities"][0], ["计算机科学", "学科"])

    def test_parses_json_code_fence(self):
        response = '```json\n{"relations": []}\n```'

        parsed = OpenaiAgent._parse_json_response(response)

        self.assertEqual(parsed, {"relations": []})

    def test_parses_json_surrounded_by_explanation(self):
        response = '处理结果如下：\n{"entities": []}\n请查收。'

        parsed = OpenaiAgent._parse_json_response(response)

        self.assertEqual(parsed, {"entities": []})

    def test_extracts_raw_json_chat_completion(self):
        response = (
            '{"choices":[{"finish_reason":"stop","message":'
            '{"content":"{\\"entities\\": []}"}}]}'
        )

        content, finish_reason = OpenaiAgent._extract_chat_completion(response)

        self.assertEqual(content, '{"entities": []}')
        self.assertEqual(finish_reason, "stop")

    def test_rejects_html_chat_completion_with_base_url_hint(self):
        with self.assertRaisesRegex(AIResponseFormatError, "/v1"):
            OpenaiAgent._extract_chat_completion("<!doctype html><title>New API</title>")

    def test_extracts_mapping_and_stream_content(self):
        response = {
            "choices": [{"message": {"content": "答案"}, "finish_reason": "stop"}]
        }
        self.assertEqual(OpenaiAgent._extract_chat_completion(response)[0], "答案")
        self.assertEqual(
            OpenaiAgent._extract_stream_content(
                'data: {"choices":[{"delta":{"content":"流"}}]}'
            ),
            "流",
        )

    def test_safe_generate_accepts_raw_json(self):
        agent = object.__new__(OpenaiAgent)
        agent.agent_request = lambda _prompt, _input: '{"entities": []}'

        parsed = agent.agent_safe_generate_response("prompt", "input", repeat=1)

        self.assertEqual(parsed, {"entities": []})

    def test_primary_failure_uses_fallback_ai(self):
        class Completions:
            def __init__(self, response=None, error=None):
                self.response = response
                self.error = error
                self.calls = 0

            def create(self, **_kwargs):
                self.calls += 1
                if self.error:
                    raise self.error
                return SimpleNamespace(
                    choices=[SimpleNamespace(
                        message=SimpleNamespace(content=self.response)
                    )]
                )

        primary_completions = Completions(error=ConnectionError("主 API 断开"))
        fallback_completions = Completions(response='{"entities": [["备用", "服务"]]}')
        primary = SimpleNamespace(
            chat=SimpleNamespace(completions=primary_completions)
        )
        fallback = SimpleNamespace(
            chat=SimpleNamespace(completions=fallback_completions)
        )
        agent = OpenaiAgent(
            primary,
            model_name="primary-model",
            fallback_client=fallback,
            fallback_model_name="fallback-model",
        )
        agent.temp_sleep = lambda *_args: None

        parsed = agent.agent_safe_generate_response("prompt", "input", repeat=2)

        self.assertEqual(parsed["entities"][0], ["备用", "服务"])
        self.assertEqual(primary_completions.calls, 1)
        self.assertEqual(fallback_completions.calls, 1)

    def test_invalid_primary_json_uses_fallback_ai(self):
        responses = iter(["not-json", '{"relations": []}'])
        agent = object.__new__(OpenaiAgent)
        agent.fallback_client = object()
        agent.fallback_model_name = "fallback-model"
        agent.agent_request = lambda *_args, **_kwargs: next(responses)

        parsed = agent.agent_safe_generate_response("prompt", "input", repeat=1)

        self.assertEqual(parsed, {"relations": []})

    def test_missing_required_field_uses_fallback_ai(self):
        responses = iter(['{"unexpected": []}', '{"entities": []}'])
        agent = object.__new__(OpenaiAgent)
        agent.fallback_client = object()
        agent.fallback_model_name = "fallback-model"
        agent.agent_request = lambda *_args, **_kwargs: next(responses)

        parsed = agent.agent_safe_generate_response(
            "prompt",
            "input",
            repeat=1,
            expected_key="entities",
        )

        self.assertEqual(parsed, {"entities": []})

    def test_agent_request_detects_truncated_response(self):
        class Completions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                return SimpleNamespace(choices=[SimpleNamespace(
                    finish_reason="length",
                    message=SimpleNamespace(content='{"relations": [{"source":'),
                )])

        completions = Completions()
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        agent = OpenaiAgent(
            client,
            model_name="test-model",
            max_output_tokens=6000,
        )
        agent.temp_sleep = lambda *_args: None

        with self.assertRaises(AIResponseTruncatedError):
            agent.agent_request("prompt", "input")

        self.assertEqual(completions.kwargs["max_tokens"], 6000)

    def test_structured_request_can_consume_streaming_json(self):
        class Completions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                return iter([
                    SimpleNamespace(choices=[SimpleNamespace(
                        delta=SimpleNamespace(content='{"entities": ['),
                        finish_reason=None,
                    )]),
                    SimpleNamespace(choices=[SimpleNamespace(
                        delta=SimpleNamespace(content='] }'),
                        finish_reason="stop",
                    )]),
                ])

        completions = Completions()
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        agent = OpenaiAgent(client, model_name="stream-model", stream=True)
        agent.temp_sleep = lambda *_args: None

        parsed = agent.agent_safe_generate_response(
            "prompt", "input", repeat=1, expected_key="entities"
        )

        self.assertEqual(parsed, {"entities": []})
        self.assertTrue(completions.kwargs["stream"])

    def test_streaming_request_preserves_truncation_detection(self):
        class Completions:
            def create(self, **_kwargs):
                return iter([
                    'data: {"choices":[{"delta":{"content":"{\\"relations\\":["},"finish_reason":null}]}',
                    'data: {"choices":[{"delta":{"content":"{"},"finish_reason":"length"}]}',
                ])

        client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
        agent = OpenaiAgent(client, model_name="stream-model", stream=True)
        agent.temp_sleep = lambda *_args: None

        with self.assertRaises(AIResponseTruncatedError):
            agent.agent_request("prompt", "input")

    def test_fallback_has_independent_stream_setting(self):
        class PrimaryCompletions:
            def create(self, **_kwargs):
                raise ConnectionError("primary unavailable")

        class FallbackCompletions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                return iter([
                    SimpleNamespace(choices=[SimpleNamespace(
                        delta=SimpleNamespace(content='{"entities": []}'),
                        finish_reason="stop",
                    )]),
                ])

        fallback_completions = FallbackCompletions()
        primary = SimpleNamespace(chat=SimpleNamespace(completions=PrimaryCompletions()))
        fallback = SimpleNamespace(chat=SimpleNamespace(completions=fallback_completions))
        agent = OpenaiAgent(
            primary,
            model_name="primary",
            stream=False,
            fallback_client=fallback,
            fallback_model_name="fallback",
            fallback_stream=True,
        )
        agent.temp_sleep = lambda *_args: None

        parsed = agent.agent_safe_generate_response("prompt", "input", repeat=1)

        self.assertEqual(parsed, {"entities": []})
        self.assertTrue(fallback_completions.kwargs["stream"])

    def test_safe_generate_can_propagate_invalid_json(self):
        agent = object.__new__(OpenaiAgent)
        agent.agent_request = lambda _prompt, _input: '{"relations": [{"source":'

        with self.assertRaises(AIResponseFormatError):
            agent.agent_safe_generate_response(
                "prompt",
                "input",
                repeat=1,
                expected_key="relations",
                raise_on_failure=True,
            )

    def test_truncation_is_preserved_when_fallback_has_network_error(self):
        errors = iter([
            AIResponseTruncatedError("primary output truncated"),
            ConnectionError("fallback disconnected"),
        ])
        agent = object.__new__(OpenaiAgent)
        agent.fallback_client = object()
        agent.fallback_model_name = "fallback-model"

        def fail_request(*_args, **_kwargs):
            raise next(errors)

        agent.agent_request = fail_request

        with self.assertRaises(AIResponseTruncatedError):
            agent.agent_safe_generate_response(
                "prompt",
                "input",
                repeat=1,
                expected_key="relations",
                raise_on_failure=True,
            )

    def test_rag_truncation_recovers_completed_answer_and_sets_output_limit(self):
        class Completions:
            def __init__(self):
                self.calls = 0
                self.kwargs = None

            def create(self, **kwargs):
                self.calls += 1
                self.kwargs = kwargs
                return SimpleNamespace(choices=[SimpleNamespace(
                    finish_reason="length",
                    message=SimpleNamespace(
                        content='{"answer":["已完整生成的答案"],"material":["未完成的引用'
                    )
                )])

        completions = Completions()
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        agent = OpenaiAgent(client, model_name="rag-model", max_output_tokens=2048)
        agent.temp_sleep = lambda *_args: None

        result = agent.agent_safe_generate_response_rag(
            "prompt", "input", [], stream=False, repeat=1
        )

        self.assertEqual(result["answer"], "已完整生成的答案")
        self.assertEqual(completions.kwargs["max_tokens"], 2048)
        self.assertEqual(completions.calls, 1)


if __name__ == "__main__":
    unittest.main()
