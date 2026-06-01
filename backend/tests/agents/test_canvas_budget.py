from paperhub.agents._canvas_budget import (
    aspect_matches,
    compute_token_budget,
    load_canvas_budget,
)


def test_load_canvas_budget():
    cb = load_canvas_budget()
    assert cb.constants.line_height_cm == 0.65
    assert cb.constants.bullet_pitch_factor == 1.6
    assert cb.constants.chars_per_cm["en"] == 12.0
    assert cb.constants.chars_per_cm["cjk"] == 8.0
    # All canonical layouts are present.
    names = {layout.name for layout in cb.layouts}
    assert {
        "text_only", "figure_left_half_portrait", "figure_right_half_portrait",
        "figure_top_full_landscape", "equation_centered", "title_frame", "closer_frame",
    }.issubset(names)


def test_aspect_matches_landscape():
    assert aspect_matches(">= 1.5", 1.78) is True
    assert aspect_matches(">= 1.5", 1.49) is False


def test_aspect_matches_portrait_range():
    assert aspect_matches("0.5..1.3", 0.7) is True
    assert aspect_matches("0.5..1.3", 1.3) is True  # inclusive upper
    assert aspect_matches("0.5..1.3", 0.49) is False


def test_aspect_matches_any():
    assert aspect_matches("any", 1.0) is True
    assert aspect_matches("any", 99.0) is True


def test_aspect_matches_no_figure():
    assert aspect_matches("no_figure", None) is True
    assert aspect_matches("no_figure", 1.0) is False  # text-only layouts reject figures


def test_compute_token_budget_text_only_en():
    cb = load_canvas_budget()
    text_only = next(layout for layout in cb.layouts if layout.name == "text_only")
    # 12.8cm × 6.5cm region at EN constants:
    #   max_lines = floor(6.5 / (0.65 * 1.6)) = floor(6.25) = 6
    #   chars_per_line = 12.8 × 12 = 153.6 → 153
    #   tokens_per_line = 153 / 6 = 25.5 → ~25
    #   budget = 6 × 25 = 150 tokens
    budget = compute_token_budget(text_only, cb.constants, script="en")
    assert 130 <= budget <= 170


def test_compute_token_budget_figure_top_landscape_en_smaller():
    cb = load_canvas_budget()
    landscape = next(
        layout for layout in cb.layouts if layout.name == "figure_top_full_landscape"
    )
    # 12.8cm × 2.5cm band → ~2 lines × ~25 tokens/line = ~50 tokens
    budget = compute_token_budget(landscape, cb.constants, script="en")
    assert 40 <= budget <= 70


def test_compute_token_budget_cjk_is_lower_than_en_same_layout():
    cb = load_canvas_budget()
    text_only = next(layout for layout in cb.layouts if layout.name == "text_only")
    en = compute_token_budget(text_only, cb.constants, script="en")
    cjk = compute_token_budget(text_only, cb.constants, script="cjk")
    # CJK constants are lower → fewer chars per cm → smaller token budget.
    assert cjk < en
