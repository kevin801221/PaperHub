import logging
from pathlib import Path

import pytest

from paperhub.pipelines.extract import extract_latex, extract_pdf


def test_extract_latex_finds_main_and_flattens() -> None:
    fixture = Path(__file__).parent / "fixtures" / "papers" / "arxiv_sample"
    out = extract_latex(fixture)
    assert out.main_path.name == "main.tex"
    assert "Mixture-of-Experts" in out.flattened_text
    # Preamble stripped — documentclass lives before \begin{document}
    assert "\\documentclass" not in out.flattened_text
    assert "Introduction" in out.flattened_text
    assert "Method" in out.flattened_text


def test_extract_pdf_returns_text() -> None:
    fixture = Path(__file__).parent / "fixtures" / "papers" / "sample.pdf"
    text = extract_pdf(fixture)
    assert "Tiny Test Paper" in text
    assert "Mixture-of-Experts" in text


def test_extract_latex_raises_on_empty_dir(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        extract_latex(tmp_path)


def test_extract_latex_follows_subdir_input(tmp_path: Path) -> None:
    """`\\input{sections/method}` must resolve when the file lives in a
    subdirectory.  This regressed silently when the tarball extractor
    flattened all members into the source root."""
    main_tex = tmp_path / "main.tex"
    main_tex.write_text(
        r"\documentclass{article}\begin{document}"
        r"\input{sections/method}"
        r"\input{sections/eval}"
        r"\end{document}",
        encoding="utf-8",
    )
    sections = tmp_path / "sections"
    sections.mkdir()
    (sections / "method.tex").write_text(
        "We propose load-balancing across experts.",
        encoding="utf-8",
    )
    (sections / "eval.tex").write_text(
        "Evaluation on MMLU and GSM8K.",
        encoding="utf-8",
    )

    out = extract_latex(tmp_path)
    assert "load-balancing" in out.flattened_text
    assert "Evaluation on MMLU" in out.flattened_text


def test_extract_latex_warns_on_missing_input(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Missing inputs must log a warning so a regression in the extractor or
    a malformed tarball can't silently truncate a paper to its preamble."""
    main_tex = tmp_path / "main.tex"
    main_tex.write_text(
        r"\documentclass{article}\begin{document}"
        r"\input{sections/missing}"
        r"\end{document}",
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING, logger="paperhub.pipelines.extract"):
        out = extract_latex(tmp_path)

    assert any("missing" in rec.message and "sections/missing" in rec.message
               for rec in caplog.records), (
        f"expected a warning naming the missing input; got: {[r.message for r in caplog.records]}"
    )
    # Behavior unchanged on the data side — missing input still becomes empty.
    assert out.flattened_text.strip() == ""
