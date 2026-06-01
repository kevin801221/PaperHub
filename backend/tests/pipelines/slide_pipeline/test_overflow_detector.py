import pytest

from paperhub.agents._canvas_budget import load_canvas_budget
from paperhub.models.slide_domain import FigureDimensions, KeyFigureBundle
from paperhub.pipelines.slide_pipeline.overflow_detector import (
    classify_layout,
    count_body_tokens,
    detect_overflow,
)


def _portrait_inventory() -> dict[str, KeyFigureBundle]:
    return {
        "p0-fig-001": KeyFigureBundle(
            key="p0-fig-001",
            role="overview",
            one_line_interpretation="x",
            dimensions=FigureDimensions(width_px=600, height_px=900),  # aspect 0.667
        )
    }


def _landscape_inventory() -> dict[str, KeyFigureBundle]:
    return {
        "p0-fig-001": KeyFigureBundle(
            key="p0-fig-001",
            role="overview",
            one_line_interpretation="x",
            dimensions=FigureDimensions(width_px=1640, height_px=920),  # aspect 1.78
        )
    }


_DECK_TEXT_ONLY = r"""
\documentclass{beamer}
\begin{document}
\begin{frame}{Background}
\begin{itemize}
\item Short intro point.
\item Second point.
\end{itemize}
\end{frame}
\end{document}
"""

_DECK_PORTRAIT_FIG_OVERFLOW = r"""
\documentclass{beamer}
\begin{document}
\begin{frame}{Method}
\begin{columns}[T]
\begin{column}{0.5\textwidth}
\includegraphics[width=\linewidth,height=0.7\textheight,keepaspectratio]{p0-fig-001}
\end{column}
\begin{column}{0.5\textwidth}
\begin{itemize}
\item This is a deliberately very long bullet that goes on for many words to push the body well past the available budget for a half-column text region.
\item Second very long bullet equally verbose with many words crowding the canvas.
\item Third long bullet adding still more density.
\item Fourth long bullet for safe measure.
\item Fifth bullet still piling on tokens beyond the budget.
\item Sixth bullet just to be sure we exceed the budget convincingly.
\end{itemize}
\end{column}
\end{columns}
\end{frame}
\end{document}
"""


def test_count_body_tokens_strips_latex():
    n = count_body_tokens(
        r"\begin{frame}{Title}\begin{itemize}\item hello world\item foo bar\end{itemize}\end{frame}"
    )
    # Words: hello world foo bar = 4 — title isn't counted as body.
    assert n == 4


def test_count_body_tokens_ignores_includegraphics_and_label():
    n = count_body_tokens(
        r"\begin{frame}{X}\includegraphics[width=\linewidth]{foo}\label{fig:bar}hello world\end{frame}"
    )
    assert n == 2


def test_classify_layout_text_only_no_figure():
    cb = load_canvas_budget()
    layout = classify_layout(
        frame_tex=r"\begin{frame}{X}\begin{itemize}\item a\end{itemize}\end{frame}",
        figure_inventory={},
        canvas_budget=cb,
    )
    assert layout.name == "text_only"


def test_classify_layout_columns_with_portrait_figure():
    cb = load_canvas_budget()
    layout = classify_layout(
        frame_tex=_DECK_PORTRAIT_FIG_OVERFLOW.split(r"\begin{document}")[1].split(r"\end{document}")[0],
        figure_inventory=_portrait_inventory(),
        canvas_budget=cb,
    )
    # 0.5\textwidth column → figure_left_half_portrait
    assert layout.name in ("figure_left_half_portrait", "figure_right_half_portrait")


def test_detect_overflow_flags_overcrammed_frame():
    cb = load_canvas_budget()
    signals = detect_overflow(
        deck_tex=_DECK_PORTRAIT_FIG_OVERFLOW,
        figure_inventory=_portrait_inventory(),
        canvas_budget=cb,
        pdflatex_log="",
        script="en",
    )
    assert len(signals) == 1
    sig = signals[0]
    assert sig.exceeds_canvas_budget is True
    assert sig.overage_tokens > 0
    assert sig.recommendation in ("split_frame", "tighten", "shrink_figure")


def test_detect_overflow_clean_frame_under_budget():
    cb = load_canvas_budget()
    signals = detect_overflow(
        deck_tex=_DECK_TEXT_ONLY,
        figure_inventory={},
        canvas_budget=cb,
        pdflatex_log="",
        script="en",
    )
    assert len(signals) == 1
    assert signals[0].exceeds_canvas_budget is False
    assert signals[0].recommendation == "ok"


def test_detect_overflow_aspect_mismatch_flagged():
    cb = load_canvas_budget()
    # Use the column-layout frame BUT swap the inventory to a landscape figure
    # — that's a layout_aspect_mismatch (landscape figure stuffed into a portrait slot).
    signals = detect_overflow(
        deck_tex=_DECK_PORTRAIT_FIG_OVERFLOW,
        figure_inventory=_landscape_inventory(),
        canvas_budget=cb,
        pdflatex_log="",
        script="en",
    )
    assert signals[0].layout_aspect_mismatch is True


def test_detect_overflow_parses_pdflatex_overfull_log():
    cb = load_canvas_budget()
    log = (
        "Overfull \\vbox (23.7pt too high) detected at line 12.\n"
        "...lots of other latex noise..."
    )
    signals = detect_overflow(
        deck_tex=_DECK_TEXT_ONLY,
        figure_inventory={},
        canvas_budget=cb,
        pdflatex_log=log,
        script="en",
    )
    assert signals[0].pdflatex_overfull_pt == pytest.approx(23.7, rel=1e-3)
