#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验步骤图分类效果"""
import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "all_recipes.json"
d = json.load(open(path, encoding="utf-8"))

ws = [r for r in d if r.get("has_step_images")]
print(f"总 {len(d)} 道 | 带步骤分解图 {len(ws)} 道\n")

for name in ("戚风蛋糕", "柱候牛腩", "水煮牛肉", "凉粉"):
    hits = [x for x in d if name in x["id"]]
    if not hits:
        print(f"[{name}] 无")
        continue
    r = hits[0]
    print(f"=== {r['name']} ===")
    print(f"  has_step_images: {r['has_step_images']}")
    print(f"  封面: {str(r.get('image_path'))[:80]}")
    print(f"  总图 {len(r.get('images') or [])} 张 | 步骤图 {len(r.get('step_images') or [])} 张")
    print(f"  菜谱步骤数: {len(r['steps'])}")
    for s in (r.get("step_images") or [])[:12]:
        print(f"    step={s['step']}  order={s.get('order')}  alt={s['alt']}")
    print()

# 顺序正确性：step 应非递减
bad = 0
for r in ws:
    seq = [s["step"] for s in r["step_images"] if s["step"] is not None]
    if seq != sorted(seq):
        bad += 1
print(f"顺序校验: {len(ws)} 道带步骤图，其中 step 号非递增的 = {bad} 道")
