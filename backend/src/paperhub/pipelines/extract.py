"""Extract paper text from LaTeX sources or PDFs.

LaTeX extraction adapted from paper2slides-plus/src/latex_utils.py:
- Identify the main .tex file (the one with \\begin{document}).
- Recursively inline \\input{...} and \\include{...}.
- Strip the preamble (everything before \\begin{document}).
- Return both the main path (for source_path persistence) and the flattened
  body text (for chunking).

PDF extraction uses PyMuPDF's plain-text export.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

_BEGIN_DOC = re.compile(r"\\begin\{document\}")
_END_DOC = re.compile(r"\\end\{document\}")
_INPUT_INCLUDE = re.compile(r"\\(?:input|include)\{([^}]+)\}")


@dataclass(frozen=True)
class LatexExtract:
    main_path: Path
    flattened_text: str


def _find_main_tex(source_dir: Path) -> Path:
    candidates = list(source_dir.glob("*.tex"))
    if not candidates:
        raise FileNotFoundError(f"no .tex files in {source_dir}")
    for cand in candidates:
        text = cand.read_text(encoding="utf-8", errors="ignore")
        if _BEGIN_DOC.search(text):
            return cand
    # Fallback: first .tex.
    return candidates[0]


def _inline_recursive(text: str, root: Path, seen: set[Path]) -> str:
    def repl(m: re.Match[str]) -> str:
        rel = m.group(1).strip()
        if not rel.endswith(".tex"):
            rel = rel + ".tex"
        target = (root / rel).resolve()
        if target in seen or not target.exists():
            return ""
        seen.add(target)
        inner = target.read_text(encoding="utf-8", errors="ignore")
        return _inline_recursive(inner, root, seen)

    return _INPUT_INCLUDE.sub(repl, text)


def extract_latex(source_dir: Path) -> LatexExtract:
    """Extract flattened body text from a LaTeX source directory.

    Strips the preamble (everything before and including ``\\begin{document}``)
    and the closing ``\\end{document}`` tag.  All ``\\input`` / ``\\include``
    directives are inlined recursively.
    """
    main = _find_main_tex(source_dir)
    raw = main.read_text(encoding="utf-8", errors="ignore")
    flat = _inline_recursive(raw, source_dir, seen={main.resolve()})
    # Strip preamble (everything up to and including \\begin{document}).
    begin_m = _BEGIN_DOC.search(flat)
    if begin_m:
        flat = flat[begin_m.end():]
    end_m = _END_DOC.search(flat)
    if end_m:
        flat = flat[: end_m.start()]
    return LatexExtract(main_path=main, flattened_text=flat.strip())


def extract_pdf(pdf_path: Path) -> str:
    """Return concatenated plain text from a PDF, one form-feed-separated
    page per source page.
    """
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)
    pieces: list[str] = []
    with pymupdf.open(pdf_path) as doc:
        for page in doc:
            pieces.append(page.get_text("text"))
    return "\n\f\n".join(pieces).strip()
