#!/usr/bin/env python3
"""Icon options for Rain Radar Alarm, in the Calendar Zone style.

Flat shapes, navy #1F3A5F, coral #E2725B, slate #9AA8B8 and white, on transparency.

    python3 docs/icon-options/generate_icons.py            # SVG + 512 px PNG per option, and a sheet
    python3 docs/icon-options/generate_icons.py --brand B   # also write brand/icon.png + icon@2x.png

PNG rendering needs Playwright with Chromium (pip install playwright; python -m playwright install chromium).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BRAND = os.path.join(HERE, "..", "..", "custom_components", "rain_radar_alarm", "brand")
NAVY, CORAL, SLATE, WHITE = "#1F3A5F", "#E2725B", "#9AA8B8", "#FFFFFF"


def drop(x, y, s, fill):
    """Raindrop, tip up, round body centred at (x, y + 0.25 s) with radius s."""
    return (f'<path fill="{fill}" d="M{x},{y - 1.5 * s} C{x + 0.35 * s},{y - 0.95 * s} {x + s},{y - 0.4 * s} '
            f'{x + s},{y + 0.25 * s} A{s},{s} 0 0 1 {x - s},{y + 0.25 * s} C{x - s},{y - 0.4 * s} '
            f'{x - 0.35 * s},{y - 0.95 * s} {x},{y - 1.5 * s} Z"/>')


def cloud(fill, dx=0, dy=0, k=1.0):
    def c(x, y, r):
        return f'<circle cx="{dx + x * k}" cy="{dy + y * k}" r="{r * k}" fill="{fill}"/>'
    return (c(128, 178, 82) + c(228, 128, 104) + c(326, 186, 74)
            + f'<rect x="{dx + 46 * k}" y="{dy + 178 * k}" width="{354 * k}" height="{86 * k}" rx="{43 * k}" fill="{fill}"/>')


def pin(cx, cy, r, inner):
    """Location pin like Calendar Zone's, with something white inside."""
    tip = cy + r * 1.75
    return (f'<path fill="{CORAL}" d="M{cx},{tip} C{cx - r * 0.55},{cy + r * 1.05} {cx - r},{cy + r * 0.62} '
            f'{cx - r},{cy} A{r},{r} 0 0 1 {cx + r},{cy} C{cx + r},{cy + r * 0.62} {cx + r * 0.55},{cy + r * 1.05} '
            f'{cx},{tip} Z"/>' + inner)


OPTIONS = {
    # A: Calendar Zone's layout, with the calendar swapped for a rain cloud: rain falls toward a
    #    location pin that holds a raindrop. Reads as "rain coming to where you are".
    "A": ("Cloud to pin",
          cloud(NAVY, 6, 8, 0.8)
          + drop(122, 300, 21, SLATE) + drop(182, 360, 21, SLATE) + drop(244, 420, 22, CORAL)
          + pin(406, 318, 90, drop(406, 312, 30, WHITE))),
    # B: a radar scope in the Calendar Zone frame: rings, a sweep, and one coral echo shaped like a drop.
    "B": ("Radar scope",
          f'<rect x="22" y="22" width="468" height="468" rx="84" fill="{NAVY}"/>'
          f'<rect x="58" y="58" width="396" height="396" rx="56" fill="{WHITE}"/>'
          f'<circle cx="256" cy="256" r="150" fill="none" stroke="{SLATE}" stroke-width="16"/>'
          f'<circle cx="256" cy="256" r="82" fill="none" stroke="{SLATE}" stroke-width="16"/>'
          f'<path d="M256,256 L256,96 A160,160 0 0 1 369,143 Z" fill="{SLATE}" opacity="0.45"/>'
          f'<line x1="256" y1="256" x2="369" y2="143" stroke="{NAVY}" stroke-width="20" stroke-linecap="round"/>'
          f'<circle cx="256" cy="256" r="22" fill="{NAVY}"/>'
          f'<circle cx="160" cy="330" r="15" fill="{SLATE}"/><circle cx="196" cy="168" r="15" fill="{SLATE}"/>'
          + drop(344, 318, 30, CORAL)),
    # C: umbrella with rain, one coral drop: "take an umbrella".
    "C": ("Umbrella",
          f'<path fill="{NAVY}" d="M40,268 A216,216 0 0 1 472,268 A54,26 0 0 0 364,268 A54,26 0 0 0 256,268 '
          f'A54,26 0 0 0 148,268 A54,26 0 0 0 40,268 Z"/>'
          f'<path d="M256,262 V420 A46,46 0 0 1 164,420" fill="none" stroke="{NAVY}" stroke-width="30" stroke-linecap="round"/>'
          + drop(96, 64, 20, SLATE) + drop(424, 72, 20, SLATE) + drop(262, 30, 16, SLATE)
          + drop(430, 404, 34, CORAL) + drop(76, 380, 20, SLATE)),
    # D: a coral raindrop with a clock face: "how long until rain".
    "D": ("Drop and clock",
          drop(256, 262, 182, CORAL)
          + f'<circle cx="256" cy="318" r="104" fill="{WHITE}"/>'
          + f'<circle cx="256" cy="318" r="104" fill="none" stroke="{NAVY}" stroke-width="22"/>'
          + f'<line x1="256" y1="318" x2="256" y2="252" stroke="{NAVY}" stroke-width="22" stroke-linecap="round"/>'
          + f'<line x1="256" y1="318" x2="306" y2="346" stroke="{NAVY}" stroke-width="22" stroke-linecap="round"/>'
          + f'<circle cx="256" cy="318" r="15" fill="{NAVY}"/>'
          ),
}


def svg(body: str) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">{body}</svg>'


def render(page, markup: str, path: str, size: int) -> None:
    page.set_viewport_size({"width": size, "height": size})
    page.set_content(f'<html><body style="margin:0;background:transparent">'
                     f'{markup.replace("width=\"512\" height=\"512\"", f"width=\"{size}\" height=\"{size}\"")}</body></html>')
    page.screenshot(path=path, omit_background=True)


def main() -> None:
    from playwright.sync_api import sync_playwright

    brand = sys.argv[sys.argv.index("--brand") + 1] if "--brand" in sys.argv else None
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page()
        for key, (_name, body) in OPTIONS.items():
            with open(os.path.join(HERE, f"option-{key}.svg"), "w") as fh:
                fh.write(svg(body) + "\n")
            render(page, svg(body), os.path.join(HERE, f"option-{key}.png"), 512)
        cells = "".join(
            f'<div style="text-align:center"><div style="display:flex;gap:16px">'
            f'<div style="background:#fff;border:1px solid #ddd;border-radius:12px;padding:16px">{svg(body).replace("width=\"512\" height=\"512\"", "width=\"200\" height=\"200\"")}</div>'
            f'<div style="background:#1c1c1c;border-radius:12px;padding:16px">{svg(body).replace("width=\"512\" height=\"512\"", "width=\"200\" height=\"200\"")}</div>'
            f'<div style="background:#fff;border:1px solid #ddd;border-radius:12px;padding:16px;display:flex;align-items:center">'
            f'{svg(body).replace("width=\"512\" height=\"512\"", "width=\"40\" height=\"40\"")}</div></div>'
            f'<div style="font:600 20px sans-serif;margin-top:10px;color:#1F3A5F">{key}: {name}</div></div>'
            for key, (name, body) in OPTIONS.items())
        sheet = (f'<html><body style="margin:0;padding:28px;background:#f4f5f7;font-family:sans-serif">'
                 f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:28px 40px">{cells}</div></body></html>')
        page.set_viewport_size({"width": 1180, "height": 640})
        page.set_content(sheet)
        page.screenshot(path=os.path.join(HERE, "icon-options.png"), full_page=True)
        if brand:
            os.makedirs(BRAND, exist_ok=True)
            body = OPTIONS[brand][1]
            render(page, svg(body), os.path.join(BRAND, "icon@2x.png"), 512)
            render(page, svg(body), os.path.join(BRAND, "icon.png"), 256)
        b.close()


if __name__ == "__main__":
    main()
