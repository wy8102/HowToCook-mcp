#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 all_recipes.json 的配图字段"""
import json
import sys
import urllib.request

path = sys.argv[1] if len(sys.argv) > 1 else "all_recipes.json"
d = json.load(open(path, encoding="utf-8"))
wi = [r for r in d if r.get("image_path")]
print(f"总条数 {len(d)} | 有图 {len(wi)} | 无图 {len(d)-len(wi)}")

multi = sum(1 for r in d if len(r.get("images") or []) > 1)
print(f"多图菜谱: {multi} 条")

for r in wi[:4]:
    imgs = r.get("images") or []
    print(f"\n  {r['name']}  (分类 {r['category']}, {len(imgs)} 张)")
    for u in imgs[:2]:
        print(f"    {u[:120]}")

# 实测取图
if wi:
    print("\n实测 HTTP 取图:")
    for r in wi[:3]:
        u = r["image_path"]
        try:
            req = urllib.request.Request(u, method="HEAD")
            with urllib.request.urlopen(req, timeout=20) as resp:
                ct = resp.headers.get("content-type")
                cl = resp.headers.get("content-length")
                print(f"  {resp.status} {ct} {cl}B  <- {r['name']}")
        except Exception as e:
            print(f"  FAIL {type(e).__name__}: {str(e)[:90]}  <- {r['name']}")
