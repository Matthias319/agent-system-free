#!/home/maetzger/.claude/tools/.venv/bin/python
"""Screenshot Annotation Tool — Playwright + Warm Editorial Design System.

Browser-rendered annotations with SVG arrows, CSS badges/labels.
Uses the exact design tokens from the report system.

Usage:
    python3 annotate-screenshot.py config.json
    python3 annotate-screenshot.py config.json --html   # debug: HTML only

Config JSON:
{
    "input": "screenshot.png",
    "output": "annotated.png",
    "title": "Schritt 1: Webinar erstellen",    // optional
    "padding": {"top": 0, "right": 220, "bottom": 0, "left": 0},
    "scale": 2,                                  // device pixel ratio
    "annotations": [
        {
            "num": 1,
            "label": "Hier klicken",
            "target": [200, 100],       // arrow points HERE (in screenshot coords)
            "badge": [750, 100],        // badge sits HERE (in screenshot coords)
            "highlight": [180, 85, 350, 115],  // optional: rect around target
            "label_side": "right"       // optional: "right" (default) or "left"
        }
    ]
}
"""

import base64
import json
import math
import sys
from pathlib import Path

# ─── Design Tokens (from _base.css :root) ───────────────────────────
ACCENT = "#cf865a"
ACCENT_HOVER = "#e09468"
BG_RAISED = "#1a1918"
BG_CARD = "#1f1e1c"
TEXT = "#e8e4de"
TEXT_SEC = "#b5afa5"
BORDER = "#2a2826"


def _highlight_edge(
    bx: float,
    by: float,
    tx: float,
    ty: float,
    hl_rect: tuple[float, float, float, float],
) -> tuple[float, float]:
    """Find where the line from badge to target intersects the highlight rect edge.

    Returns the intersection point on the rect boundary closest to the badge.
    If no intersection found, returns (tx, ty) as fallback.
    """
    hx1, hy1, hx2, hy2 = hl_rect
    dx = tx - bx
    dy = ty - by

    t_values: list[tuple[float, float, float]] = []

    # Left edge
    if dx != 0:
        t = (hx1 - bx) / dx
        y_at_t = by + t * dy
        if 0 < t <= 1 and hy1 <= y_at_t <= hy2:
            t_values.append((t, hx1, y_at_t))

    # Right edge
    if dx != 0:
        t = (hx2 - bx) / dx
        y_at_t = by + t * dy
        if 0 < t <= 1 and hy1 <= y_at_t <= hy2:
            t_values.append((t, hx2, y_at_t))

    # Top edge
    if dy != 0:
        t = (hy1 - by) / dy
        x_at_t = bx + t * dx
        if 0 < t <= 1 and hx1 <= x_at_t <= hx2:
            t_values.append((t, x_at_t, hy1))

    # Bottom edge
    if dy != 0:
        t = (hy2 - by) / dy
        x_at_t = bx + t * dx
        if 0 < t <= 1 and hx1 <= x_at_t <= hx2:
            t_values.append((t, x_at_t, hy2))

    if t_values:
        t_values.sort(key=lambda v: v[0])
        _, ex, ey = t_values[0]
        return ex, ey

    return tx, ty


def _arrow_path(bx: float, by: float, tx: float, ty: float, badge_r: float = 30) -> str:
    """SVG cubic bezier path from badge edge to target.

    Starts from the edge of the badge circle (not center) and creates
    a smooth curve to the target point. Uses horizontal departure/arrival
    control points so arrows look natural and don't cross content.
    """
    dx = tx - bx
    dy = ty - by
    dist = math.hypot(dx, dy)
    if dist < 1:
        return ""

    # Start from badge edge in direction of target
    angle = math.atan2(dy, dx)
    sx = bx + badge_r * math.cos(angle)
    sy = by + badge_r * math.sin(angle)

    # Control points: depart horizontally from badge, arrive horizontally at target
    # This creates smooth S-curves that stay away from content
    handle_len = min(abs(dx) * 0.4, dist * 0.35)
    handle_len = max(handle_len, 30)  # minimum curve

    cp1x = sx + handle_len * math.cos(angle)
    cp1y = sy + handle_len * 0.2 * math.sin(angle)  # mostly horizontal

    cp2x = tx - handle_len * math.cos(angle)
    cp2y = ty - handle_len * 0.2 * math.sin(angle)

    return f"M {sx:.1f},{sy:.1f} C {cp1x:.1f},{cp1y:.1f} {cp2x:.1f},{cp2y:.1f} {tx:.1f},{ty:.1f}"


def build_html(config: dict) -> str:
    """Build self-contained annotation HTML from config."""
    from PIL import Image

    img_path = Path(config["input"])
    with Image.open(img_path) as img:
        img_w, img_h = img.size

    # Embed image as base64
    img_data = base64.b64encode(img_path.read_bytes()).decode()
    suffix = img_path.suffix.lower().lstrip(".")
    if suffix == "jpg":
        suffix = "jpeg"
    img_src = f"data:image/{suffix};base64,{img_data}"

    # Padding
    pad = config.get("padding", {})
    pt = pad.get("top", 0)
    pr = pad.get("right", 0)
    pb = pad.get("bottom", 0)
    pl = pad.get("left", 0)

    # Title adds top space
    title = config.get("title", "")
    title_h = 44 if title else 0

    total_w = img_w + pl + pr
    total_h = img_h + pt + pb + title_h

    # Build annotation elements
    highlights = []
    arrows = []
    badges_labels = []

    for ann in config.get("annotations", []):
        num = ann["num"]
        label = ann["label"]
        tx, ty = ann["target"]
        bx, by = ann["badge"]
        side = ann.get("label_side", "right")

        # Absolute coords (account for padding + title)
        tx_a = tx + pl
        ty_a = ty + pt + title_h
        bx_a = bx + pl
        by_a = by + pt + title_h

        # Highlight rect
        if hl := ann.get("highlight"):
            x1, y1, x2, y2 = hl
            x1_a = x1 + pl
            y1_a = y1 + pt + title_h
            w = x2 - x1
            h = y2 - y1
            highlights.append(
                f'<div class="highlight" style="left:{x1_a - 5}px;'
                f'top:{y1_a - 5}px;width:{w + 10}px;height:{h + 10}px;"></div>'
            )

        # Arrow target: point to highlight edge if present, not center
        arrow_tx, arrow_ty = tx_a, ty_a
        if hl := ann.get("highlight"):
            x1, y1, x2, y2 = hl
            hl_rect_a = (
                x1 + pl - 5,
                y1 + pt + title_h - 5,
                x2 + pl + 5,
                y2 + pt + title_h + 5,
            )
            arrow_tx, arrow_ty = _highlight_edge(bx_a, by_a, tx_a, ty_a, hl_rect_a)

        # Arrow (SVG path)
        path_d = _arrow_path(bx_a, by_a, arrow_tx, arrow_ty)
        if path_d:
            arrows.append(
                f'    <path d="{path_d}" fill="none" stroke="{ACCENT}" '
                f'stroke-width="2.5" stroke-opacity="0.8" stroke-linecap="round" '
                f'marker-end="url(#ah)"/>'
            )

        # Badge
        badges_labels.append(
            f'<div class="badge" style="left:{bx_a}px;top:{by_a}px;">{num}</div>'
        )

        # Label (offset from badge center by badge radius + gap)
        if side == "left":
            lx = bx_a - 38
            badges_labels.append(
                f'<div class="label label-left" '
                f'style="right:{total_w - lx}px;top:{by_a}px;">{label}</div>'
            )
        else:
            lx = bx_a + 38
            badges_labels.append(
                f'<div class="label" style="left:{lx}px;top:{by_a}px;">{label}</div>'
            )

    # Title HTML
    title_html = ""
    if title:
        title_html = f'<div class="title">{title}</div>'

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}

body {{
    position: relative;
    width: {total_w}px;
    height: {total_h}px;
    background: {BG_CARD};
    font-family: "DejaVu Sans", system-ui, -apple-system, sans-serif;
    -webkit-font-smoothing: antialiased;
}}

.title {{
    position: absolute;
    top: {pt}px;
    left: {pl}px;
    width: {img_w}px;
    height: {title_h}px;
    display: flex;
    align-items: center;
    color: {ACCENT};
    font-size: 14px;
    font-weight: 700;
    letter-spacing: 0.03em;
}}

.screenshot {{
    position: absolute;
    top: {pt + title_h}px;
    left: {pl}px;
    display: block;
    border-radius: 6px;
    border: 1px solid rgba(255,255,255,0.06);
    box-shadow: 0 4px 20px rgba(0,0,0,0.3);
}}

.highlight {{
    position: absolute;
    border: 2px solid rgba(207, 134, 90, 0.5);
    border-radius: 6px;
    background: rgba(207, 134, 90, 0.06);
    z-index: 2;
    pointer-events: none;
}}

svg.arrows {{
    position: absolute;
    top: 0; left: 0;
    width: 100%; height: 100%;
    z-index: 3;
    pointer-events: none;
}}

.badge {{
    position: absolute;
    width: 56px; height: 56px;
    border-radius: 50%;
    background: {ACCENT};
    color: #fff;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 700;
    font-size: 26px;
    line-height: 1;
    z-index: 4;
    transform: translate(-50%, -50%);
    box-shadow:
        0 3px 12px rgba(0,0,0,0.4),
        inset 0 1px 0 rgba(255,255,255,0.18);
}}

.label {{
    position: absolute;
    background: rgba(26, 25, 24, 0.94);
    color: {TEXT};
    padding: 10px 20px 10px 24px;
    border-radius: 7px;
    font-size: 22px;
    font-weight: 600;
    letter-spacing: 0.01em;
    white-space: nowrap;
    border-left: 5px solid {ACCENT};
    z-index: 4;
    transform: translateY(-50%);
    box-shadow: 0 3px 16px rgba(0,0,0,0.35);
}}

.label-left {{
    border-left: none;
    border-right: 5px solid {ACCENT};
    padding: 10px 24px 10px 20px;
}}
</style>
</head>
<body>
{title_html}
<img class="screenshot" src="{img_src}" width="{img_w}" height="{img_h}">
{"".join(highlights)}
<svg class="arrows" viewBox="0 0 {total_w} {total_h}">
    <defs>
        <marker id="ah" viewBox="0 0 12 12" refX="11" refY="6"
            markerWidth="10" markerHeight="10" orient="auto-start-reverse">
            <path d="M 1 1.5 L 11 6 L 1 10.5 Z" fill="{ACCENT}" opacity="0.85"/>
        </marker>
    </defs>
{chr(10).join(arrows)}
</svg>
{"".join(badges_labels)}
</body>
</html>"""

    return html


def render(config: dict) -> Path:
    """Render annotated screenshot using Playwright at high DPI."""
    from playwright.sync_api import sync_playwright

    from PIL import Image

    html = build_html(config)
    output = Path(config["output"])
    scale = config.get("scale", 2)

    # Calculate viewport size
    img_path = Path(config["input"])
    with Image.open(img_path) as img:
        img_w, img_h = img.size

    pad = config.get("padding", {})
    title_h = 44 if config.get("title") else 0
    total_w = img_w + pad.get("left", 0) + pad.get("right", 0)
    total_h = img_h + pad.get("top", 0) + pad.get("bottom", 0) + title_h

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium")
        context = browser.new_context(
            viewport={"width": total_w, "height": total_h},
            device_scale_factor=scale,
        )
        page = context.new_page()
        page.set_content(html)
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(300)  # ensure rendering completes

        page.screenshot(path=str(output), full_page=True, type="png")
        browser.close()

    size_kb = output.stat().st_size / 1024
    print(
        f"✓ {output} ({total_w * scale}×{total_h * scale} @{scale}x, {size_kb:.0f}KB)"
    )
    return output


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    config_path = sys.argv[1]
    with open(config_path) as f:
        config = json.load(f)

    if "--html" in sys.argv:
        print(build_html(config))
    else:
        render(config)
