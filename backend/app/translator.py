from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from mistralai.client import Mistral

from app.languages import language_name
from app.schemas import LanguageCode


@dataclass
class TranslationContext:
    """维护少量上下文，让翻译不是逐字孤立处理。"""

    source_language: LanguageCode
    target_language: LanguageCode
    history: list[tuple[str, str]] = field(default_factory=list)

    def remember(self, source: str, translated: str) -> None:
        """保存最近几轮定稿字幕，控制上下文长度和成本。"""

        if source.strip() and translated.strip():
            self.history.append((source.strip(), translated.strip()))
            self.history = self.history[-6:]

    def build_prompt(self, text: str, is_final: bool) -> str:
        """生成翻译提示词，明确要求允许流式增量但保留语境。"""

        source_name = language_name(self.source_language)
        target_name = language_name(self.target_language)
        history_lines = "\n".join(
            f"- 原文: {src}\n  译文: {dst}" for src, dst in self.history
        )
        stability_rule = (
            "这是最终片段，请输出自然完整译文。"
            if is_final
            else "这是实时增量片段，请基于已有上下文给出当前最可能的自然译文，后续内容可能会修正。"
        )

        return (
            f"你是会议同传字幕翻译器。请把{source_name}翻译成{target_name}。\n"
            "要求：\n"
            "1. 保留说话者意图，优先自然口语字幕，不逐字硬翻。\n"
            "2. 参考上下文处理省略、指代和未完句。\n"
            "3. 只输出译文，不输出解释、标签或引号。\n"
            f"4. {stability_rule}\n\n"
            f"最近上下文：\n{history_lines or '无'}\n\n"
            f"当前原文：{text}"
        )


class StreamingTranslator:
    """基于 Mistral Chat Completion 的流式翻译客户端。"""

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model
        self._client = Mistral(api_key=api_key)

    async def close(self) -> None:
        """Mistral SDK 当前不需要显式关闭连接，保留接口便于替换。"""

        return None

    async def translate_stream(
        self,
        context: TranslationContext,
        text: str,
        *,
        is_final: bool,
    ) -> AsyncIterator[str]:
        """以流式方式读取 Mistral 翻译 delta。"""

        stream = await self._client.chat.stream_async(
            model=self._model,
            messages=[{"role": "user", "content": context.build_prompt(text, is_final)}],
            temperature=0.2,
            max_tokens=220,
        )
        async for event in stream:
            for choice in event.data.choices:
                content = choice.delta.content
                if isinstance(content, str) and content:
                    yield content
