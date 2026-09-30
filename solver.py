"""贯通式（每刀贯穿当前余料）矩形排样求解器。

搜索方式：按“先大后小”的顺序逐件放置成品。每件成品可以放到任意一张
已开启母纸的任意空闲矩形（置于其左下角），也可以开启一张新母纸。
放置后按两种贯通切法把余料一分为二，刀缝在切口处扣除：

* 切法一：先竖切（贯穿整个矩形高度），再对左侧条带横切；
* 切法二：先横切（贯穿整个矩形宽度），再对下侧条带竖切。

找到任意可行方案即返回（不要求最优）；探索状态数（或时间）超出预算时
抛出 BudgetExhausted；整个搜索空间穷尽仍未找到时才判定无解。
"""
from __future__ import annotations

import sys
import time


class BudgetExhausted(Exception):
    """搜索预算（状态数上限或时间上限）耗尽。"""


class _Node:
    """切分树节点：一个矩形区域。叶子要么是空闲余料，要么放着一件成品。"""

    __slots__ = ("x", "y", "w", "h", "item", "pw", "ph", "rot", "style", "right", "top")

    def __init__(self, x, y, w, h):
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.item = None   # 成品类型下标（排序后）；None 表示空闲叶
        self.pw = 0        # 已放置成品的宽
        self.ph = 0        # 已放置成品的高
        self.rot = False   # 是否旋转放置
        self.style = None  # 1=先竖切，2=先横切
        self.right = None  # 右侧余料子树
        self.top = None    # 上侧余料子树


def solve(sheet_w, sheet_h, kerf, max_sheets, items, budget, time_limit=30.0):
    """尝试为全部成品份数找到贯通式排样方案。

    参数:
        sheet_w, sheet_h: 母纸宽/高（mm，正整数）
        kerf: 刀缝宽度（mm，非负整数）
        max_sheets: 母纸张数上限（正整数）
        items: [{"width","height","quantity","rotatable"}, ...]
        budget: 搜索状态数上限（正整数）
        time_limit: 时间预算（秒），超时同样按“预算耗尽”处理
    返回:
        solved:  {"status","states","elapsed_ms","sheets_used","result"}
        其他:    {"status": "infeasible"|"budget_exhausted","states","elapsed_ms"[,"reason"]}
    """
    t0 = time.monotonic()
    deadline = t0 + max(0.1, float(time_limit))

    # 类型预处理：展开允许的方向（不旋转的成品只有原始方向）
    types = []
    for orig, it in enumerate(items):
        w, h = int(it["width"]), int(it["height"])
        orients = {(w, h, False)}
        if it["rotatable"] and w != h:
            orients.add((h, w, True))
        types.append({
            "orig": orig, "w": w, "h": h, "qty": int(it["quantity"]),
            "orients": sorted(orients, key=lambda o: (o[0] * o[1], o[0]), reverse=True),
        })

    # 预检：任何方向都放不进母纸的成品直接判无解（搜索空间为空，属于已穷尽）
    for t in types:
        if not any(ow <= sheet_w and oh <= sheet_h for (ow, oh, _) in t["orients"]):
            return {
                "status": "infeasible", "states": 0,
                "elapsed_ms": int((time.monotonic() - t0) * 1000),
                "reason": "成品 %d（%d×%d mm）在任何允许方向下都放不进母纸 %d×%d mm"
                          % (t["orig"] + 1, t["w"], t["h"], sheet_w, sheet_h),
            }

    # 大件优先：最长边降序、面积降序
    types.sort(key=lambda t: (max(t["w"], t["h"]), t["w"] * t["h"]), reverse=True)
    remaining0 = tuple(t["qty"] for t in types)
    total = sum(remaining0)
    sys.setrecursionlimit(max(10000, total * 4 + 1000))

    states = 0
    memo = set()      # 已失败的规范化状态
    sheets = []       # 每张纸一棵切分树（_Node 根）

    def free_sizes(root, out):
        stack = [root]
        while stack:
            n = stack.pop()
            if n.right is None and n.top is None:
                if n.item is None:
                    out.append((n.w, n.h))
            else:
                if n.right is not None:
                    stack.append(n.right)
                if n.top is not None:
                    stack.append(n.top)

    def sheet_key(root):
        out = []
        free_sizes(root, out)
        return tuple(sorted(out))

    def state_key(remaining):
        return (remaining, tuple(sorted(sheet_key(s) for s in sheets)))

    def collect_leaves(root, out):
        stack = [root]
        while stack:
            n = stack.pop()
            if n.right is None and n.top is None:
                if n.item is None:
                    out.append(n)
            else:
                if n.right is not None:
                    stack.append(n.right)
                if n.top is not None:
                    stack.append(n.top)

    def place(node, tidx, pw, ph, rot, style, open_orients):
        """在空闲叶 node 的左下角放置成品并切分余料。返回子矩形签名（用于去重）。"""
        rw = node.w - pw - kerf
        rh = node.h - ph - kerf
        right = top = None

        def usable(w, h):
            return any(ow <= w and oh <= h for (ow, oh, _) in open_orients)

        if style == 1:
            if rw > 0 and usable(rw, node.h):
                right = _Node(node.x + pw + kerf, node.y, rw, node.h)
            if rh > 0 and usable(pw, rh):
                top = _Node(node.x, node.y + ph + kerf, pw, rh)
        else:
            if rw > 0 and usable(rw, ph):
                right = _Node(node.x + pw + kerf, node.y, rw, ph)
            if rh > 0 and usable(node.w, rh):
                top = _Node(node.x, node.y + ph + kerf, node.w, rh)
        node.item = tidx
        node.pw, node.ph, node.rot, node.style = pw, ph, rot, style
        node.right, node.top = right, top
        sig = []
        if right is not None:
            sig.append((right.x, right.y, right.w, right.h))
        if top is not None:
            sig.append((top.x, top.y, top.w, top.h))
        return tuple(sorted(sig))

    def unplace(node):
        node.item = None
        node.pw = node.ph = 0
        node.rot = False
        node.style = None
        node.right = node.top = None

    def dfs(remaining):
        nonlocal states
        states += 1
        if states > budget or time.monotonic() > deadline:
            raise BudgetExhausted()
        if not any(remaining):
            return True
        key = state_key(remaining)
        if key in memo:
            return False
        i = 0
        while remaining[i] == 0:
            i += 1
        t = types[i]
        new_rem = remaining[:i] + (remaining[i] - 1,) + remaining[i + 1:]
        open_orients = [o for j, tj in enumerate(types) if new_rem[j] > 0 for o in tj["orients"]]

        # 1) 放进已开启纸张的某个空闲矩形
        tried_sheet_keys = set()
        for root in list(sheets):
            sk = sheet_key(root)
            if sk in tried_sheet_keys:
                continue
            tried_sheet_keys.add(sk)
            leaves = []
            collect_leaves(root, leaves)
            tried_rects = set()
            for leaf in leaves:
                if (leaf.w, leaf.h) in tried_rects:
                    continue
                tried_rects.add((leaf.w, leaf.h))
                for (ow, oh, rot) in t["orients"]:
                    if ow > leaf.w or oh > leaf.h:
                        continue
                    tried_sigs = set()
                    for style in (1, 2):
                        sig = place(leaf, i, ow, oh, rot, style, open_orients)
                        if sig in tried_sigs:
                            unplace(leaf)
                            continue
                        tried_sigs.add(sig)
                        if dfs(new_rem):
                            return True
                        unplace(leaf)

        # 2) 开启一张新母纸
        if len(sheets) < max_sheets:
            root = _Node(0, 0, sheet_w, sheet_h)
            for (ow, oh, rot) in t["orients"]:
                if ow > sheet_w or oh > sheet_h:
                    continue
                tried_sigs = set()
                for style in (1, 2):
                    sig = place(root, i, ow, oh, rot, style, open_orients)
                    if sig in tried_sigs:
                        unplace(root)
                        continue
                    tried_sigs.add(sig)
                    sheets.append(root)
                    if dfs(new_rem):
                        return True
                    sheets.pop()
                    unplace(root)

        memo.add(key)
        return False

    try:
        ok = dfs(remaining0)
    except BudgetExhausted:
        return {
            "status": "budget_exhausted", "states": states,
            "elapsed_ms": int((time.monotonic() - t0) * 1000),
        }
    if not ok:
        return {
            "status": "infeasible", "states": states,
            "elapsed_ms": int((time.monotonic() - t0) * 1000),
        }

    result = _extract(sheets, types, kerf, len(items))
    return {
        "status": "solved",
        "states": states,
        "elapsed_ms": int((time.monotonic() - t0) * 1000),
        "sheets_used": len(sheets),
        "result": result,
    }


def _extract(sheets, types, kerf, n_types):
    """把切分树转成排样、贯通裁切步骤（执行顺序）与废料清单。"""
    out_sheets = []
    counts = [0] * n_types
    for root in sheets:
        placements, cuts, waste = [], [], []
        _walk(root, types, kerf, placements, cuts, waste, counts)
        out_sheets.append({"placements": placements, "cuts": cuts, "waste": waste})
    return {"sheets": out_sheets, "counts": counts}


def _walk(n, types, kerf, placements, cuts, waste, counts):
    if n.item is None:
        waste.append({"rect": [n.x, n.y, n.w, n.h], "kind": "waste"})
        return
    t = types[n.item]
    counts[t["orig"]] += 1
    placements.append({"x": n.x, "y": n.y, "w": n.pw, "h": n.ph,
                       "type": t["orig"], "rot": n.rot})
    rw = n.w - n.pw - kerf
    rh = n.h - n.ph - kerf
    if n.style == 1:
        # 先竖切（贯穿整个矩形），再对左侧条带横切
        if n.pw < n.w:
            cuts.append({"rect": [n.x, n.y, n.w, n.h], "dir": "V",
                         "offset": n.pw, "kerf": kerf})
            kw = min(kerf, n.w - n.pw)
            if kw > 0:
                waste.append({"rect": [n.x + n.pw, n.y, kw, n.h], "kind": "kerf"})
        if n.ph < n.h:
            cuts.append({"rect": [n.x, n.y, n.pw, n.h], "dir": "H",
                         "offset": n.ph, "kerf": kerf})
            kw = min(kerf, n.h - n.ph)
            if kw > 0:
                waste.append({"rect": [n.x, n.y + n.ph, n.pw, kw], "kind": "kerf"})
    else:
        # 先横切（贯穿整个矩形），再对下侧条带竖切
        if n.ph < n.h:
            cuts.append({"rect": [n.x, n.y, n.w, n.h], "dir": "H",
                         "offset": n.ph, "kerf": kerf})
            kw = min(kerf, n.h - n.ph)
            if kw > 0:
                waste.append({"rect": [n.x, n.y + n.ph, n.w, kw], "kind": "kerf"})
        if n.pw < n.w:
            cuts.append({"rect": [n.x, n.y, n.w, n.ph], "dir": "V",
                         "offset": n.pw, "kerf": kerf})
            kw = min(kerf, n.w - n.pw)
            if kw > 0:
                waste.append({"rect": [n.x + n.pw, n.y, kw, n.ph], "kind": "kerf"})
    # 子区域：有子树则递归；没有子树但几何上存在则是废料
    if n.right is not None:
        _walk(n.right, types, kerf, placements, cuts, waste, counts)
    elif rw > 0:
        waste.append({"rect": [n.x + n.pw + kerf, n.y, rw,
                               n.h if n.style == 1 else n.ph], "kind": "waste"})
    if n.top is not None:
        _walk(n.top, types, kerf, placements, cuts, waste, counts)
    elif rh > 0:
        waste.append({"rect": [n.x, n.y + n.ph + kerf,
                               n.pw if n.style == 1 else n.w, rh], "kind": "waste"})
