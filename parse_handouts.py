"""Extract common identity and descriptive fields from BITS course handouts.

This is the second learning step after ``process_cs_u407.py``.  It deliberately
does NOT parse evaluation tables yet.

Run all handouts:
    python parse_handouts.py

Run selected handouts:
    python parse_handouts.py data/handouts/002_BIO_F101.pdf
"""

import argparse
import json
import logging
import re
from pathlib import Path

from pypdf import PdfReader


PROJECT_DIR = Path(__file__).parent
HANDOUT_DIR = PROJECT_DIR / "data/handouts"
DEFAULT_OUTPUT = PROJECT_DIR / "processed/handout_identities.json"

# Some supplied PDFs contain slightly damaged internal references.  pypdf can
# still read them, so hide those low-level warnings from normal program output.
logging.getLogger("pypdf").setLevel(logging.ERROR)


COURSE_NUMBER_LABELS = [r"Course\s*No\.?", r"Course\s*Number", r"Course\s*Code"]
COURSE_TITLE_LABELS = [
    r"Course\s*Title",
    r"Course\s*Name",
    r"Name\s+of\s+the\s+Course",
]
COMBINED_COURSE_LABELS = [r"Course\s*(?:Number|No\.?)\s*(?:&|and)\s*Title"]
INSTRUCTOR_LABELS = [
    r"Instructor\s*[\-–—]?\s*in\s*[\-–—]?\s*charge",
    r"Instructor\s*-?\s*Incharge",
    r"Course\s*Coordinator",
    r"Instructors?\s*\(lec\)",
    r"Instructors?",
]

DESCRIPTION_HEADINGS = [
    r"(?:\d+\.\s*)?Course\s+Description",
    r"(?:\d+\.\s*)?Catalog(?:ue)?\s+Description",
]
OBJECTIVE_HEADINGS = [
    r"(?:\d+\.\s*)?Scope\s*(?:&|and)?\s*Objectives?(?:\s+of\s+the\s+Course)?",
    r"(?:\d+\.\s*)?Course\s+Objectives?",
    r"(?:\d+\.\s*)?Aims?\s+and\s+learning\s+objectives?",
]
PREREQUISITE_HEADINGS = [
    r"Pre[- ]?requisites?\*?",
]

# These headings tell the section extractor where the current section ends.
SECTION_STOPS = [
    *DESCRIPTION_HEADINGS,
    *OBJECTIVE_HEADINGS,
    *PREREQUISITE_HEADINGS,
    r"(?:\d+\.\s*)?Text\s*Books?",
    r"(?:\d+\.\s*)?Reference\s*Books?",
    r"Lecture\s+Plan",
    r"Evaluation\s+(?:Scheme|Components?|Plan|Pattern)",
    r"Assessment\s+(?:Scheme|Components?|Plan|Pattern)",
    r"Course\s+Learning\s+Objectives?",
    r"Course\s+Learning\s+Outcomes?",
]


def clean(text):
    """Collapse PDF line breaks and repeated spaces into normal spaces."""
    return " ".join((text or "").split()).strip()


def relative_source(path):
    """Store a portable path relative to this project."""
    try:
        return str(path.resolve().relative_to(PROJECT_DIR.resolve()))
    except ValueError:
        return str(path)


def fact(value, path, page=None, status="extracted", heading=None, note=None):
    """Represent one value together with provenance and extraction status."""
    result = {
        "value": value,
        "status": status,
        "source": (
            {"document": relative_source(path), "page": page}
            if page is not None
            else None
        ),
    }
    if heading:
        result["matched_heading"] = heading
    if note:
        result["note"] = note
    return result


def alternatives(patterns):
    """Combine several acceptable heading patterns into one regex group."""
    return "(?:" + "|".join(patterns) + ")"


def find_labeled_value(pages, labels, stop_labels):
    """Find a value after a heading, allowing either a newline or next heading to end it."""
    label_pattern = alternatives(labels)
    stop_pattern = alternatives(stop_labels)

    for page_number, page_text in enumerate(pages, start=1):
        pattern = (
            label_pattern
            + r"\s*(?:[:.-]\s*)?(.+?)"
            + r"(?=\n|"
            + stop_pattern
            + r"\s*(?:[:.-]\s*)?|$)"
        )
        match = re.search(pattern, page_text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            value = clean(match.group(1))
            if value:
                heading = clean(match.group(0)[: match.start(1) - match.start(0)])
                return value, page_number, heading

        # Some PDFs flatten a complete visual page into one extracted line.
        flat_text = clean(page_text)
        flat_pattern = (
            label_pattern
            + r"\s*(?:[:.-]\s*)?(.+?)"
            + r"(?="
            + stop_pattern
            + r"\s*(?:[:.-]\s*)?|$)"
        )
        match = re.search(flat_pattern, flat_text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            value = clean(match.group(1))
            if value:
                heading = clean(match.group(0)[: match.start(1) - match.start(0)])
                return value, page_number, heading

    return None, None, None


def find_section(pages, start_headings):
    """Extract a named section from its heading until the next known heading."""
    start_pattern = alternatives(start_headings)
    stop_pattern = alternatives(SECTION_STOPS)

    for page_number, page_text in enumerate(pages, start=1):
        flat_text = clean(page_text)
        start = re.search(start_pattern + r"\s*:??\s*", flat_text, re.IGNORECASE)
        if not start:
            continue

        remaining = flat_text[start.end():]
        stop = re.search(stop_pattern, remaining, re.IGNORECASE)
        value = clean(remaining[: stop.start()] if stop else remaining)
        if value:
            return value, page_number, clean(start.group(0))

    return None, None, None


def codes_from_text(value):
    """Return normalized course codes such as CS F407 from arbitrary spacing."""
    if not value:
        return []
    value = clean(value).upper()
    codes = []

    # Handles a shared suffix such as "CS/SS G 527".
    shared = re.search(
        r"\b((?:[A-Z]{2,6}\s*/\s*)+[A-Z]{2,6})\s+([A-Z])\s*(\d{3}[A-Z]?)\b",
        value,
    )
    if shared:
        for department in re.split(r"\s*/\s*", shared.group(1)):
            codes.append(f"{department} {shared.group(2)}{shared.group(3)}")

    for match in re.finditer(r"\b([A-Z]{2,6})\s+([A-Z])\s*(\d{3}[A-Z]?)\b", value):
        codes.append(f"{match.group(1)} {match.group(2)}{match.group(3)}")
    return list(dict.fromkeys(codes))


def title_from_combined_field(value):
    """Split a field such as 'CS/SS G 527 Cloud Computing' into its title part."""
    value = clean(value)
    shared = re.match(
        r"(?:[A-Z]{2,6}\s*/\s*)*[A-Z]{2,6}\s+[A-Z]\s*\d{3}[A-Z]?\s+(.+)$",
        value,
        re.IGNORECASE,
    )
    return clean(shared.group(1)) if shared else None


def code_from_filename(path):
    """Use the normalized handout filename only as an explicitly labelled fallback."""
    match = re.match(r"\d+_([A-Z]{2,6})_([A-Z]\d{3}[A-Z]?)", path.stem.upper())
    return f"{match.group(1)} {match.group(2)}" if match else None


def find_semester(pages):
    """Find and normalize semester text from a handout header."""
    pattern = r"\b(FIRST|SECOND|I|II)\s+SEMESTER\s*[:,]?\s*(20\d{2})\s*[-–]\s*(\d{2,4})\b"
    for page_number, page_text in enumerate(pages, start=1):
        match = re.search(pattern, clean(page_text), re.IGNORECASE)
        if match:
            ending_year = match.group(3)
            if len(ending_year) == 2:
                ending_year = match.group(2)[:2] + ending_year
            semester_name = {
                "I": "First",
                "II": "Second",
                "FIRST": "First",
                "SECOND": "Second",
            }[match.group(1).upper()]
            value = f"{semester_name} Semester {match.group(2)}-{ending_year}"
            return value, page_number
    return None, None


def parse_handout(path):
    """Parse one PDF into a traceable identity/description record."""
    path = Path(path)
    reader = PdfReader(path)
    pages = [(page.extract_text() or "") for page in reader.pages]

    code_text, code_page, code_heading = find_labeled_value(
        pages,
        COURSE_NUMBER_LABELS,
        COURSE_TITLE_LABELS,
    )
    course_codes = codes_from_text(code_text)
    combined_text, combined_page, combined_heading = find_labeled_value(
        pages,
        COMBINED_COURSE_LABELS,
        INSTRUCTOR_LABELS + DESCRIPTION_HEADINGS + OBJECTIVE_HEADINGS,
    )
    if not course_codes and combined_text:
        course_codes = codes_from_text(combined_text)
        code_page = combined_page
        code_heading = combined_heading
    used_filename_fallback = False
    if not course_codes:
        fallback = code_from_filename(path)
        if fallback:
            course_codes = [fallback]
            used_filename_fallback = True

    title, title_page, title_heading = find_labeled_value(
        pages,
        COURSE_TITLE_LABELS,
        INSTRUCTOR_LABELS + DESCRIPTION_HEADINGS + OBJECTIVE_HEADINGS,
    )
    if not title and combined_text:
        title = title_from_combined_field(combined_text)
        title_page = combined_page
        title_heading = combined_heading
    instructor, instructor_page, instructor_heading = find_labeled_value(
        pages,
        INSTRUCTOR_LABELS,
        [
            r"Lab\.?\s*Instructor",
            r"Lecture\s+Instructors?",
            r"Instructors?\s+Name",
            r"Instructors?",
            *DESCRIPTION_HEADINGS,
            *OBJECTIVE_HEADINGS,
            r"(?:\d+\.\s*)?Text\s*Books?",
        ],
    )
    if instructor:
        # Contact details are separate facts later; keep this field to the person's name.
        instructor = clean(re.sub(r"\s*\(.*$", "", instructor))

    description, description_page, description_heading = find_section(
        pages, DESCRIPTION_HEADINGS
    )
    objectives, objectives_page, objectives_heading = find_section(
        pages, OBJECTIVE_HEADINGS
    )
    prerequisites, prerequisites_page, prerequisites_heading = find_section(
        pages, PREREQUISITE_HEADINGS
    )
    semester, semester_page = find_semester(pages)

    issues = []
    filename_code = code_from_filename(path)
    if not course_codes:
        issues.append("course_code_missing")
    elif used_filename_fallback:
        issues.append("course_code_from_filename_needs_pdf_verification")
    elif filename_code and filename_code not in course_codes:
        issues.append("course_code_conflicts_with_filename")
    if not title:
        issues.append("course_title_missing")
    elif len(title) > 160:
        issues.append("course_title_suspiciously_long")
    if not instructor:
        issues.append("instructor_missing")
    elif len(instructor) > 160:
        issues.append("instructor_suspiciously_long")
    if not description and not objectives:
        issues.append("description_and_objectives_missing")
    if not semester:
        issues.append("semester_missing")
    elif semester != "First Semester 2026-2027":
        issues.append("semester_differs_from_current_dataset")

    code_fact = (
        fact(
            course_codes[0],
            path,
            status="filename_fallback",
            note="Course code came from the filename and must be checked against the PDF.",
        )
        if used_filename_fallback
        else fact(course_codes[0] if course_codes else None, path, code_page, heading=code_heading)
    )

    return {
        "document": {
            "path": relative_source(path),
            "page_count": len(pages),
            "document_type": "Course Handout Part II",
            "semester": fact(semester, path, semester_page),
        },
        "course": {
            "primary_code": code_fact,
            "alternate_codes": fact(course_codes[1:], path, code_page, heading=code_heading),
            "title": fact(title, path, title_page, heading=title_heading),
            "instructor_in_charge": fact(
                instructor, path, instructor_page, heading=instructor_heading
            ),
            "description": fact(
                description, path, description_page, heading=description_heading
            ),
            "objectives": fact(
                objectives, path, objectives_page, heading=objectives_heading
            ),
            "prerequisites_raw": fact(
                prerequisites,
                path,
                prerequisites_page,
                status="needs_verification" if prerequisites else "not_found",
                heading=prerequisites_heading,
                note=(
                    "Raw prerequisite wording must be interpreted and checked against the bulletin."
                    if prerequisites
                    else "No explicit prerequisite section was found in this handout."
                ),
            ),
        },
        "validation": {
            "status": "passed" if not issues else "needs_verification",
            "issues": issues,
        },
    }


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument(
        "pdfs",
        nargs="*",
        type=Path,
        help="Optional handout PDFs. If omitted, every PDF in data/handouts is processed.",
    )
    argument_parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = argument_parser.parse_args()

    pdf_paths = args.pdfs or sorted(HANDOUT_DIR.glob("*.pdf"))
    records = []
    errors = []
    for path in pdf_paths:
        try:
            records.append(parse_handout(path))
        except Exception as error:
            errors.append({"document": relative_source(path), "error": str(error)})

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(records, indent=2, ensure_ascii=False))

    print(f"Processed {len(records)} handouts; {len(errors)} read errors.")
    print(f"Records: {args.output}")


if __name__ == "__main__":
    main()
