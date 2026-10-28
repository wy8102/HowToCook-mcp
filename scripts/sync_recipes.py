#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 HowToCook 的 Markdown 抽取 all_recipes.json

数据来源（可并存，按顺序合并，后面的同 id 覆盖前面的）：
  --data  <dir>  上游 fork 的 clone（dishes/**/*.md），可重复指定
  --local <dir>  自有菜谱目录（同样按 dishes/<分类>/<菜名>.md 放），可重复指定

设计要点：
  1. md 格式在 374 个样本里零变体，四个二级标题恒定：
     必备原料和工具 / 计算 / 操作 / 附加内容 —— 解析可以写得很确定。
  2. 上游原版 JSON 的 quantity 全是 null（份量只塞在 text_quantity 字符串里），
     这里真正解析出 quantity/unit，「计算」段的精确份量优先于「必备原料」段的粗略清单。
  3. 输出字段严格对齐 src/types/index.ts 的 Recipe 接口，多出的 images 字段保留（TS 侧忽略即可）。

用法：
  python3 scripts/sync_recipes.py --data /home/wy/howtocook-data \
                                  --local /home/wy/howtocook-local \
                                  --out all_recipes.json
"""
import argparse
import json
import os
import re
import sys

# 目录名 → 中文分类（沿用上游 JSON 的既有取值：甜品、半成品加工）
CATEGORY_MAP = {
    "meat_dish": "荤菜",
    "vegetable_dish": "素菜",
    "staple": "主食",
    "aquatic": "水产",
    "breakfast": "早餐",
    "soup": "汤",
    "drink": "饮品",
    "dessert": "甜品",
    "semi-finished": "半成品加工",
    "condiment": "调料",
}

SECTION_ING = "必备原料和工具"
SECTION_CAL = "计算"
SECTION_OPS = "操作"
SECTION_EXT = "附加内容"

# 份量：抓「数字 [~数字] 单位」，中文单位常见于菜谱
QTY_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:[～~\-—]\s*(\d+(?:\.\d+)?))?\s*"
    r"([a-zA-Z]+|克|千克|公斤|毫升|升|斤|两|片|个|只|根|瓣|勺|撮|颗|袋|包|块|张|杯|碗|把|头|条|节|段|朵|粒|颗|毫升|g|ml|kg|L)?"
)


def split_sections(text):
    """按二级标题切段，返回 {标题: 正文}"""
    parts = re.split(r"^##\s+(.+?)\s*$", text, flags=re.M)
    out = {}
    # parts[0] 是首个二级标题之前的内容
    for i in range(1, len(parts) - 1, 2):
        out[parts[i].strip()] = parts[i + 1].strip()
    return parts[0].strip() if parts else "", out


def parse_difficulty(head):
    m = re.search(r"预估烹饪难度[：:]\s*(★+)", head)
    return len(m.group(1)) if m else 0


def bullet_lines(block):
    """抽出 '- xxx' / '* xxx' 列表项（含它们后面的续行）"""
    items, cur = [], None
    for raw in block.splitlines():
        line = raw.rstrip()
        m = re.match(r"^\s*[-*]\s+(.*)$", line)
        if m:
            if cur is not None:
                items.append(cur.strip())
            cur = m.group(1)
        elif not line.strip():
            if cur is not None:
                items.append(cur.strip())
                cur = None
        elif cur is not None:
            cur += " " + line.strip()
    if cur is not None:
        items.append(cur.strip())
    return items


def numbered_steps(block):
    """抽出 '1. xxx' 步骤；嵌套的子项（  * xxx）以换行形式并入上一步"""
    steps, cur = [], None
    for raw in block.splitlines():
        line = raw.rstrip()
        m = re.match(r"^\s*\d+[.、)]\s+(.*)$", line)
        sub = re.match(r"^\s{2,}[-*]\s+(.*)$", line)
        if m:
            if cur is not None:
                steps.append(cur.strip())
            cur = m.group(1)
        elif sub and cur is not None:
            cur += "\n  * " + sub.group(1)
        elif not line.strip():
            continue
        elif cur is not None:
            cur += " " + line.strip()
    if cur is not None:
        steps.append(cur.strip())
    return steps


def parse_qty(text):
    """从一条份量文本里解析 (quantity, unit)；解析不出返回 (None, None)"""
    m = QTY_RE.search(text)
    if not m:
        return None, None
    q = m.group(1)
    try:
        qty = float(q)
        if qty == int(qty):
            qty = int(qty)
    except ValueError:
        qty = None
    unit = (m.group(3) or "").strip() or None
    # 解析出 0 的多半是「0.5 斤」这类被截断或原文「适量」，0 克没有意义 → 归为未知
    if qty == 0:
        qty = None
    return qty, unit


def core_name(s):
    """去掉份量、括号注释后的原料名，用于两段之间配对"""
    s = re.sub(r"[（(].*?[）)]", "", s)
    s = QTY_RE.sub("", s)
    return re.sub(r"[\s\-*·]+", "", s)


def build_recipe(md_path, root, category_dir):
    text = open(md_path, encoding="utf-8").read()
    head, secs = split_sections(text)

    # H1 菜名
    m = re.match(r"^#\s+(.+)$", head.splitlines()[0]) if head.splitlines() else None
    title = m.group(1).strip() if m else os.path.splitext(os.path.basename(md_path))[0]

    # description = 首个二级标题之前的原文（简介 + 难度行），与上游做法一致
    rel = os.path.relpath(md_path, root).replace(os.sep, "/")
    rname = os.path.splitext(os.path.basename(md_path))[0]
    rid = re.sub(r"\.md$", "", rel).replace("/", "-")

    # 份量：以「计算」段为准
    cal_items = bullet_lines(secs.get(SECTION_CAL, ""))
    cal_map = {}
    for it in cal_items:
        qty, unit = parse_qty(it)
        key = core_name(it)
        if key:
            cal_map[key] = (qty, unit, it)

    ingredients = []
    seen = set()
    # 先「必备原料和工具」的条目，用「计算」段的份量补上
    for it in bullet_lines(secs.get(SECTION_ING, "")):
        key = core_name(it)
        if not key or key in seen:
            continue
        seen.add(key)
        qty = unit = None
        text_qty = it
        notes = "量未指定"
        for ck, (cq, cu, ctext) in cal_map.items():
            if ck and (ck in key or key in ck):
                qty, unit, text_qty, notes = cq, cu, ctext, ""
                break
        ingredients.append({
            "name": it,
            "quantity": qty,
            "unit": unit,
            "text_quantity": text_qty,
            "notes": notes,
        })
    # 「计算」段里有、原料段没列出的，补进去
    for ck, (cq, cu, ctext) in cal_map.items():
        if any(ck and (ck in s or s in ck) for s in seen):
            continue
        ingredients.append({
            "name": ctext, "quantity": cq, "unit": cu,
            "text_quantity": ctext, "notes": "",
        })

    steps = [{"step": i + 1, "description": s}
             for i, s in enumerate(numbered_steps(secs.get(SECTION_OPS, "")))]

    notes = bullet_lines(secs.get(SECTION_EXT, ""))
    if not notes:
        tail = secs.get(SECTION_EXT, "").strip()
        notes = [tail] if tail else []

    cat = CATEGORY_MAP.get(category_dir, category_dir)

    return {
        "id": rid,
        "name": title,
        "description": head,
        "source_path": rel,
        "image_path": None,
        "images": [],
        "category": cat,
        "difficulty": parse_difficulty(head),
        "tags": [cat],
        "servings": 1,
        "ingredients": ingredients,
        "steps": steps,
        "prep_time_minutes": None,
        "cook_time_minutes": None,
        "total_time_minutes": None,
        "additional_notes": notes,
    }


def harvest(root, label, recipes, stats):
    dishes = os.path.join(root, "dishes")
    if not os.path.isdir(dishes):
        print(f"  ⚠ {label}: 没有 dishes/ 目录，跳过 ({root})")
        return
    n = 0
    for cat_dir in sorted(os.listdir(dishes)):
        cp = os.path.join(dishes, cat_dir)
        if not os.path.isdir(cp):
            continue
        # template 是菜谱模板示例，不是真菜谱，排除
        if cat_dir == "template":
            continue
        for dirpath, _, files in os.walk(cp):
            for fn in sorted(files):
                if not fn.endswith(".md"):
                    continue
                fp = os.path.join(dirpath, fn)
                try:
                    r = build_recipe(fp, root, cat_dir)
                except Exception as e:
                    stats["failed"].append(f"{label}:{fp}: {e}")
                    continue
                if not r["steps"] and not r["ingredients"]:
                    stats["empty"].append(f"{label}:{fp}")
                    continue
                recipes[r["id"]] = r      # 同 id 后者覆盖前者（local 优先）
                n += 1
                stats["by_cat"][r["category"]] = stats["by_cat"].get(r["category"], 0) + 1
    print(f"  {label}: {n} 道  ({root})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", action="append", default=[], help="上游 md 目录（含 dishes/）")
    ap.add_argument("--local", action="append", default=[], help="自有菜谱目录（含 dishes/）")
    ap.add_argument("--out", default="all_recipes.json")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    recipes, stats = {}, {"failed": [], "empty": [], "by_cat": {}}

    # 先上游，后自有 —— 自有的同 id 会覆盖上游
    for d in a.data:
        harvest(d, "上游", recipes, stats)
    for d in a.local:
        harvest(d, "自有", recipes, stats)

    out = sorted(recipes.values(), key=lambda r: r["id"])
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"\n✓ 写出 {a.out}: {len(out)} 道")
    print("  分类:", json.dumps(stats["by_cat"], ensure_ascii=False))
    withsteps = sum(1 for r in out if r["steps"])
    withqty = sum(1 for r in out if any(i["quantity"] is not None for i in r["ingredients"]))
    print(f"  有步骤: {withsteps}/{len(out)} | 有解析出份量的: {withqty}/{len(out)}")
    if stats["failed"]:
        print(f"  ✗ 解析失败 {len(stats['failed'])}:")
        for x in stats["failed"][:8]:
            print("    ", x)
    if stats["empty"]:
        print(f"  ⚠ 空内容跳过 {len(stats['empty'])}:")
        for x in stats["empty"][:8]:
            print("    ", x)
    return 0 if out else 1


if __name__ == "__main__":
    sys.exit(main())
