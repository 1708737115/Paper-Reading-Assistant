from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from api.app.models import (
    LookupEntry,
    PageImage,
    ProviderName,
    SourceWord,
    TranslatedBlock,
    TranslationDocument,
    now_utc,
)
from api.app.rendering import write_preview


class PreviewRenderingTests(unittest.TestCase):
    def test_preview_embeds_lookup_data_and_clickable_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "preview.html"
            document = TranslationDocument(
                job_id="job123",
                filename="paper.pdf",
                provider=ProviderName.deepseek,
                model="deepseek-v4-pro",
                created_at=now_utc(),
                pages=[
                    PageImage(
                        page_number=1,
                        width=200,
                        height=100,
                        image_name="page.png",
                        extraction_method="text-layer",
                        words=[
                            SourceWord(
                                page_number=1,
                                block_id="p0001-b0001",
                                text="Knowledge",
                                bbox=[10, 10, 40, 20],
                            )
                        ],
                    )
                ],
                translations=[
                    TranslatedBlock(
                        page_number=1,
                        block_id="p0001-b0001",
                        source_text="Knowledge work changes quickly.",
                        translation="Knowledge work means knowledge-based tasks.",
                    )
                ],
                lookup_entries=[
                    LookupEntry(
                        source="Knowledge work",
                        meaning="knowledge-based work",
                        explanation="Work centered on information and expertise.",
                        block_ids=["p0001-b0001"],
                        page_numbers=[1],
                    )
                ],
            )

            write_preview(document, output)
            html = output.read_text(encoding="utf-8")

        self.assertIn("lookup-data", html)
        self.assertIn("source-word", html)
        self.assertIn("source-token", html)
        self.assertIn("Knowledge work", html)
        self.assertIn("lookup-popover", html)


if __name__ == "__main__":
    unittest.main()
