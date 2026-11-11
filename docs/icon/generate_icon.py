#!/usr/bin/env python3
"""Draw the Rain Radar Alarm icon: a radar scope with a coral raindrop echo.

Writes docs/icon/icon.svg (the source) and the integration's brand images,
custom_components/rain_radar_alarm/brand/icon.png (256 px) and icon@2x.png (512 px).

    pip install playwright && python -m playwright install chromium
    python3 docs/icon/generate_icon.py
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
BRAND = HERE.parents[1] / "custom_components" / "rain_radar_alarm" / "brand"
NAVY, CORAL, SLATE, WHITE = "#1F3A5F", "#E2725B", "#9AA8B8", "#FFFFFF"


def drop(x: float, y: float, s: float, fill: str) -> str:
    """Raindrop, tip up, round body of radius s centred at (x, y + 0.25 s)."""
    return (f'<path fill="{fill}" d="M{x},{y - 1.5 * s} C{x + 0.35 * s},{y - 0.95 * s} {x + s},{y - 0.4 * s} '
            f'{x + s},{y + 0.25 * s} A{s},{s} 0 0 1 {x - s},{y + 0.25 * s} C{x - s},{y - 0.4 * s} '
            f'{x - 0.35 * s},{y - 0.95 * s} {x},{y - 1.5 * s} Z"/>')


BODY = (
    f'<rect x="22" y="22" width="468" height="468" rx="84" fill="{NAVY}"/>'
    f'<rect x="58" y="58" width="396" height="396" rx="56" fill="{WHITE}"/>'
    f'<circle cx="256" cy="256" r="150" fill="none" stroke="{SLATE}" stroke-width="16"/>'
    f'<circle cx="256" cy="256" r="82" fill="none" stroke="{SLATE}" stroke-width="16"/>'
    f'<path d="M256,256 L256,96 A160,160 0 0 1 369,143 Z" fill="{SLATE}" opacity="0.45"/>'
    f'<line x1="256" y1="256" x2="369" y2="143" stroke="{NAVY}" stroke-width="20" stroke-linecap="round"/>'
    f'<circle cx="256" cy="256" r="22" fill="{NAVY}"/>'
    f'<circle cx="160" cy="330" r="15" fill="{SLATE}"/>'
    f'<circle cx="196" cy="168" r="15" fill="{SLATE}"/>'
    + drop(344, 318, 30, CORAL)
)


def svg(size: int = 512) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" '
            f'width="{size}" height="{size}">{BODY}</svg>')


def main() -> None:
    from playwright.sync_api import sync_playwright

    (HERE / "icon.svg").write_text(svg() + "\n")
    BRAND.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        for name, size in (("icon.png", 256), ("icon@2x.png", 512)):
            page.set_viewport_size({"width": size, "height": size})
            page.set_content(f'<html><body style="margin:0;background:transparent">{svg(size)}</body></html>')
            page.screenshot(path=str(BRAND / name), omit_background=True)
        browser.close()


if __name__ == "__main__":
    main()
