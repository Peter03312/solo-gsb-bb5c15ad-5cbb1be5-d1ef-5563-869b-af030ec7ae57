"""求解器测试：可行性、旋转限制、刀缝、预算语义，以及对输出方案的独立校验。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from solver import solve  # noqa: E402


def make_items(*specs):
    return [{"width": w, "height": h, "quantity": q, "rotatable": r}
            for w, h, q, r in specs]


def verify_sheet_tiling(sheet_w, sheet_h, sheet):
    """成品 + 废料 + 刀缝条必须恰好铺满整张母纸：不重叠、不越界、面积守恒。"""
    rects = []
    for p in sheet["placements"]:
        rects.append(("item", p["x"], p["y"], p["w"], p["h"]))
    for wst in sheet["waste"]:
        x, y, w, h = wst["rect"]
        rects.append((wst["kind"], x, y, w, h))
    for _, x, y, w, h in rects:
        assert w > 0 and h > 0, ("非正尺寸", (x, y, w, h))
        assert x >= 0 and y >= 0 and x + w <= sheet_w and y + h <= sheet_h, \
            ("越界", (x, y, w, h))
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            _, x1, y1, w1, h1 = rects[i]
            _, x2, y2, w2, h2 = rects[j]
            overlap = not (x1 + w1 <= x2 or x2 + w2 <= x1
                           or y1 + h1 <= y2 or y2 + h2 <= y1)
            assert not overlap, ("重叠", rects[i], rects[j])
    total = sum(w * h for _, _, _, w, h in rects)
    assert total == sheet_w * sheet_h, ("面积不守恒", total, sheet_w * sheet_h)


def verify_cuts(sheet_w, sheet_h, kerf, sheet):
    """按顺序模拟裁切步骤：每刀必须恰好落在当前某块余料上并贯穿它；
    切完后剩下的块必须正好是全部成品 + 全部废料。"""
    pieces = [(0, 0, sheet_w, sheet_h)]
    kerf_strips = []
    for cut in sheet["cuts"]:
        rect = tuple(cut["rect"])
        assert rect in pieces, ("切割对象不是当前余料", rect)
        pieces.remove(rect)
        x, y, w, h = rect
        d = cut["offset"]
        assert cut["kerf"] == kerf
        if cut["dir"] == "V":
            assert 0 < d < w, ("刀位不在余料内部", cut)
            a = (x, y, d, h)
            strip = (x + d, y, min(kerf, w - d), h)
            b = (x + d + kerf, y, w - d - kerf, h)
        else:
            assert 0 < d < h, ("刀位不在余料内部", cut)
            a = (x, y, w, d)
            strip = (x, y + d, w, min(kerf, h - d))
            b = (x, y + d + kerf, w, h - d - kerf)
        if strip[2] > 0 and strip[3] > 0:
            kerf_strips.append(strip)
        for p in (a, b):
            if p[2] > 0 and p[3] > 0:
                pieces.append(p)
    items = sorted((p["x"], p["y"], p["w"], p["h"]) for p in sheet["placements"])
    waste = sorted(tuple(wst["rect"]) for wst in sheet["waste"] if wst["kind"] == "waste")
    assert sorted(pieces) == sorted(items + waste), \
        ("裁切结果与排样不符", pieces, items + waste)
    kerf_waste = sorted(tuple(wst["rect"]) for wst in sheet["waste"] if wst["kind"] == "kerf")
    assert sorted(kerf_strips) == sorted(kerf_waste), \
        ("刀缝损耗记录不符", kerf_strips, kerf_waste)


def verify_solution(sheet_w, sheet_h, kerf, max_sheets, demands, res):
    assert res["status"] == "solved", res
    assert res["sheets_used"] <= max_sheets
    assert res["sheets_used"] == len(res["result"]["sheets"])
    # 实际成品数满足全部份数
    assert res["result"]["counts"] == [d[2] for d in demands]
    for sheet in res["result"]["sheets"]:
        verify_sheet_tiling(sheet_w, sheet_h, sheet)
        verify_cuts(sheet_w, sheet_h, kerf, sheet)
    # 旋转限制与方向
    for sheet in res["result"]["sheets"]:
        for p in sheet["placements"]:
            w, h, _, rot = demands[p["type"]]
            if rot:
                assert (p["w"], p["h"]) in ((w, h), (h, w))
                assert p["rot"] == ((p["w"], p["h"]) == (h, w) and (w, h) != (h, w))
            else:
                assert (p["w"], p["h"]) == (w, h)
                assert p["rot"] is False


class TestSolver(unittest.TestCase):
    def test_exact_fit_no_kerf(self):
        res = solve(100, 50, 0, 5, make_items((50, 50, 2, False)), 10000)
        verify_solution(100, 50, 0, 5, [(50, 50, 2, False)], res)
        self.assertEqual(res["sheets_used"], 1)

    def test_kerf_deducted_exactly(self):
        # 45 + 10(刀缝) + 45 = 100，恰好放下两件
        demands = [(45, 100, 2, False)]
        res = solve(100, 100, 10, 1, make_items(*demands), 10000)
        verify_solution(100, 100, 10, 1, demands, res)
        self.assertEqual(res["sheets_used"], 1)
        # 刀缝 11 时 45+11+45=101 > 100，一张纸放不下两件 → 无解
        res2 = solve(100, 100, 11, 1, make_items(*demands), 10000)
        self.assertEqual(res2["status"], "infeasible")
        # 但允许两张纸时仍可解（每件一张）
        res3 = solve(100, 100, 11, 2, make_items(*demands), 10000)
        verify_solution(100, 100, 11, 2, demands, res3)
        self.assertEqual(res3["sheets_used"], 2)

    def test_rotation_restriction(self):
        # 500×200 在 400×600 母纸上只有旋转后才放得下
        res_no = solve(400, 600, 0, 5, make_items((500, 200, 1, False)), 10000)
        self.assertEqual(res_no["status"], "infeasible")
        self.assertIn("放不进", res_no.get("reason", ""))
        demands = [(500, 200, 1, True)]
        res_yes = solve(400, 600, 0, 5, make_items(*demands), 10000)
        verify_solution(400, 600, 0, 5, demands, res_yes)
        p = res_yes["result"]["sheets"][0]["placements"][0]
        self.assertTrue(p["rot"])
        self.assertEqual((p["w"], p["h"]), (200, 500))

    def test_multi_sheet_and_sheet_limit(self):
        demands = [(60, 60, 2, False)]
        res = solve(100, 100, 0, 2, make_items(*demands), 10000)
        verify_solution(100, 100, 0, 2, demands, res)
        self.assertEqual(res["sheets_used"], 2)
        res1 = solve(100, 100, 0, 1, make_items(*demands), 10000)
        self.assertEqual(res1["status"], "infeasible")

    def test_budget_exhausted(self):
        res = solve(889, 1194, 3, 10, make_items((300, 200, 4, True)), 1)
        self.assertEqual(res["status"], "budget_exhausted")
        # 预算充足时同一问题可解
        demands = [(300, 200, 4, True)]
        res2 = solve(889, 1194, 3, 10, make_items(*demands), 100000)
        verify_solution(889, 1194, 3, 10, demands, res2)

    def test_split_style_two(self):
        # 需要“先横切”：A 横贯底部，B/C 并排在上
        demands = [(100, 40, 1, False), (40, 60, 1, False), (60, 60, 1, False)]
        res = solve(100, 100, 0, 1, make_items(*demands), 10000)
        verify_solution(100, 100, 0, 1, demands, res)
        self.assertEqual(res["sheets_used"], 1)

    def test_mixed_with_kerf(self):
        demands = [(120, 80, 3, True), (200, 100, 2, False), (50, 50, 5, True)]
        res = solve(500, 400, 2, 5, make_items(*demands), 200000)
        verify_solution(500, 400, 2, 5, demands, res)

    def test_counts_exact(self):
        demands = [(100, 100, 3, False), (60, 40, 7, True)]
        res = solve(400, 300, 0, 6, make_items(*demands), 200000)
        verify_solution(400, 300, 0, 6, demands, res)

    def test_oversize_item_infeasible_fast(self):
        res = solve(100, 100, 0, 5, make_items((200, 50, 1, True)), 10000)
        self.assertEqual(res["status"], "infeasible")
        self.assertEqual(res["states"], 0)

    def test_zero_kerf_allowed(self):
        # 每张 2×2 = 4 件，6 件需 2 张
        demands = [(30, 20, 6, False)]
        res = solve(60, 40, 0, 3, make_items(*demands), 10000)
        verify_solution(60, 40, 0, 3, demands, res)
        self.assertEqual(res["sheets_used"], 2)
        demands4 = [(30, 20, 4, False)]
        res4 = solve(60, 40, 0, 3, make_items(*demands4), 10000)
        verify_solution(60, 40, 0, 3, demands4, res4)
        self.assertEqual(res4["sheets_used"], 1)


if __name__ == "__main__":
    unittest.main()
