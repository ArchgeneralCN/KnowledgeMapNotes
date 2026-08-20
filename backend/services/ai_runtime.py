"""Runtime AI configuration and its HTTP endpoints.

The application supports OpenAI-compatible primary and fallback services. This
module owns the mutable clients and settings so ``main.py`` only wires agents to
the runtime instead of implementing connection management and HTTP handlers.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from threading import Lock
from typing import Any, Optional, Protocol

from fastapi import APIRouter, HTTPException
from openai import OpenAI
from pydantic import BaseModel, Field

from LLM.Openai_Agent import OpenaiAgent


class ConfigurableAgent(Protocol):
    """Minimal agent interface needed when applying new runtime settings."""

    def configure(self, client: Optional[OpenAI], **settings: Any) -> None: ...


class AISettingsUpdate(BaseModel):
    """Runtime settings for the primary and optional fallback text models."""

    base_url: str
    api_key: Optional[str] = None
    model_name: str
    temperature: float = Field(ge=0, le=2)
    enable_thinking: bool = False
    stream: bool = False
    fallback_enabled: bool = False
    fallback_base_url: Optional[str] = None
    fallback_api_key: Optional[str] = None
    fallback_model_name: Optional[str] = None
    fallback_stream: bool = False


class AIModelsRequest(BaseModel):
    """Connection details used to discover models from a compatible API."""

    base_url: str
    api_key: Optional[str] = None


def parse_boolean(value: Optional[str], default: bool = False) -> bool:
    """Parse the boolean forms accepted by environment variables and forms."""
    if value is None:
        return default
    return value.strip().lower() in {"true", "1", "yes", "on", "enabled"}


def create_openai_client(api_key: str, base_url: str) -> Optional[OpenAI]:
    """Create a client only when both required connection values exist."""
    if not api_key or not base_url:
        return None
    return OpenAI(api_key=api_key, base_url=base_url)


def _environment_temperature() -> float:
    try:
        return min(2.0, max(0.0, float(os.getenv("TEMPERATURE", "0"))))
    except (TypeError, ValueError):
        return 0.0


class AIRuntime:
    """Own mutable model settings, clients, validation, and safe serialization."""

    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger
        self.lock = Lock()
        self.settings: dict[str, Any] = {
            "base_url": os.getenv("BASE_URL", "").strip(),
            "api_key": os.getenv("API_KEY", "").strip(),
            "model_name": os.getenv("MODEL_NAME", "").strip(),
            "temperature": _environment_temperature(),
            "enable_thinking": parse_boolean(os.getenv("ENABLE_THINKING")),
            "stream": parse_boolean(os.getenv("AI_STREAM")),
            "fallback_enabled": parse_boolean(os.getenv("FALLBACK_ENABLED")),
            "fallback_base_url": os.getenv("FALLBACK_BASE_URL", "").strip(),
            "fallback_api_key": os.getenv("FALLBACK_API_KEY", "").strip(),
            "fallback_model_name": os.getenv("FALLBACK_MODEL_NAME", "").strip(),
            "fallback_stream": parse_boolean(os.getenv("FALLBACK_STREAM")),
        }
        self.client = create_openai_client(
            self.settings["api_key"], self.settings["base_url"]
        )
        self.fallback_client = (
            create_openai_client(
                self.settings["fallback_api_key"],
                self.settings["fallback_base_url"],
            )
            if self.settings["fallback_enabled"]
            else None
        )

    @staticmethod
    def _mask_api_key(api_key: str) -> str:
        if not api_key:
            return ""
        if len(api_key) <= 7:
            return "****"
        return f"{api_key[:3]}...{api_key[-4:]}"

    def public_settings(self) -> dict[str, Any]:
        """Return settings suitable for the frontend without exposing secrets."""
        with self.lock:
            settings = self.settings.copy()
        return {
            "base_url": settings["base_url"],
            "model_name": settings["model_name"],
            "temperature": settings["temperature"],
            "enable_thinking": settings["enable_thinking"],
            "stream": settings["stream"],
            "api_key_configured": bool(settings["api_key"]),
            "api_key_hint": self._mask_api_key(settings["api_key"]),
            "fallback_enabled": settings["fallback_enabled"],
            "fallback_base_url": settings["fallback_base_url"],
            "fallback_model_name": settings["fallback_model_name"],
            "fallback_stream": settings["fallback_stream"],
            "fallback_api_key_configured": bool(settings["fallback_api_key"]),
            "fallback_api_key_hint": self._mask_api_key(settings["fallback_api_key"]),
        }

    def require_settings(self) -> None:
        """Reject model-dependent requests until one configured model is usable."""
        with self.lock:
            primary = self.client is not None and bool(self.settings["model_name"])
            fallback = (
                self.settings["fallback_enabled"]
                and self.fallback_client is not None
                and bool(self.settings["fallback_model_name"])
            )
        if not (primary or fallback):
            raise HTTPException(status_code=503, detail="请先在前端完成 AI 配置")

    @staticmethod
    def _validation_completion(client: OpenAI, settings: dict[str, Any]) -> None:
        """Send the smallest useful request and validate the response shape."""
        use_stream = bool(settings.get("stream"))
        response = client.with_options(timeout=20.0, max_retries=0).chat.completions.create(
            model=settings["model_name"],
            messages=[{"role": "user", "content": "Reply with OK."}],
            temperature=settings["temperature"],
            stream=use_stream,
            max_tokens=32,
            extra_body={
                "thinking": {
                    "type": "enabled" if settings["enable_thinking"] else "disabled"
                }
            },
        )
        if use_stream:
            content, _ = OpenaiAgent._consume_stream(response)
            if not content.strip():
                raise ValueError("AI 流式连接测试未返回内容")
        else:
            OpenaiAgent._extract_chat_completion(response)

    async def validate_current(self) -> None:
        """Validate active primary settings, then fallback settings if necessary."""
        self.require_settings()
        with self.lock:
            client = self.client
            fallback_client = self.fallback_client
            settings = self.settings.copy()

        primary_error: Optional[Exception] = None
        try:
            await asyncio.wait_for(
                asyncio.to_thread(self._validation_completion, client, settings),
                timeout=25.0,
            )
            return
        except Exception as exc:
            primary_error = exc
            self.logger.warning(
                "上传前 AI 配置校验失败: base_url=%s model=%s error=%s",
                settings["base_url"], settings["model_name"], exc,
            )

        if settings["fallback_enabled"] and fallback_client is not None:
            fallback_settings = {
                **settings,
                "base_url": settings["fallback_base_url"],
                "api_key": settings["fallback_api_key"],
                "model_name": settings["fallback_model_name"],
                "stream": settings["fallback_stream"],
            }
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(
                        self._validation_completion, fallback_client, fallback_settings
                    ),
                    timeout=25.0,
                )
                self.logger.info("主 AI 校验失败，备用 AI 可用，允许继续处理")
                return
            except Exception as exc:
                self.logger.warning("备用 AI 配置校验失败: %s", exc)
                raise HTTPException(
                    status_code=502,
                    detail=f"主 AI 和备用 AI 均不可用: {exc}",
                ) from exc

        raise HTTPException(
            status_code=502,
            detail=f"主 AI 不可用且未配置备用 AI: {primary_error}",
        ) from primary_error

    def prepare(
        self, update: AISettingsUpdate
    ) -> tuple[OpenAI, Optional[OpenAI], dict[str, Any]]:
        """Validate submitted settings and build clients without mutating state."""
        base_url = update.base_url.strip().rstrip("/")
        model_name = update.model_name.strip()
        fallback_base_url = (update.fallback_base_url or "").strip().rstrip("/")
        fallback_model_name = (update.fallback_model_name or "").strip()
        if not base_url.startswith(("http://", "https://")):
            raise HTTPException(status_code=422, detail="Base URL 必须以 http:// 或 https:// 开头")
        if not model_name:
            raise HTTPException(status_code=422, detail="模型名称不能为空")

        with self.lock:
            api_key = (update.api_key or "").strip() or self.settings["api_key"]
            fallback_api_key = (
                (update.fallback_api_key or "").strip()
                or self.settings["fallback_api_key"]
            )
        if not api_key:
            raise HTTPException(status_code=422, detail="API Key 不能为空")
        try:
            next_client = create_openai_client(api_key, base_url)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"AI 配置无效: {exc}") from exc
        if next_client is None:
            raise HTTPException(status_code=422, detail="Base URL 和 API Key 不能为空")

        next_fallback = None
        if update.fallback_enabled:
            if not fallback_base_url.startswith(("http://", "https://")):
                raise HTTPException(status_code=422, detail="备用 Base URL 必须以 http:// 或 https:// 开头")
            if not fallback_model_name:
                raise HTTPException(status_code=422, detail="备用模型名称不能为空")
            if not fallback_api_key:
                raise HTTPException(status_code=422, detail="备用 API Key 不能为空")
            try:
                next_fallback = create_openai_client(fallback_api_key, fallback_base_url)
            except Exception as exc:
                raise HTTPException(status_code=422, detail=f"备用 AI 配置无效: {exc}") from exc

        return next_client, next_fallback, {
            "base_url": base_url,
            "api_key": api_key,
            "model_name": model_name,
            "temperature": update.temperature,
            "enable_thinking": update.enable_thinking,
            "stream": update.stream,
            "fallback_enabled": update.fallback_enabled,
            "fallback_base_url": fallback_base_url,
            "fallback_api_key": fallback_api_key,
            "fallback_model_name": fallback_model_name,
            "fallback_stream": update.fallback_stream,
        }

    async def list_models(self, request: AIModelsRequest) -> dict[str, list[str]]:
        base_url = request.base_url.strip().rstrip("/")
        if not base_url.startswith(("http://", "https://")):
            raise HTTPException(status_code=422, detail="Base URL 必须以 http:// 或 https:// 开头")
        with self.lock:
            configured_key = (
                self.settings["api_key"] if base_url == self.settings["base_url"]
                else self.settings["fallback_api_key"]
                if base_url == self.settings["fallback_base_url"]
                else ""
            )
        api_key = (request.api_key or "").strip() or configured_key
        if not api_key:
            raise HTTPException(status_code=422, detail="获取模型列表需要 API Key")
        try:
            response = await asyncio.to_thread(
                lambda: create_openai_client(api_key, base_url)
                .with_options(timeout=15.0, max_retries=0)
                .models.list()
            )
        except Exception as exc:
            self.logger.warning("获取 AI 模型列表失败: base_url=%s error=%s", base_url, exc)
            raise HTTPException(status_code=502, detail=f"获取模型列表失败: {exc}") from exc
        raw_models = getattr(response, "data", None)
        if raw_models is None and isinstance(response, dict):
            raw_models = response.get("data")
        model_ids = sorted({
            str(
                getattr(item, "id", None)
                or (item.get("id") if isinstance(item, dict) else "")
            ).strip()
            for item in (raw_models or [])
        } - {""})
        return {"models": model_ids}

    async def test(self, update: AISettingsUpdate) -> dict[str, Any]:
        client, fallback_client, settings = self.prepare(update)
        started_at = time.monotonic()
        try:
            await asyncio.wait_for(
                asyncio.to_thread(self._validation_completion, client, settings),
                timeout=25.0,
            )
        except asyncio.TimeoutError as exc:
            raise HTTPException(status_code=504, detail="AI 连接测试超时，请检查服务地址或网络") from exc
        except Exception as exc:
            self.logger.warning(
                "AI 连接测试失败: base_url=%s model=%s error=%s",
                settings["base_url"], settings["model_name"], exc,
            )
            raise HTTPException(status_code=502, detail=f"AI 连接测试失败: {exc}") from exc

        if settings["fallback_enabled"] and fallback_client is not None:
            fallback_settings = {
                **settings,
                "base_url": settings["fallback_base_url"],
                "api_key": settings["fallback_api_key"],
                "model_name": settings["fallback_model_name"],
                "stream": settings["fallback_stream"],
            }
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(
                        self._validation_completion, fallback_client, fallback_settings
                    ),
                    timeout=25.0,
                )
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"备用 AI 连接测试失败: {exc}") from exc
        return {
            "message": "主 AI 和备用 AI 连接测试成功"
            if settings["fallback_enabled"] else "AI 连接测试成功",
            "latency_ms": round((time.monotonic() - started_at) * 1000),
        }

    def apply(
        self,
        update: AISettingsUpdate,
        agents: tuple[ConfigurableAgent, ...],
    ) -> dict[str, Any]:
        """Atomically apply submitted clients to every long-lived agent."""
        client, fallback_client, settings = self.prepare(update)
        with self.lock:
            for agent in agents:
                agent.configure(
                    client,
                    model_name=settings["model_name"],
                    temperature=settings["temperature"],
                    enable_thinking=settings["enable_thinking"],
                    stream=settings["stream"],
                    fallback_client=fallback_client,
                    fallback_model_name=settings["fallback_model_name"],
                    fallback_stream=settings["fallback_stream"],
                )
            self.client = client
            self.fallback_client = fallback_client
            self.settings.update(settings)
        self.logger.info(
            "AI 配置已更新: base_url=%s model=%s temperature=%s thinking=%s stream=%s fallback_stream=%s",
            settings["base_url"], settings["model_name"], settings["temperature"],
            settings["enable_thinking"], settings["stream"], settings["fallback_stream"],
        )
        return {"message": "AI 配置已更新", **self.public_settings()}


def create_ai_settings_router(
    runtime: AIRuntime,
    *agents: ConfigurableAgent,
) -> APIRouter:
    """Create AI settings endpoints bound to one application runtime."""
    router = APIRouter(tags=["AI settings"])

    @router.get("/ai-settings")
    async def get_ai_settings():
        return runtime.public_settings()

    @router.post("/ai-models")
    async def list_ai_models(request: AIModelsRequest):
        return await runtime.list_models(request)

    @router.post("/ai-settings/validate")
    async def validate_ai_settings():
        await runtime.validate_current()
        return {"message": "AI 配置校验成功"}

    @router.put("/ai-settings")
    async def update_ai_settings(update: AISettingsUpdate):
        return runtime.apply(update, tuple(agents))

    @router.post("/ai-settings/test")
    async def test_ai_settings(update: AISettingsUpdate):
        return await runtime.test(update)

    return router
