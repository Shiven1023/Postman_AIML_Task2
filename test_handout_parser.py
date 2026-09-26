"""Small regression test for the different handout layouts we inspected."""

import unittest
from pathlib import Path

from parse_handouts import parse_handout


PROJECT_DIR = Path(__file__).parent


class HandoutParserTests(unittest.TestCase):
    CASES = [
        ("002_BIO_F101.pdf", "BIO F101", "INTRODUCTION TO BIOLOGICAL SCIENCES"),
        ("057_BITS_F464.pdf", "BITS F464", "Machine Learning"),
        ("185_CS_G569.pdf", "CS G569", "Agentic AI"),
        ("180_CS_G527.pdf", "CS G527", "Cloud Computing"),
        ("191_CS_U407.pdf", "CS F407", "ARTIFICIAL INTELLIGENCE"),
        ("329_HSS_F343.pdf", "HSS F343", "Professional Ethics"),
        ("524_PHY_U110.pdf", "PHY U110", "Physics Laboratory"),
        ("132_CHE_F491.pdf", "CHE F491", "Special Projects"),
    ]

    def test_representative_handout_identities(self):
        for filename, expected_code, expected_title in self.CASES:
            with self.subTest(filename=filename):
                record = parse_handout(PROJECT_DIR / "data/handouts" / filename)
                self.assertEqual(record["course"]["primary_code"]["value"], expected_code)
                self.assertEqual(record["course"]["title"]["value"], expected_title)
                self.assertIsNotNone(record["course"]["instructor_in_charge"]["value"])

    def test_filename_fallback_is_never_silently_verified(self):
        record = parse_handout(PROJECT_DIR / "data/handouts/057_BITS_F464.pdf")
        code = record["course"]["primary_code"]
        if code["status"] == "filename_fallback":
            self.assertIn(
                "course_code_from_filename_needs_pdf_verification",
                record["validation"]["issues"],
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
