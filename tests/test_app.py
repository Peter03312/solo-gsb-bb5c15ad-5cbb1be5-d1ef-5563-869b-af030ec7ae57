"""Web 层测试：输入校验（非法不保存）、求解展示、版本失效、导出拒绝、预算重试。"""
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP = tempfile.mkdtemp(prefix="papercut-test-")
os.environ["DATA_DIR"] = _TMP
os.environ["DB_PATH"] = os.path.join(_TMP, "test.db")
os.environ["PORT"] = "8123"

import app as appmod  # noqa: E402
import db as dbmod  # noqa: E402

BASE = "http://127.0.0.1:8123"

VALID = {
    "name": "测试任务",
    "sheet_w": "889", "sheet_h": "1194", "kerf": "3",
    "max_sheets": "10", "search_budget": "100000",
    "item_width": ["300", "150"],
    "item_height": ["200", "100"],
    "item_qty": ["4", "6"],
    "item_rot": ["1", "0"],
}


def post(path, data):
    body = urllib.parse.urlencode(data, doseq=True).encode()
    req = urllib.request.Request(BASE + path, data=body, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.status, resp.read().decode("utf-8"), resp.geturl()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8"), e.geturl()


def get(path):
    try:
        resp = urllib.request.urlopen(BASE + path, timeout=15)
        return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def db_counts():
    conn = dbmod.connect(appmod.DB_PATH)
    try:
        return {t: conn.execute("SELECT COUNT(*) c FROM %s" % t).fetchone()["c"]
                for t in ("jobs", "versions", "items", "solutions")}
    finally:
        conn.close()


def query(sql, args=()):
    conn = dbmod.connect(appmod.DB_PATH)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def latest_job_id():
    return query("SELECT MAX(id) i FROM jobs")[0]["i"]


class TestWebApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dbmod.init_db(appmod.DB_PATH)
        cls.server = appmod.ThreadingHTTPServer(("127.0.0.1", 8123), appmod.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        conn = dbmod.connect(appmod.DB_PATH)
        for t in ("solutions", "items", "versions", "jobs"):
            conn.execute("DELETE FROM %s" % t)
        conn.commit()
        conn.close()

    # ---- 校验：非法输入不得保存 ----

    def test_invalid_inputs_not_saved(self):
        bad_payloads = []
        for field, bad in [("sheet_w", "0"), ("sheet_w", "-5"), ("sheet_w", "abc"),
                           ("sheet_w", "10.5"), ("sheet_h", ""),
                           ("kerf", "-1"), ("kerf", "1.5"),
                           ("max_sheets", "0"), ("max_sheets", "x"),
                           ("search_budget", "0"), ("search_budget", "-3")]:
            d = dict(VALID)
            d[field] = bad
            bad_payloads.append(d)
        d = dict(VALID)
        d["item_qty"] = ["0", "6"]
        bad_payloads.append(d)
        d = dict(VALID)
        d["item_width"] = []
        d["item_height"] = []
        d["item_qty"] = []
        d["item_rot"] = []
        bad_payloads.append(d)
        d = dict(VALID)
        d["item_width"] = ["300", ""]   # 第二行缺宽
        d["item_height"] = ["200", "100"]
        d["item_qty"] = ["4", "2"]
        d["item_rot"] = ["1", "0"]
        bad_payloads.append(d)

        for payload in bad_payloads:
            status, body, _ = post("/jobs", payload)
            self.assertEqual(status, 400, payload)
            self.assertIn("输入非法", body)
        self.assertEqual(db_counts()["jobs"], 0)
        self.assertEqual(db_counts()["versions"], 0)
        self.assertEqual(db_counts()["items"], 0)
        self.assertEqual(db_counts()["solutions"], 0)

    def test_kerf_zero_is_valid(self):
        d = dict(VALID)
        d["kerf"] = "0"
        status, body, _ = post("/jobs", d)
        self.assertEqual(status, 200)
        self.assertEqual(db_counts()["jobs"], 1)

    # ---- 创建与求解展示 ----

    def test_create_and_solve(self):
        status, body, url = post("/jobs", VALID)
        self.assertEqual(status, 200)
        self.assertIn("/jobs/%d" % latest_job_id(), url)
        self.assertIn("已找到可行方案", body)
        self.assertIn("v1", body)
        self.assertIn("裁切步骤", body)
        self.assertIn("实际成品数", body)
        self.assertIn("<svg", body)
        counts = db_counts()
        self.assertEqual((counts["jobs"], counts["versions"], counts["solutions"]),
                         (1, 1, 1))
        sol = query("SELECT * FROM solutions")[0]
        self.assertEqual(sol["status"], "solved")
        self.assertEqual(sol["sheets_used"] >= 1, True)

    def test_export_shows_version(self):
        post("/jobs", VALID)
        sol = query("SELECT * FROM solutions")[0]
        status, body = get("/jobs/%d/solutions/%d/export" % (latest_job_id(), sol["id"]))
        self.assertEqual(status, 200)
        self.assertIn("裁切单", body)
        self.assertIn("输入版本", body)
        self.assertIn("v1", body)
        self.assertIn("贯通切割", body)

    # ---- 版本失效 ----

    def test_edit_invalidates_old_solution(self):
        post("/jobs", VALID)
        jid = latest_job_id()
        old_sol = query("SELECT * FROM solutions")[0]
        d = dict(VALID)
        d["sheet_w"] = "900"   # 修改任一输入
        status, body, _ = post("/jobs/%d/edit" % jid, d)
        self.assertEqual(status, 200)
        self.assertIn("v2", body)
        self.assertIn("已失效", body)
        # 旧方案导出被拒
        status, body = get("/jobs/%d/solutions/%d/export" % (jid, old_sol["id"]))
        self.assertEqual(status, 409)
        self.assertIn("导出被拒绝", body)
        self.assertIn("v1", body)
        self.assertIn("v2", body)
        # 新方案导出正常
        new_sol = query("SELECT * FROM solutions ORDER BY id DESC")[0]
        status, body = get("/jobs/%d/solutions/%d/export" % (jid, new_sol["id"]))
        self.assertEqual(status, 200)
        self.assertIn("v2", body)

    def test_name_only_edit_keeps_solution_valid(self):
        post("/jobs", VALID)
        jid = latest_job_id()
        old_sol = query("SELECT * FROM solutions")[0]
        d = dict(VALID)
        d["name"] = "改名而已"
        status, body, _ = post("/jobs/%d/edit" % jid, d)
        self.assertEqual(status, 200)
        self.assertEqual(db_counts()["versions"], 1)  # 未产生新版本
        status, body = get("/jobs/%d/solutions/%d/export" % (jid, old_sol["id"]))
        self.assertEqual(status, 200)
        self.assertIn("改名而已", body)

    def test_edit_invalid_input_not_saved(self):
        post("/jobs", VALID)
        jid = latest_job_id()
        d = dict(VALID)
        d["kerf"] = "-2"
        status, body, _ = post("/jobs/%d/edit" % jid, d)
        self.assertEqual(status, 400)
        self.assertIn("输入非法", body)
        self.assertEqual(db_counts()["versions"], 1)
        self.assertEqual(db_counts()["solutions"], 1)

    # ---- 无解与预算耗尽的区分 ----

    def test_infeasible_reported(self):
        d = dict(VALID)
        d["item_width"] = ["2000"]
        d["item_height"] = ["100"]
        d["item_qty"] = ["1"]
        d["item_rot"] = ["1"]
        status, body, _ = post("/jobs", d)
        self.assertEqual(status, 200)
        self.assertIn("搜索已穷尽", body)
        self.assertIn("无解", body)

    def test_budget_exhausted_then_retry(self):
        d = dict(VALID)
        d["search_budget"] = "1"
        status, body, _ = post("/jobs", d)
        self.assertEqual(status, 200)
        self.assertIn("预算耗尽", body)
        self.assertIn("不代表无解", body)
        # 调整预算重试（生成新版本并成功求解）
        d["search_budget"] = "100000"
        status, body, _ = post("/jobs/%d/edit" % latest_job_id(), d)
        self.assertEqual(status, 200)
        self.assertIn("已找到可行方案", body)
        self.assertIn("v2", body)

    # ---- 其他 ----

    def test_index_and_static(self):
        post("/jobs", VALID)
        status, body = get("/")
        self.assertEqual(status, 200)
        self.assertIn("测试任务", body)
        status, body = get("/static/style.css")
        self.assertEqual(status, 200)
        self.assertIn("sheet-svg", body)

    def test_404(self):
        status, _ = get("/jobs/999")
        self.assertEqual(status, 404)
        status, _ = get("/nope")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
