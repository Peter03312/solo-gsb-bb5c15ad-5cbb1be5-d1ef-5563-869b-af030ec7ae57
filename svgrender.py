"""把每张母纸的排样结果渲染成 SVG（业务坐标系 y 向上，SVG 内需翻转）。"""
from __future__ import annotations

from html import escape

PALETTE = [
    "#4e79a7", "#f28e2b", "#59a14f", "#e15759", "#76b7b2",
    "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac",
]


def type_color(type_idx):
    return PALETTE[type_idx % len(PALETTE)]


def render_sheet_svg(sheet_w, sheet_h, sheet, max_w=660, max_h=440):
    """sheet: {"placements":[...], "waste":[...]}；返回 SVG 字符串。"""
    scale = min(max_w / sheet_w, max_h / sheet_h)
    W, H = sheet_w * scale, sheet_h * scale
    parts = [
        '<svg class="sheet-svg" viewBox="0 0 %.2f %.2f" width="%.1f" height="%.1f" '
        'xmlns="http://www.w3.org/2000/svg" role="img">' % (W, H, W, H),
        '<rect x="0" y="0" width="%.2f" height="%.2f" fill="#ffffff" '
        'stroke="#333" stroke-width="1.5"/>' % (W, H),
    ]

    def rect(x, y, w, h, fill, stroke, dash):
        # y 翻转：SVG 原点在左上
        return ('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="%s" '
                'stroke="%s" stroke-width="0.8"%s/>'
                % (x * scale, H - (y + h) * scale, w * scale, h * scale,
                   fill, stroke, ' stroke-dasharray="3,2"' if dash else ""))

    for wst in sheet["waste"]:
        x, y, w, h = wst["rect"]
        if wst["kind"] == "kerf":
            parts.append(rect(x, y, w, h, "#c9c9c9", "#b0b0b0", False))
        else:
            parts.append(rect(x, y, w, h, "#f2f2f2", "#cccccc", True))

    for p in sheet["placements"]:
        color = type_color(p["type"])
        label = "成品%d %d×%d%s" % (
            p["type"] + 1, p["w"], p["h"], "（旋转）" if p["rot"] else "")
        parts.append("<g><title>%s</title>%s</g>"
                     % (escape(label),
                        rect(p["x"], p["y"], p["w"], p["h"], color, "#2f2f2f", False)))
        w_px, h_px = p["w"] * scale, p["h"] * scale
        cx = (p["x"] + p["w"] / 2) * scale
        cy = H - (p["y"] + p["h"] / 2) * scale
        if w_px >= 30 and h_px >= 12:
            name = "成品%d%s" % (p["type"] + 1, " ⟳" if p["rot"] else "")
            two_lines = w_px >= 64 and h_px >= 26
            parts.append('<text x="%.2f" y="%.2f" font-size="11" text-anchor="middle" '
                         'dominant-baseline="middle" fill="#ffffff">%s</text>'
                         % (cx, cy - (6 if two_lines else 0), escape(name)))
            if two_lines:
                parts.append('<text x="%.2f" y="%.2f" font-size="9" text-anchor="middle" '
                             'dominant-baseline="middle" fill="#f0f0f0">%d×%d</text>'
                             % (cx, cy + 8, p["w"], p["h"]))
    parts.append("</svg>")
    return "".join(parts)
