"""Small tests for the Bulletin + timetable + handout aggregation pipeline."""

import unittest

from build_course_catalog import (
    build_catalog,
    parse_bulletin_prerequisites,
    parse_timetable_courses,
)
from parse_course_categories import parse_course_categories


class CourseCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prerequisites = parse_bulletin_prerequisites()
        cls.timetable_codes = parse_timetable_courses()
        category_output = parse_course_categories()
        cls.categories = {
            record["course_code"]: record["classifications"]
            for record in category_output["courses"]
        }

    def test_categories_are_programme_specific(self):
        cs_f213 = {
            (item["programme"], item["category"])
            for item in self.categories["CS F213"]
        }
        self.assertIn(("Computer Science", "CDC"), cs_f213)
        self.assertIn(
            ("Electrical and Electronics Engineering", "DEL"),
            cs_f213,
        )

    def test_ai_is_a_computer_science_del(self):
        cs_f407 = {
            (item["programme"], item["category"])
            for item in self.categories["CS F407"]
        }
        self.assertIn(("Computer Science", "DEL"), cs_f407)

    def test_humanities_pool_is_common_to_first_degree_programmes(self):
        hss_f343 = {
            (item["programme"], item["category"])
            for item in self.categories["HSS F343"]
        }
        self.assertIn(
            ("All First-Degree Programmes", "HUEL"),
            hss_f343,
        )

    def test_other_courses_are_not_misread_as_humanities_electives(self):
        bits_f225 = {
            (item["programme"], item["category"])
            for item in self.categories.get("BITS F225", [])
        }
        self.assertNotIn(
            ("All First-Degree Programmes", "HUEL"),
            bits_f225,
        )

    def test_eee_f437_prerequisites(self):
        record = self.prerequisites["EEE F437"]
        self.assertEqual(record["rule"], "any_of")
        self.assertEqual(
            set(record["prerequisite_course_codes"]),
            {"ECE F214", "ECOM F214", "EEE F214", "INSTR F214"},
        )

    def test_wrapped_bulletin_course_heading(self):
        record = self.prerequisites["BITS F429"]
        self.assertEqual(record["rule"], "any_of")
        self.assertIn("BITS F201", record["prerequisite_course_codes"])
        self.assertNotIn("BITS F429", record["prerequisite_course_codes"])

    def test_prerequisite_does_not_absorb_later_course_mentions(self):
        record = self.prerequisites["ECE F331"]
        self.assertNotIn("ECE F314", record["prerequisite_course_codes"])

    def test_logical_or_is_not_misread_as_a_course_department(self):
        record = self.prerequisites["AN F311"]
        self.assertNotIn("OR MF218", record["prerequisite_course_codes"])

    def test_shared_department_list_is_any_of(self):
        record = self.prerequisites["EEE F419"]
        self.assertEqual(record["rule"], "any_of")

    def test_ampersand_is_all_of(self):
        record = self.prerequisites["PHY F433"]
        self.assertEqual(record["rule"], "all_of")

    def test_timetable_course_codes(self):
        self.assertIn("BITS F464", self.timetable_codes)
        self.assertIn("CS F407", self.timetable_codes)
        self.assertIn("EEE F437", self.timetable_codes)
        self.assertNotIn("ME U423", self.timetable_codes)

    def test_aggregation_adds_boolean_and_prerequisites(self):
        handout = {
            "document": {"path": "data/handouts/example.pdf"},
            "course": {
                "primary_code": {"value": "EEE F437"},
                "alternate_codes": {"value": []},
                "title": {"value": "Semiconductor Fabrication Technology"},
                "instructor_in_charge": {"value": "Example Instructor"},
                "description": {"value": "Example description"},
                "objectives": {"value": "Example objectives"},
                "prerequisites_raw": {"value": "Electronic Devices (F-214)"},
            },
            "validation": {"status": "passed", "issues": []},
        }
        courses = build_catalog(
            [handout],
            self.prerequisites,
            self.timetable_codes,
            self.categories,
        )
        self.assertIs(courses[0]["offered_this_sem"], True)
        self.assertEqual(
            courses[0]["formal_prerequisites"]["rule"], "any_of"
        )
        self.assertIn(
            {
                "programme": "Electrical and Electronics Engineering",
                "category": "DEL",
                "source": {
                    "document": "data/bulletin.pdf",
                    "page": 319,
                },
            },
            courses[0]["programme_classifications"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
