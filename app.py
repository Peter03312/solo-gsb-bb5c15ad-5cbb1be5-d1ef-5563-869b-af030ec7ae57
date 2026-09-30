"""矩形纸张裁切排样 Web 应用（仅依赖 Python 标准库）。

启动：python3 app.py  （默认监听 0.0.0.0:8000，可用 PORT 环境变量修改）
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote

import db
import solver
import validation
import views

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data"))
DB_PATH = os.environ.get("DB_PATH", os.path.join(DATA_DIR, "app.db"))
PORT = int(os.environ.get("PORT", "8000"))
SOLVER_TIME_LIMIT = float(os.environ.get("SOLVER_TIME_LIMIT", "30"))
STATIC_DIR = os.path.join(BASE_DIR, "static")


class Form:
    """application/x-www-form-urlencoded 表单封装。"""

    def __init__(self, qs):
        self._data = {k: v for k, v in qs.items()}

    def get(self, name, default=""):
        vals = self._data.get(name)
        return vals[0] if vals else default

    def getlist(self, name):
        return list(self._data.get(name, []))


def form_values(form):
    """把原始表单转成模板可回填的 values（不校验）。"""
    n = max(len(form.getlist("item_width")), len(form.getlist("item_height")),
            len(form.getlist("item_qty")), len(form.getlist("item_rot")))
    items = []
    for i in range(n):
        w = form.getlist("item_width")
        h = form.getlist("item_height")
        q = form.getlist("item_qty")
        r = form.getlist("item_rot")
        items.append({
            "width": w[i] if i < len(w) else "",
            "height": h[i] if i < len(h) else "",
            "quantity": q[i] if i < len(q) else "",
            "rotatable": r[i] if i < len(r) else "0",
        })
    return {
        "name": form.get("name"),
        "sheet_w": form.get("sheet_w"),
        "sheet_h": form.get("sheet_h"),
        "kerf": form.get("kerf"),
        "max_sheets": form.get("max_sheets"),
        "search_budget": form.get("search_budget"),
        "items": items,
    }


def version_values(version, items):
    return {
        "name": None,  # 由调用方填
        "version_no": version["version_no"],
        "sheet_w": version["sheet_w"],
        "sheet_h": version["sheet_h"],
        "kerf": version["kerf"],
        "max_sheets": version["max_sheets"],
        "search_budget": version["search_budget"],
        "items": [{"width": it["width"], "height": it["height"],
                   "quantity": it["quantity"], "rotatable": "1" if it["rotatable"] else "0"}
                  for it in items],
    }


def inputs_equal(version, items, cleaned):
    """判断 cleaned 的裁切输入与当前版本是否完全一致（名称除外）。"""
    if (version["sheet_w"], version["sheet_h"], version["kerf"],
            version["max_sheets"], version["search_budget"]) != \
            (cleaned["sheet_w"], cleaned["sheet_h"], cleaned["kerf"],
             cleaned["max_sheets"], cleaned["search_budget"]):
        return False
    old = [(it["width"], it["height"], it["quantity"], it["rotatable"]) for it in items]
    new = [(it["width"], it["height"], it["quantity"], 1 if it["rotatable"] else 0)
           for it in cleaned["items"]]
    return old == new


def run_solver(conn, version):
    """对指定输入版本运行求解器并保存方案。"""
    items = db.version_items(conn, version["id"])
    item_dicts = [{"width": it["width"], "height": it["height"],
                   "quantity": it["quantity"], "rotatable": bool(it["rotatable"])}
                  for it in items]
    res = solver.solve(version["sheet_w"], version["sheet_h"], version["kerf"],
                       version["max_sheets"], item_dicts, version["search_budget"],
                       time_limit=SOLVER_TIME_LIMIT)
    return db.save_solution(conn, version["id"], res)


# ---------------- 页面处理 ----------------

def page_index(conn, **_):
    return 200, views.index_page(db.list_jobs(conn))


def page_job_new(conn, **_):
    values = {"sheet_w": 889, "sheet_h": 1194, "kerf": 3, "max_sheets": 10,
              "search_budget": 100000,
              "items": [{"width": 300, "height": 200, "quantity": 4, "rotatable": "1"}]}
    return 200, views.form_page("/jobs", values, [])


def page_job_create(conn, form, **_):
    cleaned, errors = validation.validate(form)
    if errors:
        return 400, views.form_page("/jobs", form_values(form), errors)
    job_id = db.create_job(conn, cleaned)
    run_solver(conn, db.current_version(conn, job_id))
    conn.commit()
    return "redirect", "/jobs/%d?flash=%s" % (
        job_id, quote("任务已创建（输入版本 v1），求解结果见下。"))


def _load_job(conn, job_id):
    job = db.get_job(conn, job_id)
    if not job:
        return None
    return job


def page_job_detail(conn, job_id, query, **_):
    job = _load_job(conn, job_id)
    if not job:
        return 404, views.message_page("未找到", "任务 #%s 不存在。" % job_id)
    version = db.current_version(conn, job_id)
    items = db.version_items(conn, version["id"])
    solution = db.latest_solution(conn, version["id"])
    history = db.job_solutions(conn, job_id)
    result = None
    if solution and solution["status"] == "solved" and solution["result_json"]:
        result = json.loads(solution["result_json"])
    flash = None
    if query.get("flash"):
        flash = ("ok", query["flash"][0])
    return 200, views.detail_page(job, version, items, solution, result, history,
                                  flash=flash)


def page_job_edit(conn, job_id, **_):
    job = _load_job(conn, job_id)
    if not job:
        return 404, views.message_page("未找到", "任务 #%s 不存在。" % job_id)
    version = db.current_version(conn, job_id)
    items = db.version_items(conn, version["id"])
    values = version_values(version, items)
    values["name"] = job["name"]
    return 200, views.form_page("/jobs/%d/edit" % job_id, values, [], job=job)


def page_job_update(conn, form, job_id, **_):
    job = _load_job(conn, job_id)
    if not job:
        return 404, views.message_page("未找到", "任务 #%s 不存在。" % job_id)
    version = db.current_version(conn, job_id)
    cleaned, errors = validation.validate(form)
    if errors:
        values = form_values(form)
        values["version_no"] = version["version_no"]
        return 400, views.form_page("/jobs/%d/edit" % job_id, values, errors, job=job)
    items = db.version_items(conn, version["id"])
    if inputs_equal(version, items, cleaned):
        # 裁切输入未变：仅更新名称，不生成新版本，方案保持有效
        db.rename_job(conn, job_id, cleaned["name"])
        conn.commit()
        return "redirect", "/jobs/%d?flash=%s" % (
            job_id, quote("裁切输入未变化：仅更新任务名称，既有方案仍然有效。"))
    db.insert_version(conn, job_id, version["version_no"] + 1, cleaned)
    db.rename_job(conn, job_id, cleaned["name"])
    run_solver(conn, db.current_version(conn, job_id))
    conn.commit()
    return "redirect", "/jobs/%d?flash=%s" % (
        job_id, quote("输入已修改，生成输入版本 v%d；旧版本方案已全部失效。"
                      % (version["version_no"] + 1)))


def page_solution_export(conn, job_id, solution_id, **_):
    job = _load_job(conn, job_id)
    if not job:
        return 404, views.message_page("未找到", "任务 #%s 不存在。" % job_id)
    sol = db.get_solution(conn, solution_id)
    if not sol:
        return 404, views.message_page("未找到", "方案 #%s 不存在。" % solution_id)
    sol_version = db.get_version(conn, sol["version_id"])
    if not sol_version or sol_version["job_id"] != job["id"]:
        return 404, views.message_page("未找到", "方案 #%s 不属于任务 #%s。"
                                       % (solution_id, job_id))
    cur = db.current_version(conn, job_id)
    if sol["version_id"] != cur["id"]:
        return 409, views.refused_page(
            job, sol, sol_version, cur,
            "该方案基于输入版本 v%d，而任务当前输入版本为 v%d：方案已失效，"
            "不得用于生产。请使用当前版本的方案。"
            % (sol_version["version_no"], cur["version_no"]))
    if sol["status"] != "solved":
        return 409, views.refused_page(
            job, sol, sol_version, cur,
            "该版本未求得可行方案（%s），无可导出的裁切单。"
            % views.status_label(sol["status"]))
    items = db.version_items(conn, sol["version_id"])
    result = json.loads(sol["result_json"])
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    return 200, views.export_page(job, sol_version, items, sol, result, now)


# ---------------- HTTP 框架 ----------------

ROUTES = [
    ("GET", re.compile(r"/"), page_index),
    ("GET", re.compile(r"/jobs/new"), page_job_new),
    ("POST", re.compile(r"/jobs"), page_job_create),
    ("GET", re.compile(r"/jobs/(?P<job_id>\d+)"), page_job_detail),
    ("GET", re.compile(r"/jobs/(?P<job_id>\d+)/edit"), page_job_edit),
    ("POST", re.compile(r"/jobs/(?P<job_id>\d+)/edit"), page_job_update),
    ("GET", re.compile(r"/jobs/(?P<job_id>\d+)/solutions/(?P<solution_id>\d+)/export"),
     page_solution_export),
]


class Handler(BaseHTTPRequestHandler):
    server_version = "PaperCutter/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # 简化日志
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))

    # -- 工具 --
    def _send_html(self, status, html):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location):
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _read_form(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        length = min(length, 1_000_000)
        raw = self.rfile.read(length).decode("utf-8", "replace")
        return Form(parse_qs(raw, keep_blank_values=True))

    # -- 分发 --
    def _dispatch(self, method):
        parsed = urlparse(self.path)
        path = parsed.path
        if method == "GET" and path.startswith("/static/"):
            return self._serve_static(path)
        query = parse_qs(parsed.query)
        form = self._read_form() if method == "POST" else None
        conn = db.connect(DB_PATH)
        try:
            for m, pattern, handler in ROUTES:
                if m != method:
                    continue
                match = pattern.fullmatch(path)
                if not match:
                    continue
                kwargs = {k: int(v) for k, v in match.groupdict().items()}
                if form is not None:
                    result = handler(conn, form=form, query=query, **kwargs)
                else:
                    result = handler(conn, query=query, **kwargs)
                conn.commit()
                status, payload = result
                if status == "redirect":
                    return self._redirect(payload)
                return self._send_html(status, payload)
            self._send_html(404, views.message_page("404", "页面不存在。"))
        except BrokenPipeError:
            pass
        except Exception as exc:  # 兜底，避免连接悬挂
            conn.rollback()
            try:
                self._send_html(500, views.message_page("服务器内部错误", str(exc)))
            except Exception:
                pass
        finally:
            conn.close()

    def _serve_static(self, path):
        name = os.path.basename(path)
        full = os.path.join(STATIC_DIR, name)
        if not os.path.isfile(full):
            return self._send_html(404, views.message_page("404", "资源不存在。"))
        ctype = "text/css; charset=utf-8" if name.endswith(".css") else "application/octet-stream"
        with open(full, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")


def main():
    db.init_db(DB_PATH)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("纸张裁切排样服务已启动：http://0.0.0.0:%d （数据库：%s）" % (PORT, DB_PATH))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
