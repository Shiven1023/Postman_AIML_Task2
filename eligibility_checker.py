"""Deterministically check whether one course can satisfy a requested category.
Run:
    python eligibility_checker.py "CS F407" DEL
Supported categories are CDC, DEL, and HUEL.
"""

import argparse
import json
import re
from pathlib import Path


PROJECT_DIR = Path(__file__).parent
PROFILE_PATH = PROJECT_DIR / "user_profile.json"
CATALOG_PATH = PROJECT_DIR / "processed/course_catalog.json"

COMMON_HUMANITIES_SCOPE = "All First-Degree Programmes"
SUPPORTED_CATEGORIES = {"CDC", "DEL", "HUEL"}


def normalize_course_code(value):
    """Normalize values such as ``cs f407`` to ``CS F407``."""
    value = " ".join(str(value or "").upper().split())
    match = re.fullmatch(
        r"([A-Z]{2,6})\s+([A-Z]{1,2})\s*(\d{3}[A-ZT]?(?:-\d+)?)",
        value,
    )
    if not match:
        return value
    return f"{match.group(1)} {match.group(2)}{match.group(3)}"


def programme_key(value):
    """Make programme-name comparisons tolerant of punctuation and B.E./M.Sc."""
    key = re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()
    for prefix in ("B E ", "M SC ", "B PHARM "):
        if key.startswith(prefix):
            key = key[len(prefix) :]
            break
    if key.endswith(" PROGRAMME"):
        key = key[: -len(" PROGRAMME")]
    return key.strip()


def check(name, status, reason, **details):
    result = {"name": name, "status": status, "reason": reason}
    if details:
        result["details"] = details
    return result


def find_course(catalog, requested_code):
    """Find a course using its primary or alternate code."""
    requested_code = normalize_course_code(requested_code)
    for course in catalog.get("courses", []):
        codes = [course.get("course_code"), *course.get("alternate_codes", [])]
        normalized = {normalize_course_code(code) for code in codes if code}
        if requested_code in normalized:
            return course
    return None


def first_year_check(profile):
    semester = profile.get("current_semester")
    if not isinstance(semester, int):
        return check(
            "first_year_scope",
            "UNKNOWN",
            "current_semester must be filled with an integer before checking eligibility.",
        )
    if semester in {1, 2}:
        return check(
            "first_year_scope",
            "FAIL",
            "The MVP does not support first-year course selection; use the programme's Year-I chart.",
        )
    return check(
        "first_year_scope",
        "PASS",
        f"Semester {semester} is outside the MVP's first-year restriction.",
    )


def already_taken_check(profile, course):
    course_codes = {
        normalize_course_code(course.get("course_code")),
        *{
            normalize_course_code(code)
            for code in course.get("alternate_codes", [])
        },
    }
    completed = {
        normalize_course_code(code)
        for code in (profile.get("completed_courses") or [])
    }
    current = {
        normalize_course_code(code)
        for code in (profile.get("current_courses") or [])
    }

    completed_matches = sorted(course_codes & completed)
    current_matches = sorted(course_codes & current)
    if completed_matches:
        return check(
            "already_taken",
            "FAIL",
            "The course has already been completed.",
            matching_codes=completed_matches,
        )
    if current_matches:
        return check(
            "already_taken",
            "FAIL",
            "The student is already taking this course.",
            matching_codes=current_matches,
        )
    return check(
        "already_taken",
        "PASS",
        "The course is not present in completed_courses or current_courses.",
    )


def prerequisite_check(profile, course):
    prerequisite = course.get("formal_prerequisites") or {}
    required = {
        normalize_course_code(code)
        for code in prerequisite.get("prerequisite_course_codes", [])
    }
    completed = {
        normalize_course_code(code)
        for code in (profile.get("completed_courses") or [])
    }
    rule = prerequisite.get("rule", "none_listed_in_bulletin")

    if not required or rule == "none_listed_in_bulletin":
        return check(
            "prerequisites",
            "PASS",
            "No code-based formal prerequisite was listed in the supplied Bulletin.",
        )
    if rule == "mixed_needs_verification":
        return check(
            "prerequisites",
            "UNKNOWN",
            "The extracted prerequisite rule is mixed and requires manual verification.",
            required_courses=sorted(required),
        )
    if rule == "any_of":
        satisfied = sorted(required & completed)
        if satisfied:
            return check(
                "prerequisites",
                "PASS",
                "At least one permitted prerequisite has been completed.",
                completed_prerequisites=satisfied,
            )
        return check(
            "prerequisites",
            "FAIL",
            "At least one of the listed prerequisite courses must be completed.",
            required_courses=sorted(required),
        )
    if rule in {"single", "all_of"}:
        missing = sorted(required - completed)
        if not missing:
            return check(
                "prerequisites",
                "PASS",
                "All required prerequisite courses have been completed.",
                required_courses=sorted(required),
            )
        return check(
            "prerequisites",
            "FAIL",
            "One or more prerequisite courses have not been completed.",
            missing_courses=missing,
        )
    return check(
        "prerequisites",
        "UNKNOWN",
        f"Unsupported prerequisite rule: {rule}",
    )


def timetable_check(course):
    if course.get("offered_this_sem") is True:
        return check(
            "timetable",
            "PASS",
            "The course has an active listing in the current-semester timetable.",
        )
    return check(
        "timetable",
        "FAIL",
        "The course does not have an active listing in the current-semester timetable.",
    )


def category_check(profile, course, requested_category):
    category = str(requested_category or "").upper().strip()
    if category not in SUPPORTED_CATEGORIES:
        return check(
            "course_category",
            "UNKNOWN",
            "Choose one supported category: CDC, DEL, or HUEL.",
            requested_category=category or None,
        )

    degree = profile.get("degree")
    if not degree:
        return check(
            "course_category",
            "UNKNOWN",
            "The student's degree must be filled before checking CDC/DEL/HUEL applicability.",
        )

    classifications = course.get("programme_classifications", [])
    own_programme = [
        item
        for item in classifications
        if programme_key(item.get("programme")) == programme_key(degree)
    ]
    common_huel = any(
        item.get("programme") == COMMON_HUMANITIES_SCOPE
        and item.get("category") == "HUEL"
        for item in classifications
    )

    if category == "HUEL":
        if not common_huel:
            return check(
                "course_category",
                "FAIL",
                "The course is not listed in the common Humanities-elective pool.",
            )
        own_discipline_categories = sorted(
            {
                item.get("category")
                for item in own_programme
                if item.get("category") in {"CDC", "DEL"}
            }
        )
        if own_discipline_categories:
            return check(
                "course_category",
                "FAIL",
                "A course from the student's own discipline cannot count as a HUEL.",
                own_discipline_categories=own_discipline_categories,
            )
        return check(
            "course_category",
            "PASS",
            "The course is in the common HUEL pool and is not classified as this programme's CDC or DEL.",
        )

    matching = [
        item
        for item in own_programme
        if item.get("category") == category
    ]
    if matching:
        return check(
            "course_category",
            "PASS",
            f"The course is listed as a {category} for {degree}.",
        )

    applicable = sorted(
        {
            item.get("category")
            for item in own_programme
            if item.get("category")
        }
    )
    return check(
        "course_category",
        "FAIL",
        f"The course is not listed as a {category} for {degree}.",
        categories_for_programme=applicable,
    )


def evaluate_course(profile, course, requested_category):
    """Run every deterministic check and return one structured result."""
    checks = [
        first_year_check(profile),
        already_taken_check(profile, course),
        prerequisite_check(profile, course),
        timetable_check(course),
        category_check(profile, course, requested_category),
    ]

    statuses = {item["status"] for item in checks}
    if "FAIL" in statuses:
        overall = "INELIGIBLE"
    elif "UNKNOWN" in statuses:
        overall = "NEEDS_VERIFICATION"
    else:
        overall = "ELIGIBLE"

    return {
        "course_code": course.get("course_code"),
        "title": course.get("title"),
        "requested_category": str(requested_category).upper(),
        "overall_status": overall,
        "checks": checks,
    }


def relevance_score(course, topics):
    """Return a small explainable keyword score for the requested topics."""
    title = str(course.get("title") or "").lower()
    body = " ".join(
        str(course.get(field) or "").lower()
        for field in ("description", "objectives")
    )
    all_text = f"{title} {body}"

    score = 0
    matched_topics = []
    for raw_topic in topics:
        topic = " ".join(str(raw_topic).lower().split())
        words = re.findall(r"[a-z0-9]+", topic)
        if not words:
            continue

        exact_match = topic in all_text
        all_words_match = all(word in all_text for word in words)
        if not (exact_match or all_words_match):
            continue

        matched_topics.append(str(raw_topic))
        score += 5 if exact_match else len(words)
        if topic in title:
            score += 5
        else:
            score += sum(2 for word in words if word in title)

    return score, matched_topics


def recommend_courses(profile, catalog, topics, requested_category=None, limit=5):
    """Return relevant courses only after deterministic eligibility checks."""
    semester = profile.get("current_semester")
    if not isinstance(semester, int):
        raise ValueError("Fill current_semester before requesting recommendations.")
    if semester in {1, 2}:
        raise ValueError(
            "The MVP does not support first-year course selection; "
            "use the programme's Year-I chart."
        )
    if not profile.get("degree"):
        raise ValueError("Fill degree before requesting recommendations.")
    if not topics:
        raise ValueError("Include a topic, for example machine learning.")

    categories = (
        [str(requested_category).upper()]
        if requested_category
        else ["CDC", "DEL", "HUEL"]
    )
    recommendations = []

    for course in catalog.get("courses", []):
        if course.get("validation", {}).get("status") != "passed":
            continue

        eligible_categories = []
        for category in categories:
            result = evaluate_course(profile, course, category)
            if result["overall_status"] == "ELIGIBLE":
                eligible_categories.append(category)

        if not eligible_categories:
            continue

        score, matched_topics = relevance_score(course, topics)
        if score == 0:
            continue

        recommendations.append(
            {
                "course_code": course.get("course_code"),
                "title": course.get("title"),
                "eligible_categories": eligible_categories,
                "match_score": score,
                "matched_topics": matched_topics,
                "handout_sources": course.get("handout_sources", []),
                "category_sources": [
                    item.get("source")
                    for item in course.get("programme_classifications", [])
                    if item.get("category") in eligible_categories
                    and item.get("source")
                    and (
                        programme_key(item.get("programme"))
                        == programme_key(profile.get("degree"))
                        or (
                            item.get("category") == "HUEL"
                            and item.get("programme") == COMMON_HUMANITIES_SCOPE
                        )
                    )
                ],
            }
        )

    recommendations.sort(
        key=lambda item: (
            -item["match_score"],
            item.get("title") or "",
            item.get("course_code") or "",
        )
    )
    return recommendations[:limit]


def load_json(path):
    return json.loads(path.read_text())


def print_result(result):
    print(f"Course: {result['course_code']} - {result.get('title') or 'Unknown title'}")
    print(f"Requested category: {result['requested_category']}")
    print(f"Overall: {result['overall_status']}")
    for item in result["checks"]:
        print(f"- [{item['status']}] {item['name']}: {item['reason']}")
        if item.get("details"):
            print(f"  Details: {json.dumps(item['details'], ensure_ascii=False)}")


def print_recommendations(recommendations):
    if not recommendations:
        print("No eligible courses matched the requested topic.")
        return

    print("Recommendations:")
    for number, item in enumerate(recommendations, start=1):
        categories = ", ".join(item["eligible_categories"])
        topics = ", ".join(item["matched_topics"])
        print(
            f"{number}. {item['course_code']} - "
            f"{item.get('title') or 'Unknown title'}"
        )
        print(f"   Eligible as: {categories}")
        print(f"   Topic match: {topics}")
        print("   Why: academically eligible and its handout text matches the request.")
        if item["handout_sources"]:
            print(f"   Source: {item['handout_sources'][0]}")
        if item["category_sources"]:
            source = item["category_sources"][0]
            print(
                f"   Category source: {source.get('document')}, "
                f"page {source.get('page')}"
            )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("course_code", help='Course code, for example "CS F407"')
    parser.add_argument("category", help="CDC, DEL, or HUEL")
    parser.add_argument("--profile", type=Path, default=PROFILE_PATH)
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    args = parser.parse_args()

    profile = load_json(args.profile)
    catalog = load_json(args.catalog)
    course = find_course(catalog, args.course_code)
    if not course:
        raise SystemExit(f"Course not found in catalogue: {args.course_code}")

    print_result(evaluate_course(profile, course, args.category))


if __name__ == "__main__":
    main()
