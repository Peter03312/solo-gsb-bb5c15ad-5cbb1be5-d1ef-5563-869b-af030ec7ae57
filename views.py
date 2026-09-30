"""服务端 HTML 渲染（全部用户输入均转义后输出）。"""
from __future__ import annotations

from html import escape as _esc

from svgrender import render_sheet_svg, type_color

STATUS_LABELS = {
    "solved": "已找到可行方案",
    "infeasible": "搜索已穷尽：无解",
    "budget_exhausted": "搜索预算耗尽",
}


def esc(s):
    return _esc(str(s), quote=True)


def status_label(status):
    return STATUS_LABELS.get(status, status)


def layout(title, body, flash=None):
    flash_html = ""
    if flash:
        kind, msg = flash
        flash_html = '<div class="flash %s">%s</div>' % (esc(kind), esc(msg))
    return """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%s · 纸张裁切排样</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<header class="no-print"><h1><a href="/">矩形纸张裁切排样</a></h1>
<nav><a href="/">任务列表</a> · <a href="/jobs/new">新建任务</a></nav>
</header>
%s
<main>
%s
</main>
</body>
</html>""" % (esc(title), flash_html, body)


# ---------- 任务列表 ----------

def index_page(rows):
    trs = []
    for r in rows:
        j, v, s = r["job"], r["version"], r["solution"]
        status = status_label(s["status"]) if s else "—"
        cls = "st-%s" % s["status"] if s else ""
        trs.append(
            "<tr><td>#%d</td><td><a href=\"/jobs/%d\">%s</a></td>"
            "<td>%s</td><td>v%d</td><td class=\"%s\">%s</td></tr>"
            % (j["id"], j["id"], esc(j["name"]), esc(j["created_at"]),
               v["version_no"] if v else 0, cls, esc(status)))
    table = ("<table class=\"tbl\"><thead><tr><th>ID</th><th>任务名称</th>"
             "<th>创建时间</th><th>当前输入版本</th><th>最新求解状态</th></tr></thead>"
             "<tbody>%s</tbody></table>" % "".join(trs)) if trs else \
            "<p class=\"muted\">还没有任务，点击“新建任务”开始。</p>"
    body = """
<section>
  <div class="row-between"><h2>任务列表</h2>
  <a class="btn primary" href="/jobs/new">新建任务</a></div>
  %s
</section>""" % table
    return layout("任务列表", body)


# ---------- 输入表单（新建 / 修改） ----------

def _item_row(w="", h="", q="", rot="0"):
    sel0 = ' selected' if str(rot) == "0" else ""
    sel1 = ' selected' if str(rot) == "1" else ""
    return ("""<tr>
<td><input type="number" name="item_width" min="1" step="1" required value="%s"></td>
<td><input type="number" name="item_height" min="1" step="1" required value="%s"></td>
<td><input type="number" name="item_qty" min="1" step="1" required value="%s"></td>
<td><select name="item_rot">
<option value="0"%s>不可旋转</option>
<option value="1"%s>可旋转</option>
</select></td>
<td><button type="button" class="btn small" onclick="removeRow(this)">删除</button></td>
</tr>""" % (esc(w), esc(h), esc(q), sel0, sel1))


def form_page(action, values, errors, job=None):
    err_html = ""
    if errors:
        err_html = ('<div class="flash err"><b>输入非法，未保存任何数据：</b><ul>%s</ul></div>'
                    % "".join("<li>%s</li>" % esc(e) for e in errors))
    items = values.get("items") or []
    rows = "".join(_item_row(it.get("width", ""), it.get("height", ""),
                             it.get("quantity", ""), it.get("rotatable", "0"))
                   for it in items) or _item_row()
    heading = ("修改输入 · 任务 #%d（当前版本 v%d）"
               % (job["id"], values.get("version_no", 0))) if job else "新建裁切任务"
    note = ""
    if job:
        note = ('<p class="muted">注意：修改任一裁切输入将生成新的输入版本，'
                '旧版本上的方案会立即失效；仅修改任务名称则不影响既有方案。</p>')
    body = """
<section>
<h2>%s</h2>
%s
%s
<form method="post" action="%s" class="form">
  <fieldset>
    <legend>任务</legend>
    <label>任务名称（可选）<input type="text" name="name" maxlength="80" value="%s"></label>
  </fieldset>
  <fieldset>
    <legend>母纸与全局参数（单位：mm）</legend>
    <div class="grid">
      <label>母纸宽度 *<input type="number" name="sheet_w" min="1" step="1" required value="%s"></label>
      <label>母纸高度 *<input type="number" name="sheet_h" min="1" step="1" required value="%s"></label>
      <label>刀缝宽度（≥0）*<input type="number" name="kerf" min="0" step="1" required value="%s"></label>
      <label>张数上限 *<input type="number" name="max_sheets" min="1" step="1" required value="%s"></label>
      <label>搜索状态数上限 *<input type="number" name="search_budget" min="1" step="1" required value="%s"></label>
    </div>
  </fieldset>
  <fieldset>
    <legend>成品明细（尺寸 mm，份数为正整数）</legend>
    <table class="tbl" id="items-table">
      <thead><tr><th>宽度</th><th>高度</th><th>份数</th><th>能否旋转</th><th></th></tr></thead>
      <tbody id="items-body">%s</tbody>
    </table>
    <button type="button" class="btn" onclick="addRow()">＋ 添加成品</button>
  </fieldset>
  <div class="actions"><button type="submit" class="btn primary">保存并求解</button>
  <a class="btn" href="/">取消</a></div>
</form>
</section>
<template id="row-tpl">%s</template>
<script>
function addRow(){
  var t=document.getElementById('row-tpl');
  document.getElementById('items-body').appendChild(t.content.cloneNode(true));
}
function removeRow(btn){
  var body=document.getElementById('items-body');
  if(body.rows.length>1){btn.closest('tr').remove();}
  else{btn.closest('tr').querySelectorAll('input').forEach(function(i){i.value='';});}
}
</script>""" % (
        esc(heading), note, err_html, esc(action),
        esc(values.get("name", "")),
        esc(values.get("sheet_w", "")), esc(values.get("sheet_h", "")),
        esc(values.get("kerf", "")), esc(values.get("max_sheets", "")),
        esc(values.get("search_budget", "")), rows, _item_row())
    return layout(heading, body)


# ---------- 任务详情 ----------

def _params_table(version):
    return """<table class="tbl kv">
<tr><th>输入版本</th><td>v%d</td></tr>
<tr><th>母纸尺寸</th><td>%d × %d mm</td></tr>
<tr><th>刀缝宽度</th><td>%d mm</td></tr>
<tr><th>张数上限</th><td>%d 张</td></tr>
<tr><th>搜索状态数上限</th><td>%d</td></tr>
<tr><th>版本保存时间</th><td>%s</td></tr>
</table>""" % (version["version_no"], version["sheet_w"], version["sheet_h"],
               version["kerf"], version["max_sheets"], version["search_budget"],
               esc(version["created_at"]))


def _items_table(items, counts=None):
    head = "<tr><th></th><th>类型</th><th>尺寸 (mm)</th><th>能否旋转</th><th>需求份数</th>"
    if counts is not None:
        head += "<th>实际成品数</th><th>是否满足</th>"
    head += "</tr>"
    trs = []
    for i, it in enumerate(items):
        chip = '<span class="chip" style="background:%s"></span>' % type_color(i)
        rot = "可旋转" if it["rotatable"] else "不可旋转"
        row = "<tr><td>%s</td><td>成品%d</td><td>%d × %d</td><td>%s</td><td>%d</td>" % (
            chip, i + 1, it["width"], it["height"], rot, it["quantity"])
        if counts is not None:
            ok = counts[i] >= it["quantity"]
            row += "<td>%d</td><td>%s</td>" % (
                counts[i], '<span class="ok">满足</span>' if ok else '<span class="bad">不足</span>')
        trs.append(row + "</tr>")
    return '<table class="tbl"><thead>%s</thead><tbody>%s</tbody></table>' % (head, "".join(trs))


def describe_cut(cut):
    x, y, w, h = cut["rect"]
    if cut["dir"] == "V":
        return ("对余料（左下角 (%d, %d)，宽 %d mm，高 %d mm）沿<b>垂直</b>方向、"
                "距其左边缘 <b>%d mm</b> 处贯通切割（刀缝 %d mm）"
                % (x, y, w, h, cut["offset"], cut["kerf"]))
    return ("对余料（左下角 (%d, %d)，宽 %d mm，高 %d mm）沿<b>水平</b>方向、"
            "距其下边缘 <b>%d mm</b> 处贯通切割（刀缝 %d mm）"
            % (x, y, w, h, cut["offset"], cut["kerf"]))


def sheets_view(version, result):
    """每张纸：SVG 排样图 + 按执行顺序排列的贯通裁切步骤。"""
    blocks = []
    n = len(result["sheets"])
    for idx, sh in enumerate(result["sheets"], 1):
        svg = render_sheet_svg(version["sheet_w"], version["sheet_h"], sh)
        used = sum(p["w"] * p["h"] for p in sh["placements"])
        util = used * 100.0 / (version["sheet_w"] * version["sheet_h"])
        steps = "".join("<li>%s</li>" % describe_cut(c)
                        for c in sh["cuts"]) or "<li>无需切割（整张即成品或空张）</li>"
        blocks.append("""
<div class="sheet-block">
  <h3>第 %d / %d 张 <span class="muted">（%d × %d mm，利用率 %.1f%%，成品 %d 件）</span></h3>
  <div class="sheet-cols">
    <div class="sheet-svg-wrap">%s</div>
    <div class="cut-steps"><h4>裁切步骤（按执行顺序，每刀贯穿当前余料）</h4>
      <ol>%s</ol>
      <p class="muted">图例：彩色=成品，浅灰虚线=余料/废料，深灰=刀缝损耗；悬停成品可查看尺寸。</p>
    </div>
  </div>
</div>""" % (idx, n, version["sheet_w"], version["sheet_h"], util,
            len(sh["placements"]), svg, steps))
    return "".join(blocks)


def detail_page(job, version, items, solution, result, history, flash=None):
    sol_html = ""
    if solution is None:
        sol_html = '<div class="flash warn">该版本尚未求解。</div>'
    elif solution["status"] == "solved":
        sol_html = """
<div class="flash ok">%s：共用 %d 张母纸，探索 %d 个状态，耗时 %d ms。
<a class="btn primary" href="/jobs/%d/solutions/%d/export">导出裁切单</a></div>
<h3>成品产出</h3>%s
<h3>逐张排样与裁切步骤</h3>%s""" % (
            status_label("solved"), solution["sheets_used"],
            solution["states_explored"], solution["elapsed_ms"],
            job["id"], solution["id"],
            _items_table(items, result["counts"]),
            sheets_view(version, result))
    elif solution["status"] == "infeasible":
        reason = ("<p>原因：%s</p>" % esc(solution["reason"])) if solution["reason"] else ""
        sol_html = """
<div class="flash err"><b>搜索已穷尽：无解。</b>共探索 %d 个状态（耗时 %d ms），
在张数上限等约束下不存在可行的贯通式裁切方案。%s
可修改输入（如提高张数上限、调整成品尺寸或允许旋转）后重试。</div>""" % (
            solution["states_explored"], solution["elapsed_ms"], reason)
    else:
        sol_html = """
<div class="flash warn"><b>搜索预算耗尽，不能确定是否有解。</b>
已探索 %d 个状态（达到上限 %d 或时间预算，耗时 %d ms），搜索被迫中止——
这<b>不代表无解</b>。可提高“搜索状态数上限”后重试。
<a class="btn primary" href="/jobs/%d/edit">调整预算并重试</a></div>""" % (
            solution["states_explored"], version["search_budget"],
            solution["elapsed_ms"], job["id"])

    hist_rows = []
    for h in history:
        valid = h["version_id"] == version["id"]
        hist_rows.append(
            "<tr><td>#%d</td><td>v%d</td><td class=\"st-%s\">%s</td><td>%s</td>"
            "<td>%d</td><td>%d ms</td><td>%s</td><td>%s</td><td>%s</td></tr>"
            % (h["id"], h["version_no"], h["status"], esc(status_label(h["status"])),
               esc(h["created_at"]), h["states_explored"], h["elapsed_ms"],
               '<span class="ok">有效</span>' if valid else '<span class="bad">已失效</span>',
               ("%d 张" % h["sheets_used"]) if h["sheets_used"] is not None else "—",
               ('<a href="/jobs/%d/solutions/%d/export">导出裁切单</a>'
                % (job["id"], h["id"])) if h["status"] == "solved" else "—"))
    hist_html = ("<table class=\"tbl\"><thead><tr><th>方案ID</th><th>输入版本</th>"
                 "<th>状态</th><th>求解时间</th><th>探索状态数</th><th>耗时</th>"
                 "<th>有效性</th><th>用张数</th><th>操作</th></tr></thead>"
                 "<tbody>%s</tbody></table>" % "".join(hist_rows)) if hist_rows else \
                "<p class=\"muted\">暂无求解记录。</p>"

    body = """
<section>
  <div class="row-between">
    <h2>任务 #%d · %s</h2>
    <div><a class="btn" href="/jobs/%d/edit">修改输入</a>
    <a class="btn" href="/">返回列表</a></div>
  </div>
  <p class="muted">创建于 %s ｜ 当前输入版本：<b>v%d</b></p>
  <div class="cols">
    <div><h3>当前输入参数</h3>%s</div>
    <div><h3>成品需求</h3>%s</div>
  </div>
  <h3>求解结果（基于输入版本 v%d）</h3>
  %s
  <h3>历史方案</h3>
  %s
</section>""" % (job["id"], esc(job["name"]), job["id"], esc(job["created_at"]),
                version["version_no"], _params_table(version), _items_table(items),
                version["version_no"], sol_html, hist_html)
    return layout("任务 #%d" % job["id"], body, flash=flash)


# ---------- 裁切单导出 / 拒绝 ----------

def export_page(job, version, items, solution, result, now):
    sheets_html = sheets_view(version, result)
    body = """
<div class="export-head">
  <h2>裁切单</h2>
  <table class="tbl kv">
    <tr><th>任务</th><td>#%d · %s</td></tr>
    <tr><th>输入版本</th><td><b>v%d</b>（输入一旦修改，本单即失效）</td></tr>
    <tr><th>母纸尺寸</th><td>%d × %d mm</td></tr>
    <tr><th>刀缝宽度</th><td>%d mm</td></tr>
    <tr><th>张数上限 / 实际用张数</th><td>%d / %d 张</td></tr>
    <tr><th>搜索状态数上限 / 实际探索</th><td>%d / %d</td></tr>
    <tr><th>导出时间</th><td>%s</td></tr>
  </table>
  <div class="no-print"><button class="btn primary" onclick="window.print()">打印 / 另存为 PDF</button>
  <a class="btn" href="/jobs/%d">返回任务</a></div>
</div>
<h3>成品产出</h3>
%s
<h3>逐张裁切指示</h3>
%s
<footer class="muted">本裁切单对应输入版本 v%d；输入版本一旦变更，本裁切单自动失效，不得再用于生产。</footer>
""" % (job["id"], esc(job["name"]), version["version_no"],
       version["sheet_w"], version["sheet_h"], version["kerf"],
       version["max_sheets"], solution["sheets_used"],
       version["search_budget"], solution["states_explored"], esc(now),
       job["id"], _items_table(items, result["counts"]), sheets_html,
       version["version_no"])
    return layout("裁切单 v%d" % version["version_no"], body)


def refused_page(job, sol, sol_version, cur_version, reason):
    body = """
<section>
  <div class="flash err"><b>导出被拒绝。</b>%s</div>
  <table class="tbl kv">
    <tr><th>方案 ID</th><td>#%d</td></tr>
    <tr><th>方案基于的输入版本</th><td>v%d</td></tr>
    <tr><th>任务当前输入版本</th><td>v%d</td></tr>
  </table>
  <p><a class="btn primary" href="/jobs/%d">返回任务（查看当前版本的方案）</a></p>
</section>""" % (esc(reason), sol["id"], sol_version["version_no"],
                 cur_version["version_no"], job["id"])
    return layout("导出被拒绝", body)


def message_page(title, msg):
    return layout(title, '<section><div class="flash err">%s</div>'
                         '<p><a class="btn" href="/">返回任务列表</a></p></section>'
                         % esc(msg))
