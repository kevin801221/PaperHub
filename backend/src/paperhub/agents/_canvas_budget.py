"""F4.5 canvas-budget loader (operator-tunable yaml; no thresholds in Python)."""
from __future__ import annotations

import math
from dataclasses import dataclass
from importlib.resources import files
from typing import Literal

import yaml

Script = Literal["en", "cjk"]


@dataclass(frozen=True)
class CanvasConstants:
    frame_canvas_cm: tuple[float, float]
    line_height_cm: float
    bullet_pitch_factor: float
    chars_per_cm: dict[str, float]
    chars_per_word: float
    aspect_mismatch_strict: bool


@dataclass(frozen=True)
class CanvasLayout:
    name: str
    matches_aspect: str  # ">= X" / "<= X" / "X..Y" / "any" / "no_figure"
    figure_region_cm: tuple[float, float]
    text_region_cm: tuple[float, float]
    text_structure_hint: str
    requires_math_block: bool = False


@dataclass(frozen=True)
class CanvasBudget:
    constants: CanvasConstants
    layouts: tuple[CanvasLayout, ...]


def load_canvas_budget() -> CanvasBudget:
    path = files("paperhub.agents") / "slide_canvas_budget.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    c = raw["constants"]
    constants = CanvasConstants(
        frame_canvas_cm=tuple(c["frame_canvas_cm"]),
        line_height_cm=float(c["line_height_cm"]),
        bullet_pitch_factor=float(c["bullet_pitch_factor"]),
        chars_per_cm={k: float(v) for k, v in c["chars_per_cm"].items()},
        chars_per_word=float(c["chars_per_word"]),
        aspect_mismatch_strict=bool(c.get("aspect_mismatch_strict", False)),
    )
    layouts: list[CanvasLayout] = []
    for name, body in raw["layouts"].items():
        layouts.append(
            CanvasLayout(
                name=name,
                matches_aspect=str(body["matches_aspect"]),
                figure_region_cm=tuple(body["figure_region_cm"]),
                text_region_cm=tuple(body["text_region_cm"]),
                text_structure_hint=str(body["text_structure_hint"]),
                requires_math_block=bool(body.get("requires_math_block", False)),
            )
        )
    return CanvasBudget(constants=constants, layouts=tuple(layouts))


def aspect_matches(rule: str, aspect: float | None) -> bool:
    """True iff `aspect` satisfies the matches_aspect rule.

    `aspect=None` means "no figure present" — only `no_figure` and `any` accept it.
    """
    rule = rule.strip()
    if rule == "any":
        return True
    if rule == "no_figure":
        return aspect is None
    if aspect is None:
        return False  # figure-bearing rule + no figure → mismatch
    if rule.startswith(">="):
        return aspect >= float(rule[2:].strip())
    if rule.startswith("<="):
        return aspect <= float(rule[2:].strip())
    if ".." in rule:
        lo_s, hi_s = rule.split("..")
        return float(lo_s.strip()) <= aspect <= float(hi_s.strip())
    raise ValueError(f"unknown matches_aspect rule: {rule!r}")


def compute_token_budget(
    layout: CanvasLayout, constants: CanvasConstants, *, script: Script
) -> int:
    """Compute body-text token capacity for this layout's text region."""
    width_cm, height_cm = layout.text_region_cm
    chars_per_cm = constants.chars_per_cm[script]
    line_pitch = constants.line_height_cm * constants.bullet_pitch_factor
    if line_pitch <= 0 or height_cm <= 0 or width_cm <= 0:
        return 0
    max_lines = math.floor(height_cm / line_pitch)
    chars_per_line = math.floor(width_cm * chars_per_cm)
    tokens_per_line = chars_per_line / constants.chars_per_word
    return int(max_lines * tokens_per_line)
