from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import fitz

from api.app.pdf_pipeline import extract_pdf_pages


class PdfPipelineWordExtractionTests(unittest.TestCase):
    def test_extracts_words_from_text_layer_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pdf_path = tmp_path / "sample.pdf"
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((72, 72), "Knowledge work changes quickly in modern teams.")
            page.insert_text((72, 108), "Codex helps readers inspect source phrases.")
            doc.save(pdf_path)
            doc.close()

            pages = extract_pdf_pages(pdf_path, tmp_path, lambda _progress, _step: None)

        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0].extraction_method, "text-layer")
        self.assertGreater(len(pages[0].words), 5)
        self.assertTrue(any(word.text == "Knowledge" for word in pages[0].words))
        self.assertTrue(all(len(word.bbox) == 4 for word in pages[0].words))


if __name__ == "__main__":
    unittest.main()
