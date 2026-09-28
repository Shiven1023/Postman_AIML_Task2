"""Extract programme-specific CDC/DEL lists and the common HUEL pool.
Run:
    python parse_course_categories.py

Output:
    processed/course_categories.json
"""

import json
import re
from collections import defaultdict
from pathlib import Path

import pdfplumber


PROJECT_DIR = Path(__file__).parent
BULLETIN_PATH = PROJECT_DIR / "data/bulletin.pdf"
OUTPUT_PATH = PROJECT_DIR / "processed/course_categories.json"

FIRST_PAGE = 314
LAST_PAGE = 335

COURSE_CODE_PATTERN = re.compile(
    r"\b(?P<department>[A-Z]{2,6})\s+"
    r"(?P<level>[A-Z]{1,2})\s*(?P<number>\d{3}[A-ZT]?(?:-\d+)?)\b",
    re.IGNORECASE,
)

# Headings are explicitly listed because programme names are the boundaries
# between tables.  The course codes themselves are still extracted from the
# supplied Bulletin rather than being hardcoded here.
PROGRAMME_HEADINGS = {
    "ARCHITECTURAL AND URBAN ENGINEERING": "Architectural and Urban Engineering",
    "BIOTECHNOLOGY": "Biotechnology",
    "BIOTECHNOLOGY WITH SPECIALIZATION IN APPLIED MOLECULAR BIOLOGY": (
        "Biotechnology with Specialization in Applied Molecular Biology"
    ),
    "CHEMICAL ENGINEERING": "Chemical Engineering",
    "CHEMICAL ENGINEERING WITH SPECIALIZATION IN ENERGY, ENVIRONMENT, AND SUSTAINABILITY": (
        "Chemical Engineering with Specialization in Energy, Environment, and Sustainability"
    ),
    "CIVIL ENGINEERING": "Civil Engineering",
    "COMPUTER SCIENCE": "Computer Science",
    "ELECTRICAL AND ELECTRONICS ENGINEERING": "Electrical and Electronics Engineering",
    "ELECTRONICS AND COMMUNICATION ENGINEERING": (
        "Electronics and Communication Engineering"
    ),
    "ELECTRONICS AND COMPUTER ENGINEERING": "Electronics and Computer Engineering",
    "ELECTRONICS AND INSTRUMENTATION ENGINEERING": (
        "Electronics and Instrumentation Engineering"
    ),
    "ENVIRONMENTAL AND SUSTAINABILITY ENGINEERING": (
        "Environmental and Sustainability Engineering"
    ),
    "MANUFACTURING ENGINEERING": "Manufacturing Engineering",
    "MATHEMATICS AND COMPUTING": "Mathematics and Computing",
    "MECHANICAL ENGINEERING": "Mechanical Engineering",
    "MECHANICAL ENGINEERING WITH SPECIALIZATION IN AEROSPACE": (
        "Mechanical Engineering with Specialization in Aerospace"
    ),
    "PHARMACY": "Pharmacy",
    "BIOLOGICAL SCIENCES": "Biological Sciences",
    "CHEMISTRY": "Chemistry",
    "ECONOMICS": "Economics",
    "MATHEMATICS": "Mathematics",
    "PHYSICS": "Physics",
    "PHYSICS WITH SPECIALIZATION IN SPACE SCIENCE AND TECHNOLOGY": (
        "Physics with Specialization in Space Science and Technology"
    ),
    "ROBOTICS AND INDUSTRIAL AUTOMATION": "Robotics and Industrial Automation",
    "GENERAL STUDIES - COMMUNICATION AND MEDIA STUDIES STREAM": (
        "General Studies - Communication and Media Studies Stream"
    ),
    "GENERAL STUDIES - DEVELOPMENT STUDIES STREAM": (
        "General Studies - Development Studies Stream"
    ),
    "SEMICONDUCTOR AND NANOSCIENCE": "Semiconductor and Nanoscience",
}

BBA_PROGRAMME = "Bachelor of Business Administration (Honours)"
COMMON_HUMANITIES_SCOPE = "All First-Degree Programmes"


def clean(text):
    """Normalize whitespace and dash characters from extracted PDF text."""
    text = (text or "").replace("–", "-").replace("—", "-")
    return " ".join(text.split()).strip()


def relative_path(path):
    return str(Path(path).resolve().relative_to(PROJECT_DIR.resolve()))


def normalize_course_code(match):
    return (
        f"{match.group('department').upper()} "
        f"{match.group('level').upper()}{match.group('number').upper()}"
    )


def programme_at(lines, index):
    """Recognize a one-, two-, or three-line programme heading."""
    for line_count in (3, 2, 1):
        candidate = clean(" ".join(lines[index : index + line_count]))
        # Programme headings are printed in uppercase. Requiring that visual
        # convention prevents a wrapped course title such as "Computer
        # Science" or "Biotechnology" from starting a new programme.
        if candidate != candidate.upper():
            continue
        if candidate in PROGRAMME_HEADINGS:
            return PROGRAMME_HEADINGS[candidate]
    return None


def page_columns(page):
    """Return left and right column text in the page's reading order."""
    middle = page.width / 2
    crops = [
        ("left", (0, 0, middle, page.height)),
        ("right", (middle, 0, page.width, page.height)),
    ]
    for column_name, box in crops:
        text = page.crop(box).extract_text(x_tolerance=1, y_tolerance=3) or ""
        yield column_name, [clean(line) for line in text.splitlines() if clean(line)]


def parse_course_categories(pdf_path=BULLETIN_PATH):
    """Return course classifications and programme-level course lists."""
    classifications = defaultdict(list)
    programme_courses = defaultdict(
        lambda: {"CDC": set(), "DEL": set(), "HUEL": set()}
    )
    programme_pages = defaultdict(set)

    current_programme = None
    current_category = None

    with pdfplumber.open(pdf_path) as bulletin:
        for page_number in range(FIRST_PAGE, LAST_PAGE + 1):
            page = bulletin.pages[page_number - 1]

            for column_name, lines in page_columns(page):
                for index, line in enumerate(lines):
                    programme = programme_at(lines, index)
                    if programme:
                        current_programme = programme
                        current_category = None
                        programme_pages[programme].add(page_number)
                        continue

                    # The supplied Bulletin continues directly from the
                    # Semiconductor DEL list to the BBA table on page 332;
                    # the programme name is supplied by its semester chart on
                    # page 238 but is not repeated above this course table.
                    if (
                        page_number == 332
                        and column_name == "left"
                        and line.startswith("CORE COURSES")
                    ):
                        current_programme = BBA_PROGRAMME
                        current_category = "CDC"
                        programme_pages[current_programme].update({238, 332})
                        continue

                    if line.startswith("CORE COURSES"):
                        current_category = "CDC"
                        continue
                    if line.startswith("DISCIPLINE ELECTIVE COURSES"):
                        current_category = "DEL"
                        continue
                    if line.startswith(
                        "Pool of Humanities courses for first degree"
                    ):
                        current_programme = COMMON_HUMANITIES_SCOPE
                        current_category = "HUEL"
                        programme_pages[current_programme].add(page_number)
                        continue
                    if line.startswith("Other Courses"):
                        current_programme = None
                        current_category = None
                        continue
                    if line.startswith("Project Type Courses"):
                        current_programme = None
                        current_category = None
                        continue

                    if not current_programme or not current_category:
                        continue

                    course_codes = [
                        normalize_course_code(match)
                        for match in COURSE_CODE_PATTERN.finditer(line)
                    ]

                    # A few narrow table rows place the department on one line
                    # and the F/G-number on the next, for example:
                    #   ECOM  Real Time Operating Systems  3 1 4
                    #   F321
                    if not course_codes and index + 1 < len(lines):
                        department = re.match(r"^(?P<department>[A-Z]{2,6})\s+", line)
                        suffix = re.fullmatch(
                            r"(?P<level>[A-Z]{1,2})\s*(?P<number>\d{3}[A-ZT]?)",
                            lines[index + 1],
                            re.IGNORECASE,
                        )
                        if department and suffix:
                            course_codes = [
                                f"{department.group('department').upper()} "
                                f"{suffix.group('level').upper()}"
                                f"{suffix.group('number').upper()}"
                            ]

                    for course_code in course_codes:
                        programme_pages[current_programme].add(page_number)
                        programme_courses[current_programme][current_category].add(
                            course_code
                        )
                        classification = {
                            "programme": current_programme,
                            "category": current_category,
                            "source": {
                                "document": relative_path(pdf_path),
                                "page": page_number,
                            },
                        }
                        if not any(
                            item["programme"] == current_programme
                            and item["category"] == current_category
                            for item in classifications[course_code]
                        ):
                            classifications[course_code].append(classification)

    course_records = [
        {
            "course_code": course_code,
            "classifications": sorted(
                items, key=lambda item: (item["programme"], item["category"])
            ),
        }
        for course_code, items in sorted(classifications.items())
    ]

    programme_records = [
        {
            "programme": programme,
            "cdc_course_codes": sorted(categories["CDC"]),
            "del_course_codes": sorted(categories["DEL"]),
            "huel_course_codes": sorted(categories["HUEL"]),
            "source": {
                "document": relative_path(pdf_path),
                "pages": sorted(programme_pages[programme]),
            },
        }
        for programme, categories in sorted(programme_courses.items())
    ]

    return {
        "metadata": {
            "source": relative_path(pdf_path),
            "page_range": [FIRST_PAGE, LAST_PAGE],
            "definitions": {
                "CDC": "Core Course listed for the programme in the Bulletin.",
                "DEL": "Discipline Elective listed for the programme in the Bulletin.",
                "HUEL": (
                    "Humanities Elective listed in the common pool for all "
                    "first-degree programmes."
                ),
            },
            "note": (
                "A classification is programme-specific. The same course may be a "
                "CDC for one programme and a DEL for another. HUEL is a common "
                "pool classification."
            ),
            "rules": [
                {
                    "category": "HUEL",
                    "rule": "own_discipline_course_cannot_count_as_huel",
                    "description": (
                        "A student cannot count a course, or its equivalent, "
                        "from the student's own discipline as a Humanities "
                        "Elective even when it appears in the common HUEL pool."
                    ),
                    "source": {
                        "document": relative_path(pdf_path),
                        "page": 335,
                    },
                }
            ],
            "first_year_note": {
                "classification": (
                    "Year-I courses come from programme-specific named schedules "
                    "and General Institutional Requirements, not a common CDC "
                    "pool. Some programme charts contain explicit alternatives."
                ),
                "mvp_behavior": (
                    "Profiles in semesters 1 or 2 may be stored, but the MVP "
                    "does not support first-year schedule selection and should "
                    "direct those students to their programme chart. This is an "
                    "MVP scope limitation, not an academic ineligibility rule."
                ),
                "sources": [
                    {"document": relative_path(pdf_path), "page": 209},
                    {"document": relative_path(pdf_path), "page": 210},
                    {
                        "document": relative_path(pdf_path),
                        "page_range": [211, 238],
                    },
                ],
            },
            "counts": {
                "programmes": sum(
                    record["programme"] != COMMON_HUMANITIES_SCOPE
                    for record in programme_records
                ),
                "common_pools": 1,
                "unique_courses": len(course_records),
                "classifications": sum(
                    len(record["classifications"]) for record in course_records
                ),
            },
        },
        "programmes": programme_records,
        "courses": course_records,
    }


def main():
    output = parse_course_categories()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    counts = output["metadata"]["counts"]
    print(
        f"Categories: {counts['unique_courses']} courses, "
        f"{counts['classifications']} programme classifications"
    )
    print(f"Output: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
