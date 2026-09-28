"""Build one small course catalogue from the processed handouts and two PDFs.

The pipeline intentionally does only four things:

1. Read explicit, course-code prerequisites from the Bulletin.
2. Read programme-specific CDC/DEL lists and the common HUEL pool.
3. Read course codes listed in the current semester timetable.
4. Add those results to the already processed handout records.

Run:
    python build_course_catalog.py

Outputs:
    processed/bulletin_prerequisites.json
    processed/course_categories.json
    processed/timetable_courses.json
    processed/course_catalog.json
"""

import json
import logging
import re
from pathlib import Path

from pypdf import PdfReader

from parse_course_categories import parse_course_categories


PROJECT_DIR = Path(__file__).parent
BULLETIN_PATH = PROJECT_DIR / "data/bulletin.pdf"
TIMETABLE_PATH = PROJECT_DIR / "data/timetable.pdf"
HANDOUTS_PATH = PROJECT_DIR / "processed/handout_identities.json"

BULLETIN_OUTPUT = PROJECT_DIR / "processed/bulletin_prerequisites.json"
TIMETABLE_OUTPUT = PROJECT_DIR / "processed/timetable_courses.json"
CATALOG_OUTPUT = PROJECT_DIR / "processed/course_catalog.json"

# These page ranges belong to the supplied PDFs. They keep the parser away from
# admission material, equivalent-course lists, and other unrelated sections.
BULLETIN_FIRST_COURSE_PAGE = 611
BULLETIN_LAST_COURSE_PAGE = 751
TIMETABLE_FIRST_COURSE_PAGE = 10
TIMETABLE_LAST_COURSE_PAGE = 112

COURSE_CODE_PATTERN = (
    r"[A-Z]{2,6}\s+[A-Z]{1,2}\s*\d{3}[A-ZT]?(?:-\d+)?"
)
COURSE_HEADER_PATTERN = re.compile(
    rf"^(?P<code>{COURSE_CODE_PATTERN})\s+.+?\s+"
    rf"(?:\d+\s+){{0,3}}\d+\*?$",
    re.IGNORECASE,
)
COURSE_HEADER_START_PATTERN = re.compile(
    rf"^(?P<code>{COURSE_CODE_PATTERN})\s+(?P<title>.+)$",
    re.IGNORECASE,
)
UNITS_ONLY_PATTERN = re.compile(r"^(?:\d+\s+){0,3}\d+\*?$")
PREREQUISITE_LABEL_PATTERN = re.compile(
    r"^Pre\s*[- ]?\s*requisites?\s*:?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)
TIMETABLE_ROW_PATTERN = re.compile(
    rf"\b\d{{1,4}}\s+(?P<code>{COURSE_CODE_PATTERN})\s+",
    re.IGNORECASE,
)

logging.getLogger("pypdf").setLevel(logging.ERROR)


def clean(text):
    """Collapse repeated PDF whitespace."""
    return " ".join((text or "").split()).strip()


def relative_path(path):
    """Return a path that remains portable inside this project."""
    return str(Path(path).resolve().relative_to(PROJECT_DIR.resolve()))


def normalize_course_code(value):
    """Normalize values such as 'EEE  F 437' to 'EEE F437'."""
    match = re.fullmatch(
        r"\s*([A-Z]{2,6})\s+([A-Z]{1,2})\s*(\d{3}[A-ZT]?(?:-\d+)?)\s*",
        value.upper(),
    )
    if not match:
        return clean(value).upper()
    return f"{match.group(1)} {match.group(2)}{match.group(3)}"


def course_codes_from_text(text):
    """Extract normalized course codes, including shared-prefix expressions.

    Example: ``ECE/EEE/INSTR F211`` becomes three course codes.
    """
    text = clean(text).upper()
    codes = []

    shared_pattern = re.compile(
        r"\b((?:[A-Z]{2,6}\s*/\s*)+[A-Z]{2,6})\s+"
        r"([A-Z]{1,2})\s*(\d{3}[A-ZT]?(?:-\d+)?)\b"
    )
    for match in shared_pattern.finditer(text):
        for department in re.split(r"\s*/\s*", match.group(1)):
            codes.append(f"{department} {match.group(2)}{match.group(3)}")

    normal_pattern = re.compile(rf"\b({COURSE_CODE_PATTERN})\b")
    for match in normal_pattern.finditer(text):
        codes.append(normalize_course_code(match.group(1)))

    codes = list(dict.fromkeys(codes))
    return [code for code in codes if code.split()[0] not in {"AND", "OR"}]


def prerequisite_rule(raw_text, course_codes):
    """Describe the simple AND/OR shape without trying to interpret mixed rules."""
    if len(course_codes) == 1:
        return "single"

    # Find logical connectors *between* course-code groups. Taking the last
    # connector in each gap avoids mistaking a title such as "Science and
    # Engineering ... OR" for an AND rule.
    shared_pattern = re.compile(
        r"\b((?:[A-Z]{2,6}\s*/\s*)+[A-Z]{2,6})\s+"
        r"[A-Z]{1,2}\s*\d{3}[A-ZT]?(?:-\d+)?\b",
        re.IGNORECASE,
    )
    normal_pattern = re.compile(rf"\b{COURSE_CODE_PATTERN}\b", re.IGNORECASE)
    groups = [(match.start(), match.end(), True) for match in shared_pattern.finditer(raw_text)]
    for match in normal_pattern.finditer(raw_text):
        if not any(start <= match.start() < end for start, end, _ in groups):
            groups.append((match.start(), match.end(), False))
    groups.sort()

    connectors = []
    for left, right in zip(groups, groups[1:]):
        gap = raw_text[left[1] : right[0]]
        matches = list(re.finditer(r"\bOR\b|\bAND\b|&|/", gap, re.I))
        if matches:
            connector = matches[-1].group(0).upper()
            if connector == "/":
                connector = "OR"
            elif connector == "&":
                connector = "AND"
            connectors.append(connector)

    connector_types = set(connectors)
    has_alternative_group = any(is_shared for _, _, is_shared in groups)
    if connector_types == {"OR"}:
        return "any_of"
    if connector_types == {"AND"} and not has_alternative_group:
        return "all_of"
    if not connector_types and has_alternative_group and len(groups) == 1:
        return "any_of"
    if connector_types or has_alternative_group:
        return "mixed_needs_verification"
    return "all_of"


def course_header_code(lines, index):
    """Return a header code even when its title and units wrap onto new lines."""
    line = lines[index][1]
    complete_header = COURSE_HEADER_PATTERN.match(line)
    if complete_header:
        return normalize_course_code(complete_header.group("code"))

    start = COURSE_HEADER_START_PATTERN.match(line)
    if not start:
        return None
    if start.group("title").startswith((":", "/", "&")):
        return None

    # Some Bulletin headings wrap as:
    #   BITS F429 Nanotechnology for Renewable Energy
    #   and Environment
    #   3 1 4
    for look_ahead in range(index + 1, min(index + 3, len(lines))):
        next_line = lines[look_ahead][1]
        if COURSE_HEADER_START_PATTERN.match(next_line):
            break
        if UNITS_ONLY_PATTERN.fullmatch(next_line):
            return normalize_course_code(start.group("code"))
    return None


def bulletin_course_entries(pdf_path=BULLETIN_PATH):
    """Split the supplied Bulletin course-description pages into course entries."""
    reader = PdfReader(pdf_path)
    entries = []
    current = None
    lines = []

    for page_number in range(
        BULLETIN_FIRST_COURSE_PAGE, BULLETIN_LAST_COURSE_PAGE + 1
    ):
        page_text = reader.pages[page_number - 1].extract_text() or ""
        for original_line in page_text.splitlines():
            line = clean(original_line)
            if line:
                lines.append((page_number, line))

    for index, (page_number, line) in enumerate(lines):
        header_code = course_header_code(lines, index)
        if header_code:
            if current:
                entries.append(current)
            current = {
                "course_code": header_code,
                "page": page_number,
                "lines": [],
            }
        elif current:
            current["lines"].append((page_number, line))

    if current:
        entries.append(current)
    return entries


def parse_bulletin_prerequisites(pdf_path=BULLETIN_PATH):
    """Return only explicitly labelled prerequisites containing course codes."""
    records = {}

    for entry in bulletin_course_entries(pdf_path):
        prerequisite_lines = []
        source_page = None
        collecting = False

        for page_number, line in entry["lines"]:
            label = PREREQUISITE_LABEL_PATTERN.match(line)
            if label:
                collecting = True
                source_page = page_number
                if label.group("rest"):
                    prerequisite_lines.append(label.group("rest"))
                continue

            if collecting:
                # Equivalence and note fields are not prerequisite course codes.
                stop = re.search(
                    r"\b(?:Equivalent|Equivalents|Note)\s*:|\bThis course\b",
                    line,
                    re.I,
                )
                if stop:
                    before_stop = clean(line[: stop.start()])
                    if before_stop:
                        prerequisite_lines.append(before_stop)
                    break
                prerequisite_lines.append(line)

        if not prerequisite_lines:
            continue

        raw_text = clean(" ".join(prerequisite_lines))
        course_codes = course_codes_from_text(raw_text)
        course_codes = [
            code for code in course_codes if code != entry["course_code"]
        ]
        if not course_codes:
            # Topic-only statements such as "basic fluid mechanics" are not
            # formal course-code prerequisites and are intentionally skipped.
            continue

        rule = prerequisite_rule(raw_text, course_codes)
        record = {
            "course_code": entry["course_code"],
            "prerequisite_course_codes": course_codes,
            "rule": rule,
            "raw_text": raw_text,
            "status": (
                "needs_verification"
                if rule == "mixed_needs_verification"
                else "parsed"
            ),
            "source": {
                "document": relative_path(pdf_path),
                "page": source_page,
            },
        }

        # Repeated identical catalogue entries are harmless. If two entries
        # disagree, keep the first and visibly mark it for review.
        existing = records.get(entry["course_code"])
        if existing and existing["prerequisite_course_codes"] != course_codes:
            existing["status"] = "needs_verification"
            existing["note"] = "Conflicting prerequisite entries were found."
        else:
            records[entry["course_code"]] = record

    return records


def parse_timetable_courses(pdf_path=TIMETABLE_PATH):
    """Return courses with at least one non-cancelled timetable listing."""
    reader = PdfReader(pdf_path)
    offered = set()

    for page_number in range(
        TIMETABLE_FIRST_COURSE_PAGE, TIMETABLE_LAST_COURSE_PAGE + 1
    ):
        page_text = clean(reader.pages[page_number - 1].extract_text() or "")
        rows = list(TIMETABLE_ROW_PATTERN.finditer(page_text))
        for index, row in enumerate(rows):
            end = rows[index + 1].start() if index + 1 < len(rows) else len(page_text)
            row_text = page_text[row.end() : end]
            lecture_sections = list(
                re.finditer(r"\bL\d+\s+(?P<instructor>\S+)", row_text, re.I)
            )
            has_active_section = not lecture_sections or any(
                section.group("instructor").upper() != "CANCLED"
                for section in lecture_sections
            )
            if has_active_section:
                offered.add(normalize_course_code(row.group("code")))

    return sorted(offered)


def value_of(fact):
    """Read a value from the fact objects created by parse_handouts.py."""
    return fact.get("value") if isinstance(fact, dict) else fact


def flatten_handout(record):
    """Turn one verbose handout record into a small query-friendly record."""
    course = record["course"]
    primary_code = value_of(course.get("primary_code"))
    alternate_codes = value_of(course.get("alternate_codes")) or []
    return {
        "course_code": primary_code,
        "alternate_codes": alternate_codes,
        "title": value_of(course.get("title")),
        "instructor_in_charge": value_of(course.get("instructor_in_charge")),
        "description": value_of(course.get("description")),
        "objectives": value_of(course.get("objectives")),
        "handout_prerequisites_raw": value_of(course.get("prerequisites_raw")),
        "handout_sources": [record["document"]["path"]],
        "validation": {
            "status": record["validation"]["status"],
            "issues": list(record["validation"]["issues"]),
        },
    }


def combine_duplicate_handouts(courses):
    """Keep one catalogue record per primary course code."""
    combined = {}

    for course in courses:
        code = course["course_code"]
        if not code:
            continue
        if code not in combined:
            combined[code] = course
            continue

        current = combined[code]
        current["alternate_codes"] = sorted(
            set(current["alternate_codes"] + course["alternate_codes"])
        )
        current["handout_sources"] = sorted(
            set(current["handout_sources"] + course["handout_sources"])
        )
        current["validation"]["issues"] = sorted(
            set(
                current["validation"]["issues"]
                + course["validation"]["issues"]
            )
        )
        if current["validation"]["issues"]:
            current["validation"]["status"] = "needs_verification"

        # Prefer a non-empty value if the first duplicate was missing it.
        for field in [
            "title",
            "instructor_in_charge",
            "description",
            "objectives",
            "handout_prerequisites_raw",
        ]:
            if not current[field] and course[field]:
                current[field] = course[field]

    return list(combined.values())


def build_catalog(
    handout_records,
    bulletin_prerequisites,
    timetable_codes,
    course_categories=None,
):
    """Attach rules, programme categories, and availability to each course."""
    courses = combine_duplicate_handouts(
        [flatten_handout(record) for record in handout_records]
    )
    offered = set(timetable_codes)
    course_categories = course_categories or {}

    for course in courses:
        possible_codes = [course["course_code"], *course["alternate_codes"]]
        course["offered_this_sem"] = any(code in offered for code in possible_codes)

        classifications = []
        for code in possible_codes:
            for classification in course_categories.get(code, []):
                if not any(
                    item["programme"] == classification["programme"]
                    and item["category"] == classification["category"]
                    for item in classifications
                ):
                    classifications.append(classification)
        course["programme_classifications"] = sorted(
            classifications,
            key=lambda item: (item["programme"], item["category"]),
        )

        matches = [
            bulletin_prerequisites[code]
            for code in possible_codes
            if code in bulletin_prerequisites
        ]
        if matches:
            course["formal_prerequisites"] = matches[0]
            if matches[0]["status"] == "needs_verification":
                course["validation"]["status"] = "needs_verification"
                course["validation"]["issues"].append(
                    "formal_prerequisite_rule_needs_verification"
                )
        else:
            course["formal_prerequisites"] = {
                "course_code": course["course_code"],
                "prerequisite_course_codes": [],
                "rule": "none_listed_in_bulletin",
                "raw_text": None,
                "status": "not_found",
                "source": None,
            }

        course["validation"]["issues"] = sorted(
            set(course["validation"]["issues"])
        )

    return sorted(courses, key=lambda item: item["course_code"])


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False))


def main():
    bulletin_prerequisites = parse_bulletin_prerequisites()
    category_output = parse_course_categories()
    category_index = {
        record["course_code"]: record["classifications"]
        for record in category_output["courses"]
    }
    timetable_codes = parse_timetable_courses()
    handout_records = json.loads(HANDOUTS_PATH.read_text())
    courses = build_catalog(
        handout_records,
        bulletin_prerequisites,
        timetable_codes,
        category_index,
    )

    bulletin_output = {
        "source": relative_path(BULLETIN_PATH),
        "page_range": [
            BULLETIN_FIRST_COURSE_PAGE,
            BULLETIN_LAST_COURSE_PAGE,
        ],
        "records": sorted(
            bulletin_prerequisites.values(),
            key=lambda item: item["course_code"],
        ),
    }
    timetable_output = {
        "source": relative_path(TIMETABLE_PATH),
        "semester": "First Semester 2026-2027",
        "page_range": [
            TIMETABLE_FIRST_COURSE_PAGE,
            TIMETABLE_LAST_COURSE_PAGE,
        ],
        "definition": (
            "A course is offered_this_sem when the Coursewise Timetable has "
            "at least one listing that is not marked CANCLED."
        ),
        "course_codes": timetable_codes,
    }
    catalog_output = {
        "metadata": {
            "semester": "First Semester 2026-2027",
            "bulletin_assumption": (
                "Prerequisites from the supplied 2025-2026 Bulletin are used "
                "for the supplied 2026-2027 semester data."
            ),
            "sources": {
                "handouts": relative_path(HANDOUTS_PATH),
                "bulletin": relative_path(BULLETIN_PATH),
                "timetable": relative_path(TIMETABLE_PATH),
                "course_categories": "processed/course_categories.json",
            },
            "category_rules": category_output["metadata"].get("rules", []),
            "first_year_note": category_output["metadata"].get(
                "first_year_note"
            ),
            "counts": {
                "handout_records": len(handout_records),
                "unique_courses": len(courses),
                "bulletin_prerequisite_records": len(bulletin_prerequisites),
                "timetable_course_codes": len(timetable_codes),
                "courses_offered_this_sem": sum(
                    course["offered_this_sem"] for course in courses
                ),
                "courses_with_formal_prerequisites": sum(
                    bool(
                        course["formal_prerequisites"][
                            "prerequisite_course_codes"
                        ]
                    )
                    for course in courses
                ),
                "courses_with_programme_classifications": sum(
                    bool(course["programme_classifications"])
                    for course in courses
                ),
            },
        },
        "courses": courses,
    }

    write_json(BULLETIN_OUTPUT, bulletin_output)
    write_json(
        PROJECT_DIR / "processed/course_categories.json",
        category_output,
    )
    write_json(TIMETABLE_OUTPUT, timetable_output)
    write_json(CATALOG_OUTPUT, catalog_output)

    print(
        f"Bulletin: {len(bulletin_prerequisites)} formal prerequisite records"
    )
    print(f"Timetable: {len(timetable_codes)} active course codes")
    print(
        f"Catalogue: {len(courses)} unique courses; "
        f"{catalog_output['metadata']['counts']['courses_offered_this_sem']} "
        "offered this semester"
    )
    print(f"Output: {CATALOG_OUTPUT}")


if __name__ == "__main__":
    main()
