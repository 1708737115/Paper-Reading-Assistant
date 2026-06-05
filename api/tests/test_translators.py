from __future__ import annotations

import json
import unittest

from api.app.models import SourceBlock
from api.app.translators import TranslationFormatError, normalize_translation_response


class NormalizeTranslationResponseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.blocks = [
            SourceBlock(page_number=1, block_id="p0001-b0001", source_text="The Next Era of Knowledge Work"),
            SourceBlock(page_number=1, block_id="p0001-b0002", source_text="How Codex helps knowledge workers"),
        ]

    def test_accepts_translated_text_without_source_text(self) -> None:
        raw = json.dumps(
            {
                "translations": [
                    {"page_number": 1, "block_id": "p0001-b0001", "translated_text": "知识工作的下一个时代"},
                    {"page_number": 1, "block_id": "p0001-b0002", "translated_text": "Codex 如何帮助知识工作者"},
                ]
            },
            ensure_ascii=False,
        )

        result = normalize_translation_response(raw, self.blocks)

        self.assertEqual(result[0].source_text, "The Next Era of Knowledge Work")
        self.assertEqual(result[0].translation, "知识工作的下一个时代")
        self.assertEqual(result[1].translation, "Codex 如何帮助知识工作者")

    def test_accepts_container_and_translation_aliases(self) -> None:
        raw = json.dumps(
            {
                "translated_blocks": [
                    {"block_id": "p0001-b0001", "target_text": "知识工作的下一个时代", "terms": ["knowledge work"]},
                    {"block_id": "p0001-b0002", "chinese": "Codex 如何帮助知识工作者"},
                ]
            },
            ensure_ascii=False,
        )

        result = normalize_translation_response(raw, self.blocks)

        self.assertEqual(result[0].terms, ["knowledge work"])
        self.assertEqual(result[1].translation, "Codex 如何帮助知识工作者")

    def test_matches_by_order_when_block_id_is_missing(self) -> None:
        raw = json.dumps(
            {
                "results": [
                    {"translation": "知识工作的下一个时代"},
                    {"translation": "Codex 如何帮助知识工作者"},
                ]
            },
            ensure_ascii=False,
        )

        result = normalize_translation_response(raw, self.blocks)

        self.assertEqual(result[0].block_id, "p0001-b0001")
        self.assertIn("Matched translation by batch order", result[0].warnings[0])
        self.assertEqual(result[1].block_id, "p0001-b0002")

    def test_raises_clear_error_when_translation_text_is_missing(self) -> None:
        raw = json.dumps({"translations": [{"block_id": "p0001-b0001", "warnings": []}]})

        with self.assertRaisesRegex(TranslationFormatError, "missing translation text"):
            normalize_translation_response(raw, self.blocks)

    def test_accepts_nested_data_container(self) -> None:
        raw = json.dumps(
            {
                "data": {
                    "translations": [
                        {"block_id": "p0001-b0001", "translation_text": "知识工作的下一个时代"},
                        {"block_id": "p0001-b0002", "translation_text": "Codex 如何帮助知识工作者"},
                    ]
                }
            },
            ensure_ascii=False,
        )

        result = normalize_translation_response(raw, self.blocks)

        self.assertEqual(result[0].translation, "知识工作的下一个时代")
        self.assertEqual(result[1].translation, "Codex 如何帮助知识工作者")

    def test_accepts_block_id_keyed_mapping(self) -> None:
        raw = json.dumps(
            {
                "p0001-b0001": "知识工作的下一个时代",
                "p0001-b0002": {"translatedText": "Codex 如何帮助知识工作者"},
            },
            ensure_ascii=False,
        )

        result = normalize_translation_response(raw, self.blocks)

        self.assertEqual(result[0].translation, "知识工作的下一个时代")
        self.assertEqual(result[1].translation, "Codex 如何帮助知识工作者")

    def test_accepts_nested_page_blocks(self) -> None:
        raw = json.dumps(
            {
                "pages": [
                    {
                        "page_number": 1,
                        "blocks": [
                            {"block_id": "p0001-b0001", "content": "知识工作的下一个时代"},
                            {"block_id": "p0001-b0002", "content": "Codex 如何帮助知识工作者"},
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        )

        result = normalize_translation_response(raw, self.blocks)

        self.assertEqual(result[0].translation, "知识工作的下一个时代")
        self.assertEqual(result[1].translation, "Codex 如何帮助知识工作者")


if __name__ == "__main__":
    unittest.main()
