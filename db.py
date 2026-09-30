"""SQLite 存储层：任务、输入版本、成品明细、求解方案。

输入每次修改都会生成新的版本（version_no 递增），方案绑定到具体版本；
任务的当前版本一旦前进，旧版本上的方案即自动失效。
"""
from __future__ import annotations

import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL DEFAULT '未命名任务',
  created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS versions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id INTEGER NOT NULL REFERENCES jobs(id),
  version_no INTEGER NOT NULL,
  sheet_w INTEGER NOT NULL,
  sheet_h INTEGER NOT NULL,
  kerf INTEGER NOT NULL,
  max_sheets INTEGER NOT NULL,
  search_budget INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
  UNIQUE(job_id, version_no)
);
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  version_id INTEGER NOT NULL REFERENCES versions(id),
  width INTEGER NOT NULL,
  height INTEGER NOT NULL,
  quantity INTEGER NOT NULL,
  rotatable INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS solutions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  version_id INTEGER NOT NULL REFERENCES versions(id),
  status TEXT NOT NULL,              -- solved | infeasible | budget_exhausted
  sheets_used INTEGER,
  states_explored INTEGER NOT NULL,
  elapsed_ms INTEGER NOT NULL,
  reason TEXT,
  result_json TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_versions_job ON versions(job_id, version_no);
CREATE INDEX IF NOT EXISTS idx_items_version ON items(version_id);
CREATE INDEX IF NOT EXISTS idx_solutions_version ON solutions(version_id);
"""


def connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path):
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


# ---- 查询 ----

def list_jobs(conn):
    jobs = conn.execute("SELECT * FROM jobs ORDER BY id DESC").fetchall()
    out = []
    for j in jobs:
        ver = current_version(conn, j["id"])
        sol = latest_solution(conn, ver["id"]) if ver else None
        out.append({"job": j, "version": ver, "solution": sol})
    return out


def get_job(conn, job_id):
    return conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()


def current_version(conn, job_id):
    return conn.execute(
        "SELECT * FROM versions WHERE job_id=? ORDER BY version_no DESC LIMIT 1",
        (job_id,)).fetchone()


def get_version(conn, version_id):
    return conn.execute("SELECT * FROM versions WHERE id=?", (version_id,)).fetchone()


def version_items(conn, version_id):
    return conn.execute(
        "SELECT * FROM items WHERE version_id=? ORDER BY id", (version_id,)).fetchall()


def latest_solution(conn, version_id):
    return conn.execute(
        "SELECT * FROM solutions WHERE version_id=? ORDER BY id DESC LIMIT 1",
        (version_id,)).fetchone()


def get_solution(conn, solution_id):
    return conn.execute("SELECT * FROM solutions WHERE id=?", (solution_id,)).fetchone()


def job_solutions(conn, job_id):
    return conn.execute(
        "SELECT s.*, v.version_no FROM solutions s "
        "JOIN versions v ON v.id = s.version_id "
        "WHERE v.job_id=? ORDER BY s.id DESC", (job_id,)).fetchall()


# ---- 写入（仅在输入校验通过后调用） ----

def create_job(conn, cleaned):
    cur = conn.execute("INSERT INTO jobs (name) VALUES (?)", (cleaned["name"],))
    job_id = cur.lastrowid
    insert_version(conn, job_id, 1, cleaned)
    return job_id


def insert_version(conn, job_id, version_no, cleaned):
    cur = conn.execute(
        "INSERT INTO versions (job_id, version_no, sheet_w, sheet_h, kerf,"
        " max_sheets, search_budget) VALUES (?,?,?,?,?,?,?)",
        (job_id, version_no, cleaned["sheet_w"], cleaned["sheet_h"], cleaned["kerf"],
         cleaned["max_sheets"], cleaned["search_budget"]))
    vid = cur.lastrowid
    for it in cleaned["items"]:
        conn.execute(
            "INSERT INTO items (version_id, width, height, quantity, rotatable)"
            " VALUES (?,?,?,?,?)",
            (vid, it["width"], it["height"], it["quantity"],
             1 if it["rotatable"] else 0))
    return vid


def rename_job(conn, job_id, name):
    conn.execute("UPDATE jobs SET name=? WHERE id=?", (name, job_id))


def save_solution(conn, version_id, res):
    import json
    cur = conn.execute(
        "INSERT INTO solutions (version_id, status, sheets_used, states_explored,"
        " elapsed_ms, reason, result_json) VALUES (?,?,?,?,?,?,?)",
        (version_id, res["status"], res.get("sheets_used"), res["states"],
         res["elapsed_ms"], res.get("reason"),
         json.dumps(res["result"], ensure_ascii=False)
         if res["status"] == "solved" else None))
    return cur.lastrowid
