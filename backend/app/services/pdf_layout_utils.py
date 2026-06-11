from typing import Any

import fitz


def line_rect(line: dict[str, Any]) -> fitz.Rect:
    bbox = line.get("bbox", {})
    return fitz.Rect(bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"])


def block_rect(block: dict[str, Any]) -> fitz.Rect:
    bbox = block.get("bbox", {})
    return fitz.Rect(bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"])


def rect_overlap_ratio(first: fitz.Rect, second: fitz.Rect) -> float:
    overlap = first & second
    if overlap.is_empty or first.get_area() <= 0:
        return 0.0
    return overlap.get_area() / first.get_area()


def color_from_int(color: int):
    red = ((color >> 16) & 255) / 255
    green = ((color >> 8) & 255) / 255
    blue = (color & 255) / 255
    return (red, green, blue)


def color_distance(first, second) -> float:
    return sum((first[index] - second[index]) ** 2 for index in range(3)) ** 0.5


def relative_luminance(color) -> float:
    def channel_luminance(value: float) -> float:
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = color
    return (
        0.2126 * channel_luminance(red)
        + 0.7152 * channel_luminance(green)
        + 0.0722 * channel_luminance(blue)
    )


def contrast_ratio(first, second) -> float:
    first_luminance = relative_luminance(first)
    second_luminance = relative_luminance(second)
    lighter = max(first_luminance, second_luminance)
    darker = min(first_luminance, second_luminance)
    return (lighter + 0.05) / (darker + 0.05)


def ensure_readable_color(color, background_color):
    if not color or len(color) != 3:
        return fitz.utils.getColor("black")

    if not background_color or len(background_color) != 3:
        return color

    if contrast_ratio(color, background_color) < 1.6:
        black = fitz.utils.getColor("black")
        white = fitz.utils.getColor("white")
        return black if contrast_ratio(black, background_color) >= contrast_ratio(white, background_color) else white
    return color
