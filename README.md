# BITS Course Recommender - Data Pipeline

This repository currently builds one simple JSON course catalogue. It does not
use an LLM yet.

## What each source provides

- Course handouts: code, title, instructor, description, objectives and raw
  handout prerequisite wording.
- Bulletin: only explicitly labelled formal prerequisite course codes.
- Bulletin programme tables: programme-specific CDC/DEL lists and the common
  Humanities-elective pool.
- Timetable: whether a course has at least one non-cancelled listing this
  semester.

## Run the pipeline

Install the PDF-processing dependencies:

```bash
python -m pip install -r requirements.txt
```

Parse all handouts:

```bash
python parse_handouts.py
```

Parse the Bulletin and timetable, then merge everything:

```bash
python build_course_catalog.py
```

Run the checks:

```bash
python -m unittest -v test_handout_parser.py test_course_catalog.py
```

## Outputs

- `processed/handout_identities.json`: raw structured handout records.
- `processed/bulletin_prerequisites.json`: formal prerequisite relationships.
- `processed/course_categories.json`: programme-specific CDC/DEL mappings and
  the common HUEL pool.
- `processed/timetable_courses.json`: currently active timetable course codes.
- `processed/course_catalog.json`: the final combined, query-friendly file.

