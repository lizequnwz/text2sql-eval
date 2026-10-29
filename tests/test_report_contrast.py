"""Check the light/dark palette against readable text and control contrast ratios."""

import re
from importlib.resources import files

import pytest


def luminance(color):
    channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in channels
    ]
    return sum(
        value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722), strict=True)
    )


@pytest.mark.parametrize("theme", [":root", '[data-theme="dark"]'])
def test_report_color_pairs_have_sufficient_contrast(theme):
    css = files("text2sql_eval").joinpath("assets", "report.css").read_text(encoding="utf-8")
    block = re.search(re.escape(theme) + r"\s*\{([^}]+)\}", css).group(1)
    colors = dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})\s*;", block))
    pairs = [
        ("text", "bg", 4.5),
        ("text", "surface", 4.5),
        ("muted", "surface", 4.5),
        ("accent", "surface", 4.5),
        ("pass", "pass-bg", 4.5),
        ("fail", "fail-bg", 4.5),
        ("review", "review-bg", 4.5),
        ("error", "error-bg", 4.5),
        ("control-border", "surface", 3),
        ("focus", "surface", 3),
    ]
    for foreground, background, minimum in pairs:
        low, high = sorted((luminance(colors[foreground]), luminance(colors[background])))
        ratio = (high + 0.05) / (low + 0.05)
        assert ratio >= minimum, (
            f"{theme}: {foreground}/{background} contrast {ratio:.2f} < {minimum}"
        )
