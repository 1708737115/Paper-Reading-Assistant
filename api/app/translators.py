from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Iterable, TypeVar

import httpx
from pydantic import BaseModel, Field, ValidationError

from .models import GlossaryTerm, ProviderName, SourceBlock, TranslatedBlock


PayloadT = TypeVar("PayloadT", bound=BaseModel)


class TranslationItem(BaseModel):
    block_id: str
    source_text: str
    translation: str
    terms: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TranslationPayload(BaseModel):
    translations: list[TranslationItem]


class GlossaryPayload(BaseModel):
    terms: list[GlossaryTerm] = Field(default_factory=list)


@dataclass
class ProviderConfig:
    provider: ProviderName
    model: str
    api_key: str


class BaseTranslator:
    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    async def build_glossary(self, blocks: list[SourceBlock]) -> list[GlossaryTerm]:
        sample = "\n\n".join(block.source_text for block in blocks[:10])[:7000]
        if not sample:
            return []
        prompt = (
            "Extract a concise bilingual glossary from the academic paper excerpt. "
            "Return JSON only with a terms array. Each term must have source and target. "
            "Use Simplified Chinese for target terms."
        )
        raw = await self._json_request(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=f"{prompt}\n\nExcerpt:\n{sample}",
            schema=glossary_schema(),
        )
        payload = await self._validate_or_repair(raw, GlossaryPayload, glossary_schema())
        return payload.terms[:40]

    async def translate_batch(self, blocks: list[SourceBlock], glossary: list[GlossaryTerm]) -> list[TranslatedBlock]:
        glossary_text = json.dumps([term.model_dump() for term in glossary], ensure_ascii=False)
        block_payload = [
            {
                "page_number": block.page_number,
                "block_id": block.block_id,
                "source_text": block.source_text,
                "warnings": block.warnings,
            }
            for block in blocks
        ]
        prompt = (
            "Translate the following academic paper blocks into Simplified Chinese. "
            "Return JSON only. Preserve equations, variables, citation numbers, figure/table labels, "
            "section numbers, and proper nouns. Do not invent content. If OCR text looks suspicious, "
            "add a short warning for that block.\n\n"
            f"Glossary:\n{glossary_text}\n\n"
            f"Blocks:\n{json.dumps(block_payload, ensure_ascii=False)}"
        )
        schema = translation_schema()
        raw = await self._json_request(SYSTEM_PROMPT, prompt, schema)
        payload = await self._validate_or_repair(raw, TranslationPayload, schema)
        by_id = {item.block_id: item for item in payload.translations}
        translated: list[TranslatedBlock] = []
        for block in blocks:
            item = by_id.get(block.block_id)
            if item is None:
                translated.append(
                    TranslatedBlock(
                        page_number=block.page_number,
                        block_id=block.block_id,
                        source_text=block.source_text,
                        translation="",
                        terms=[],
                        warnings=[*block.warnings, "Missing translation from model"],
                    )
                )
                continue
            translated.append(
                TranslatedBlock(
                    page_number=block.page_number,
                    block_id=block.block_id,
                    source_text=block.source_text,
                    translation=item.translation.strip(),
                    terms=item.terms,
                    warnings=[*block.warnings, *item.warnings],
                )
            )
        return translated

    async def _json_request(self, system_prompt: str, user_prompt: str, schema: dict[str, Any]) -> str:
        raise NotImplementedError

    async def _validate_or_repair(
        self,
        raw: str,
        model_type: type[PayloadT],
        schema: dict[str, Any],
    ) -> PayloadT:
        try:
            return model_type.model_validate(parse_json_object(raw))
        except (json.JSONDecodeError, ValidationError):
            repair_prompt = (
                "Repair the following model output into valid JSON that matches the requested schema. "
                "Return JSON only and do not add commentary.\n\n"
                f"Invalid output:\n{raw[:12000]}"
            )
            repaired = await self._json_request(SYSTEM_PROMPT, repair_prompt, schema)
            return model_type.model_validate(parse_json_object(repaired))


class OpenAIResponsesTranslator(BaseTranslator):
    async def _json_request(self, system_prompt: str, user_prompt: str, schema: dict[str, Any]) -> str:
        payload = {
            "model": self.config.model,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema["name"],
                    "strict": True,
                    "schema": schema["schema"],
                }
            },
        }
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        if response.status_code >= 400:
            raise RuntimeError(provider_error("OpenAI", response))
        return extract_openai_response_text(response.json())


class DeepSeekTranslator(BaseTranslator):
    async def _json_request(self, system_prompt: str, user_prompt: str, schema: dict[str, Any]) -> str:
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": f"{system_prompt}\nReturn valid JSON only."},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(
                "https://api.deepseek.com/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        if response.status_code >= 400:
            raise RuntimeError(provider_error("DeepSeek", response))
        data = response.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("DeepSeek returned an unexpected response shape.") from exc


def create_translator(config: ProviderConfig) -> BaseTranslator:
    if config.provider == ProviderName.openai:
        return OpenAIResponsesTranslator(config)
    if config.provider == ProviderName.deepseek:
        return DeepSeekTranslator(config)
    raise ValueError(f"Unsupported provider: {config.provider}")


async def translate_blocks(
    config: ProviderConfig,
    blocks: list[SourceBlock],
    progress: Callable[[int, str], None],
    start_progress: int = 45,
    end_progress: int = 88,
) -> tuple[list[GlossaryTerm], list[TranslatedBlock]]:
    translator = create_translator(config)
    progress(start_progress, "Building glossary")
    glossary = await translator.build_glossary(blocks)
    batches = list(batch_blocks(blocks))
    translated: list[TranslatedBlock] = []
    total = max(1, len(batches))
    for index, batch in enumerate(batches, start=1):
        current = start_progress + int(index / total * (end_progress - start_progress))
        progress(current, f"Translating batch {index}/{total}")
        translated.extend(await translator.translate_batch(batch, glossary))
    return glossary, translated


def batch_blocks(blocks: list[SourceBlock], max_chars: int = 8500, max_blocks: int = 14) -> Iterable[list[SourceBlock]]:
    batch: list[SourceBlock] = []
    chars = 0
    for block in blocks:
        block_len = len(block.source_text)
        if batch and (chars + block_len > max_chars or len(batch) >= max_blocks):
            yield batch
            batch = []
            chars = 0
        batch.append(block)
        chars += block_len
    if batch:
        yield batch


def parse_json_object(raw: str) -> dict[str, Any]:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw[start : end + 1])
        raise


def extract_openai_response_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    for item in data.get("output", []):
        for content in item.get("content", []):
            if isinstance(content, dict):
                if isinstance(content.get("text"), str):
                    return content["text"]
                if isinstance(content.get("output_text"), str):
                    return content["output_text"]
    raise RuntimeError("OpenAI returned an unexpected response shape.")


def provider_error(name: str, response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = {"message": response.text}
    message = payload.get("error", payload)
    return f"{name} API error ({response.status_code}): {message}"


SYSTEM_PROMPT = (
    "You are a careful academic translation engine. You translate English research papers into "
    "clear Simplified Chinese for close reading. Keep factual content faithful and preserve symbols."
)


def glossary_schema() -> dict[str, Any]:
    return {
        "name": "glossary_payload",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "terms": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "source": {"type": "string"},
                            "target": {"type": "string"},
                        },
                        "required": ["source", "target"],
                    },
                }
            },
            "required": ["terms"],
        },
    }


def translation_schema() -> dict[str, Any]:
    return {
        "name": "translation_payload",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "translations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "block_id": {"type": "string"},
                            "source_text": {"type": "string"},
                            "translation": {"type": "string"},
                            "terms": {"type": "array", "items": {"type": "string"}},
                            "warnings": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["block_id", "source_text", "translation", "terms", "warnings"],
                    },
                }
            },
            "required": ["translations"],
        },
    }
