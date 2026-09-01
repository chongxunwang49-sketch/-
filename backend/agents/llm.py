"""
统一 LLM 调用层(步骤8)

模型可插拔设计:LLM_PROVIDER 决定走哪个后端,一行 .env 配置切换。
  - ollama   :本地 Ollama(默认,离线保底),走 LangChain ChatOllama
  - deepseek :DeepSeek 官方 API(质量高),走 LangChain ChatOpenAI(兼容 OpenAI 协议)
  - dify     :用户在 dify 平台搭建的智能体应用(作为 Agent 的 LLM 后端),
              走 dify /v1/workflows/run HTTP 接口;需用户提供 app_id/api_key

统一对外接口:
  - complete(system_prompt, user_prompt, ...)   -> str  同步完整回复
  - complete_dify(inputs: dict)                 -> dict dify 工作流专用(workflow 输出)
  - stream_complete(...)                        -> Iterator[str] 流式(报告 Agent 用)

所有调用带超时(防卡死)+ tenacity 指数退避重试 + token 统计(供步骤16日志)。
"""
import json
import logging
import os
import re
import time
from typing import Dict, Iterator, Optional

from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential

load_dotenv()

# 本地服务请求绝不允许被系统代理接管(否则 127.0.0.1:11434 会被代理拦成 502)
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1,0.0.0.0")
os.environ.setdefault("no_proxy", "localhost,127.0.0.1,0.0.0.0")

logger = logging.getLogger(__name__)

PROVIDER_OLLAMA = "ollama"
PROVIDER_DEEPSEEK = "deepseek"
PROVIDER_DIFY = "dify"


class LLMError(RuntimeError):
    """LLM 调用相关错误(超时/网络/后端不可用)"""


def _retry_decorator():
    """统一重试策略:指数退避,最多 3 次,仅重试网络/超时类异常"""
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, max=8),
        reraise=True,
    )


def extract_json(text: str) -> dict:
    """
    从 LLM 回复里稳健地提取 JSON。
    LLM 可能输出前后带解释或代码块标记,这里先剥代码块,再取第一个 {..} 平衡括号。
    """
    text = re.sub(r"```(?:json)?", "", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise LLMError(f"LLM 输出中未找到 JSON 对象: {text[:200]}")
    return json.loads(text[start:end + 1])


class LLMClient:
    """统一 LLM 客户端,按 provider 选择后端"""

    def __init__(self, provider: Optional[str] = None, timeout: Optional[int] = None):
        self.provider = (provider or os.getenv("LLM_PROVIDER", "ollama")).lower()
        self.timeout = timeout or int(os.getenv("LLM_TIMEOUT", "180"))
        if self.provider == PROVIDER_OLLAMA:
            self._init_ollama()
        elif self.provider == PROVIDER_DEEPSEEK:
            self._init_deepseek()
        elif self.provider == PROVIDER_DIFY:
            self._init_dify()
        else:
            raise LLMError(f"未知的 LLM_PROVIDER: {self.provider}")
        logger.info("LLMClient 就绪: provider=%s, timeout=%ds", self.provider, self.timeout)

    # ---------------- 各 provider 初始化 ----------------
    def _init_ollama(self):
        from langchain_ollama import ChatOllama
        self._llm = ChatOllama(
            model=os.getenv("OLLAMA_MODEL", "qwen2.5:3b"),
            base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            temperature=0.7,
            timeout=self.timeout,
        )

    def _init_deepseek(self):
        from langchain_openai import ChatOpenAI  # DeepSeek 兼容 OpenAI 协议
        api_key = os.getenv("DEEPSEEK_API_KEY", "")
        if not api_key:
            raise LLMError("LLM_PROVIDER=deepseek 但未配置 DEEPSEEK_API_KEY(.env)")
        self._llm = ChatOpenAI(
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            api_key=api_key,
            temperature=0.7,
            timeout=self.timeout,
        )

    def _init_dify(self):
        # dify 作为 provider:实际调用走 backend.services.dify.call_workflow(按角色选 app)
        # 4 组角色 app 配置见 .env 的 DIFY_{ROLE}_APP_ID / DIFY_{ROLE}_API_KEY
        self.dify_base = os.getenv("DIFY_BASE_URL", "http://localhost/v1")

    # ---------------- 核心调用 ----------------
    @_retry_decorator()
    def complete(self, system_prompt: str, user_prompt: str, temperature: float = 0.7,
                 json_mode: bool = False) -> str:
        """同步完整回复。json_mode 提示模型输出 JSON(仅提示,仍靠 extract_json 兜底)"""
        start = time.perf_counter()
        if self.provider in (PROVIDER_OLLAMA, PROVIDER_DEEPSEEK):
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            kwargs = {}
            if json_mode and self.provider == PROVIDER_DEEPSEEK:
                kwargs["response_format"] = {"type": "json_object"}  # DeepSeek 原生支持
            resp = self._llm.invoke(messages, **kwargs)
            text = resp.content if isinstance(resp.content, str) else str(resp.content)
            usage = getattr(resp, "usage_metadata", None)
            tokens = _usage_to_tokens(usage)
            _log_usage(self.provider, tokens, time.perf_counter() - start)
            return text.strip()
        # dify:通过 workflow 调用(见 complete_dify)
        raise LLMError("dify provider 请使用 complete_dify(inputs)")

    def complete_dify(self, inputs: dict, user: str = "stock-agent") -> dict:
        """调用 dify 工作流(blocking),返回其 outputs 字典。"""
        if self.provider != PROVIDER_DIFY:
            raise LLMError("complete_dify 仅用于 dify provider")
        url = f"{self.dify_base}/workflows/run"
        headers = {
            "Authorization": f"Bearer {self.dify_api_key}",
            "X-App-Id": self.dify_app_id,
            "Content-Type": "application/json",
        }
        payload = {"inputs": inputs, "response_mode": "blocking", "user": user}
        start = time.perf_counter()
        try:
            resp = self._httpx.post(url, headers=headers, json=payload, timeout=self.timeout)
        except Exception as e:
            raise LLMError(f"dify 请求失败: {e}") from e
        if resp.status_code != 200:
            raise LLMError(f"dify 返回 {resp.status_code}: {resp.text[:200]}")
        outputs = resp.json().get("data", {}).get("outputs", {})
        _log_usage(self.provider, {}, time.perf_counter() - start)
        return outputs

    def stream_complete(self, system_prompt: str, user_prompt: str) -> Iterator[str]:
        """流式回复(报告生成用,逐 token 吐出,前端可实时展示)。仅 ollama/deepseek。"""
        if self.provider not in (PROVIDER_OLLAMA, PROVIDER_DEEPSEEK):
            yield self.complete(system_prompt, user_prompt)
            return
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        for chunk in self._llm.stream(messages):
            piece = chunk.content
            if piece:
                yield piece


def _usage_to_tokens(usage) -> dict:
    """把 LangChain 的 usage_metadata 转成 {prompt, completion, total}"""
    if not usage:
        return {}
    return {
        "prompt_tokens": usage.get("input_tokens", 0),
        "completion_tokens": usage.get("output_tokens", 0),
        "total_tokens": (usage.get("input_tokens", 0) + usage.get("output_tokens", 0)),
    }


def _log_usage(provider: str, tokens: dict, elapsed: float) -> None:
    """结构化日志:token 消耗与耗时(步骤16可观测性埋点)"""
    if tokens:
        logger.info("LLM[%s] 耗时 %.2fs, token: %s", provider, elapsed, tokens)
    else:
        logger.info("LLM[%s] 耗时 %.2fs(无 token 统计)", provider, elapsed)
