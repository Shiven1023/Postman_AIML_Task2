"""Small first experiment: turn one BITS course handout into structured JSON.

Run from the project folder with:
    python process_cs_u407.py

Dependency:
    pip install pypdf
"""

import json
import re
from pathlib import Path

from pypdf import PdfReader


PROJECT_DIR = Path(__file__).parent
PDF_PATH = PROJECT_DIR / "data/handouts/191_CS_U407.pdf"
OUTPUT_PATH = PROJECT_DIR / "processed/cs_f407.json"
SOURCE_NAME = "data/handouts/191_CS_U407.pdf"


def clean(text):
    """Replace repeated whitespace with a single space."""
    return " ".join(text.split()).strip()


def extract_between(text, start, end):
    """Return text found between two headings, or None when it is not found."""
    match = re.search(start + r"(.*?)" + end, text, flags=re.IGNORECASE | re.DOTALL)
    return clean(match.group(1)) if match else None


def fact(value, page, status="verified", note=None):
    """Attach traceability and verification information to an extracted value."""
    result = {
        "value": value,
        "status": status,
        "source": {"document": SOURCE_NAME, "page": page} if page else None,
    }
    if note:
        result["note"] = note
    return result


def extract_component(page_text, name, start_pattern, end_pattern=None):
    """Extract one row of the evaluation table on page 4."""
    # PDF tables often split one visual row across several extracted lines.
    # Normalising the page first lets the patterns follow the visual wording.
    page_text = clean(page_text)
    if end_pattern:
        chunk = extract_between(page_text, start_pattern, end_pattern)
    else:
        match = re.search(start_pattern + r"(.*)", page_text, flags=re.IGNORECASE | re.DOTALL)
        chunk = clean(match.group(1)) if match else None

    if not chunk:
        return None

    duration_match = re.search(r"(Take Home|\d+\s*Mins(?:\s+each)?|\d+\s*Hours?)", chunk, re.I)
    weight_match = re.search(r"(\d+)\s*%", chunk)
    date_match = re.search(r"([A-Z][a-z]+\s+\d{1,2},\s+\d{4})", chunk)

    timing = date_match.group(1) if date_match else None
    if re.search(r"Continuous Evaluation", chunk, re.I):
        timing = "Continuous Evaluation (submissions and Viva)"
    elif re.search(r"In lecture", chunk, re.I):
        timing = "In lecture"

    return {
        "name": name,
        "duration": clean(duration_match.group(1)) if duration_match else None,
        "weight_percent": int(weight_match.group(1)) if weight_match else None,
        "timing": timing,
        "source": {"document": SOURCE_NAME, "page": 4},
        "status": "verified",
    }


def main():
    reader = PdfReader(PDF_PATH)
    pages = [(page.extract_text() or "") for page in reader.pages]
    page_1 = pages[0]
    page_4 = pages[3]
    all_text = "\n".join(pages)

    course_number_match = re.search(r"Course No\.\s*:\s*([^\n]+)", page_1, re.I)
    course_number_text = course_number_match.group(1) if course_number_match else ""
    course_codes = [
        f"{match.group(1)} {match.group(2)}"
        for match in re.finditer(r"\b([A-Z]{2,5})\s+([A-Z]\d{3})\b", course_number_text)
    ]

    title_match = re.search(r"Course Title\s*:\s*([^\n]+)", page_1, re.I)
    instructor_match = re.search(r"Instructor-in-charge\s*:\s*([^\n(]+)", page_1, re.I)

    description = extract_between(page_1, r"Course Description", r"Text Book:")
    topic_match = re.search(
        r"topics that we will cover:\s*(.*?)\.",
        description or "",
        flags=re.IGNORECASE | re.DOTALL,
    )
    topics = []
    if topic_match:
        topic_text = re.sub(r",?\s+and\s+", ", ", topic_match.group(1), flags=re.I)
        topics = [clean(item) for item in topic_text.split(",") if clean(item)]

    components = [
        extract_component(
            page_4,
            "MidSem Test",
            r"MidSem Test \(Closed Book\)",
            r"Building Geospatial Intelligent Agents Project",
        ),
        extract_component(
            page_4,
            "Building Geospatial Intelligent Agents Project",
            r"Building Geospatial Intelligent Agents Project: Phase-wise Assignment\(s\)",
            r"Quizes \(Open/Closed Book\)",
        ),
        extract_component(
            page_4,
            "Quizzes",
            r"Quizes \(Open/Closed Book\)",
            r"Comprehensive Exam",
        ),
        extract_component(
            page_4,
            "Comprehensive Exam",
            r"Comprehensive Exam \(Closed book\)",
            r"Assignment\(s\):",
        ),
    ]
    components = [component for component in components if component]

    project_details = extract_between(page_4, r"Assignment\(s\):", r"Notices:")
    makeup_policy = extract_between(page_4, r"Makeup Policy:", r"Plagiarism Policy:")

    attendance_present = bool(re.search(r"Attendance Policy", all_text, re.I))
    prerequisite_match = re.search(
        r"Pre[- ]?requisites?\s*:\s*([^\n]+)", all_text, flags=re.IGNORECASE
    )

    weight_total = sum(
        component["weight_percent"]
        for component in components
        if component["weight_percent"] is not None
    )

    record = {
        "document": {
            "path": SOURCE_NAME,
            "page_count": len(pages),
            "semester": "First Semester 2026-2027",
            "document_type": "Course Handout Part II",
        },
        "course": {
            "primary_code": fact(course_codes[0] if course_codes else None, 1),
            "alternate_codes": fact(course_codes[1:], 1),
            "title": fact(clean(title_match.group(1)) if title_match else None, 1),
            "instructor_in_charge": fact(
                clean(instructor_match.group(1)) if instructor_match else None, 1
            ),
            "description": fact(description, 1),
            "topics": fact(topics, 1),
            "prerequisites": (
                fact(clean(prerequisite_match.group(1)), None)
                if prerequisite_match
                else fact(
                    None,
                    None,
                    "needs_verification",
                    "No explicit course-code prerequisite was found in this handout.",
                )
            ),
        },
        "handout_properties": {
            "evaluation_components": fact(components, 4),
            "has_midsem": fact(any(c["name"] == "MidSem Test" for c in components), 4),
            "has_comprehensive_exam": fact(
                any(c["name"] == "Comprehensive Exam" for c in components), 4
            ),
            "has_project": fact(
                any("Project" in c["name"] for c in components), 4
            ),
            "project_details": fact(project_details, 4),
            "attendance_policy": (
                fact("Attendance policy heading found", None)
                if attendance_present
                else fact(
                    None,
                    None,
                    "needs_verification",
                    "The handout does not explicitly state an attendance policy.",
                )
            ),
            "makeup_policy": fact(makeup_policy, 4),
        },
        "validation": {
            "evaluation_weight_total": weight_total,
            "evaluation_weight_check": "passed" if weight_total == 100 else "failed",
            "warnings": [
                "Prerequisites require verification from the bulletin or regulations.",
                "Attendance requirements could not be verified from this handout.",
            ],
        },
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(record, indent=2, ensure_ascii=False))
    print(f"Created {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
