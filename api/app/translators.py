from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Iterable, TypeVar

import httpx
from pydantic import BaseModel, Field, ValidationError

from .models import GlossaryTerm, ProviderName, SourceBlock, TranslatedBlock


PayloadT = TypeVar("PayloadT", bound=BaseModel)


class GlossaryPayload(BaseModel):
    terms: list[GlossaryTerm] = Field(default_factory=list)


class TranslationFormatError(RuntimeError):
    pass


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
        try:
            return normalize_translation_response(raw, blocks)
        except TranslationFormatError:
            repaired = await self._repair_response(raw, schema)
            try:
                return normalize_translation_response(repaired, blocks)
            except TranslationFormatError as exc:
                raise RuntimeError(f"Model returned unsupported translation JSON: {exc}") from exc

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
            repaired = await self._repair_response(raw, schema)
            return model_type.model_validate(parse_json_object(repaired))

    async def _repair_response(self, raw: str, schema: dict[str, Any]) -> str:
        repair_prompt = (
            "Repair the following model output into valid JSON that matches the requested schema. "
            "For translation payloads, each item only needs block_id, translation, terms, and warnings. "
            "Return JSON only and do not add commentary.\n\n"
            f"Invalid output:\n{raw[:12000]}"
        )
        return await self._json_request(SYSTEM_PROMPT, repair_prompt, schema)


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


def normalize_translation_response(raw: str, blocks: list[SourceBlock]) -> list[TranslatedBlock]:
    data = parse_json_value(raw)
    items = extract_translation_items(data, [block.block_id for block in blocks])
    if not items:
        raise TranslationFormatError("no translation items found")

    block_by_id = {block.block_id: block for block in blocks}
    translated_by_id: dict[str, TranslatedBlock] = {}
    missing_translation_ids: list[str] = []

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        block_id = coerce_text(item.get("block_id") or item.get("id"))
        block = block_by_id.get(block_id)
        warnings = coerce_text_list(item.get("warnings"))

        if block is None:
            if index < len(blocks):
                block = blocks[index]
                block_id = block.block_id
                warnings.append("Matched translation by batch order because block_id was missing or unknown")
            else:
                continue

        if block_id in translated_by_id:
            continue

        translation = first_text(item, TRANSLATION_TEXT_KEYS)
        if not translation:
            missing_translation_ids.append(block_id)
            continue

        translated_by_id[block_id] = TranslatedBlock(
            page_number=block.page_number,
            block_id=block.block_id,
            source_text=block.source_text,
            translation=translation,
            terms=coerce_text_list(item.get("terms")),
            warnings=[*block.warnings, *warnings],
        )

    if missing_translation_ids:
        sample = ", ".join(missing_translation_ids[:5])
        raise TranslationFormatError(f"missing translation text for {len(missing_translation_ids)} item(s): {sample}")

    translated: list[TranslatedBlock] = []
    for block in blocks:
        item = translated_by_id.get(block.block_id)
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
        else:
            translated.append(item)
    return translated


TRANSLATION_CONTAINER_KEYS = (
    "translations",
    "translated_blocks",
    "translatedBlocks",
    "results",
    "items",
    "blocks",
    "paragraphs",
    "segments",
    "outputs",
)

TRANSLATION_TEXT_KEYS = (
    "translation",
    "translated",
    "translated_text",
    "translatedText",
    "translation_text",
    "target_text",
    "targetText",
    "chinese",
    "zh",
    "zh_text",
    "zhText",
    "zh_cn",
    "text",
    "content",
)


def extract_translation_items(data: Any, known_block_ids: list[str] | None = None) -> list[Any]:
    known_block_ids = known_block_ids or []
    if isinstance(data, list):
        return normalize_list_items(data)
    if isinstance(data, dict):
        mapped = block_mapping_items(data, known_block_ids)
        if mapped:
            return mapped
        for key in TRANSLATION_CONTAINER_KEYS:
            value = data.get(key)
            if isinstance(value, list):
                return normalize_list_items(value)
            if isinstance(value, dict):
                mapped = block_mapping_items(value, known_block_ids)
                if mapped:
                    return mapped
        nested = find_best_translation_list(data, known_block_ids)
        if nested:
            return nested
    raise TranslationFormatError("expected a translations array or block-id keyed translation object")


def normalize_list_items(items: list[Any]) -> list[Any]:
    if all(isinstance(item, str) for item in items):
        return [{"translation": item} for item in items]
    return items


def block_mapping_items(data: dict[str, Any], known_block_ids: list[str]) -> list[dict[str, Any]]:
    if not known_block_ids:
        return []
    items_by_id: dict[str, dict[str, Any]] = {}
    for block_id in known_block_ids:
        value = data.get(block_id)
        if isinstance(value, str):
            items_by_id[block_id] = {"block_id": block_id, "translation": value}
        elif isinstance(value, dict):
            item = dict(value)
            item.setdefault("block_id", block_id)
            items_by_id[block_id] = item
    return [items_by_id[block_id] for block_id in known_block_ids if block_id in items_by_id]


def find_best_translation_list(data: Any, known_block_ids: list[str]) -> list[Any]:
    candidates: list[tuple[int, list[Any]]] = []

    def visit(value: Any) -> None:
        if isinstance(value, list):
            normalized = normalize_list_items(value)
            score = translation_list_score(normalized, known_block_ids)
            if score > 0:
                candidates.append((score, normalized))
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            mapped = block_mapping_items(value, known_block_ids)
            if mapped:
                candidates.append((translation_list_score(mapped, known_block_ids) + 5, mapped))
            for nested in value.values():
                visit(nested)

    visit(data)
    if not candidates:
        return []
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def translation_list_score(items: list[Any], known_block_ids: list[str]) -> int:
    score = 0
    known = set(known_block_ids)
    for item in items:
        if isinstance(item, dict):
            block_id = coerce_text(item.get("block_id") or item.get("id"))
            if block_id in known:
                score += 5
            if any(coerce_text(item.get(key)) for key in TRANSLATION_TEXT_KEYS):
                score += 3
            if "page_number" in item or "page" in item:
                score += 1
            if "source_text" in item or "source" in item:
                score += 1
    return score


def first_text(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = item.get(key)
        text = coerce_text(value)
        if text:
            return text
    return ""


def coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    return ""


def coerce_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [text for text in (coerce_text(item) for item in value) if text]
    return []


def parse_json_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        object_start = raw.find("{")
        object_end = raw.rfind("}")
        array_start = raw.find("[")
        array_end = raw.rfind("]")
        if array_start >= 0 and array_end > array_start and (object_start < 0 or array_start < object_start):
            return json.loads(raw[array_start : array_end + 1])
        if object_start >= 0 and object_end > object_start:
            return json.loads(raw[object_start : object_end + 1])
        raise


def parse_json_object(raw: str) -> dict[str, Any]:
    data = parse_json_value(raw)
    if not isinstance(data, dict):
        raise json.JSONDecodeError("Expected JSON object", raw, 0)
    return data


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
                            "translation": {"type": "string"},
                            "terms": {"type": "array", "items": {"type": "string"}},
                            "warnings": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["block_id", "translation", "terms", "warnings"],
                    },
                }
            },
            "required": ["translations"],
        },
    }
