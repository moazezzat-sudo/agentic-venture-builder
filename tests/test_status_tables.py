"""README "What works and what is mocked" and ARCHITECTURE.md "Built vs. stubbed" must stay identical."""

import re
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
STATUSES = {"**Working**", "**MOCKED**", "**STUBBED**"}


def table(path: Path, heading: str) -> list[str]:
    """The markdown table rows (header included) that follow a heading."""
    text = path.read_text(encoding="utf-8")
    assert heading in text, f"{path.name} has no {heading!r}"
    lines = text[text.index(heading):].splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("| Phase |"))
    end = start
    while end < len(lines) and lines[end].startswith("|"):
        end += 1
    return [line.strip() for line in lines[start:end]]


def test_architecture_copies_the_readme_status_table_word_for_word():
    readme = table(ROOT_DIR / "README.md", "## What works and what is mocked")
    architecture = table(ROOT_DIR / "ARCHITECTURE.md", "## Built vs. stubbed")
    assert readme == architecture


def test_every_row_has_one_allowed_status_and_working_rows_name_a_test():
    rows = table(ROOT_DIR / "README.md", "## What works and what is mocked")[2:]
    assert rows, "the status table has no rows"
    for row in rows:
        cells = [c.strip() for c in row.strip("|").split("|")]
        assert len(cells) == 4, row
        assert cells[2] in STATUSES, f"status must be Working, MOCKED or STUBBED: {row}"
        if cells[2] == "**Working**":
            assert re.search(r"tests/test_\w+\.py", cells[3]), f"a Working row names the test that proves it: {row}"
