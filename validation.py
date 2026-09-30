"""输入校验：所有非法输入一律拒绝，绝不写入数据库。

规则（尺寸单位均为 mm）：
* 母纸长宽、成品长宽：正整数
* 刀缝宽度：非负整数
* 成品份数、张数上限、搜索状态数上限：正整数
"""
from __future__ import annotations

import re

INT_RE = re.compile(r"^\d+$")

DIM_LO, DIM_HI = 1, 100_000          # 尺寸（mm）
KERF_HI = 10_000                     # 刀缝（mm）
QTY_HI = 100_000                     # 单种成品份数
SHEETS_HI = 1_000                    # 张数上限
BUDGET_HI = 5_000_000                # 搜索状态数上限
MAX_TYPES = 50                       # 成品种类数
TOTAL_QTY_HI = 1_000                 # 全部成品总份数
NAME_HI = 80                         # 任务名称长度


def _parse_int(raw, lo, hi, label, errors):
    s = (raw or "").strip()
    if not INT_RE.match(s):
        want = "正整数" if lo > 0 else "非负整数"
        errors.append("%s必须是%s（收到：%r）" % (label, want, raw if raw != "" else "空"))
        return None
    v = int(s)
    if not (lo <= v <= hi):
        errors.append("%s须在 %d ~ %d 之间（收到：%d）" % (label, lo, hi, v))
        return None
    return v


def validate(form):
    """校验表单。form 需提供 get(name) 与 getlist(name)。

    返回 (cleaned, errors)：有错误时 cleaned 为 None，调用方不得保存。
    """
    errors = []

    name = (form.get("name") or "").strip()
    if len(name) > NAME_HI:
        errors.append("任务名称不能超过 %d 个字符" % NAME_HI)
    name = name or "未命名任务"

    sheet_w = _parse_int(form.get("sheet_w"), DIM_LO, DIM_HI, "母纸宽度", errors)
    sheet_h = _parse_int(form.get("sheet_h"), DIM_LO, DIM_HI, "母纸高度", errors)
    kerf = _parse_int(form.get("kerf"), 0, KERF_HI, "刀缝宽度", errors)
    max_sheets = _parse_int(form.get("max_sheets"), 1, SHEETS_HI, "张数上限", errors)
    budget = _parse_int(form.get("search_budget"), 1, BUDGET_HI, "搜索状态数上限", errors)

    widths = form.getlist("item_width")
    heights = form.getlist("item_height")
    qtys = form.getlist("item_qty")
    rots = form.getlist("item_rot")

    items = []
    total_qty = 0
    if not (len(widths) == len(heights) == len(qtys) == len(rots)):
        errors.append("成品行数据不完整，请检查每一行")
    elif len(widths) > MAX_TYPES:
        errors.append("成品种类最多 %d 种" % MAX_TYPES)
    else:
        for i in range(len(widths)):
            w_raw, h_raw, q_raw = widths[i].strip(), heights[i].strip(), qtys[i].strip()
            r_raw = rots[i].strip()
            if not w_raw and not h_raw and not q_raw:
                continue  # 整行空白视为未填写
            label = "成品第 %d 行" % (i + 1)
            if r_raw not in ("0", "1"):
                errors.append("%s：旋转标志非法" % label)
                continue
            w = _parse_int(w_raw, DIM_LO, DIM_HI, label + "宽度", errors)
            h = _parse_int(h_raw, DIM_LO, DIM_HI, label + "高度", errors)
            q = _parse_int(q_raw, 1, QTY_HI, label + "份数", errors)
            if w is not None and h is not None and q is not None:
                items.append({"width": w, "height": h, "quantity": q,
                              "rotatable": r_raw == "1"})
                total_qty += q
        if not items:
            errors.append("至少需要填写一种成品")
        if total_qty > TOTAL_QTY_HI:
            errors.append("成品总份数不能超过 %d" % TOTAL_QTY_HI)

    if errors:
        return None, errors
    return {
        "name": name,
        "sheet_w": sheet_w,
        "sheet_h": sheet_h,
        "kerf": kerf,
        "max_sheets": max_sheets,
        "search_budget": budget,
        "items": items,
    }, []
