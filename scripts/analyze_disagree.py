#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用已交付的 MOSS 版 v3 文档（独立真值，含绝对时间戳角色）评测 CAM++ vs WeSpeaker。"""
import json, re, sys
import docx

BASE = 600.0  # 切片相对偏移
CAM = r"I:/青年说街头采访/清华26-0730/_work/v3/_bench/bench_transcript.json"
WES = r"I:/青年说街头采访/清华26-0730/_work/v3/_bench/bench_wespeaker.json"
DOCX = r"I:/青年说街头采访/清华26-0730/_work/v3/26-0730 北大药学博.docx"

def parse_docx_turns(path):
    d = docx.Document(path)
    role_re = re.compile(r"^\s*(采访者|受访者)（(\d{1,2}:\d{2})）\s*$")
    turns = []
    cur = None
    for p in d.paragraphs:
        t = p.text
        m = role_re.match(t)
        if m:
            if cur is not None:
                turns.append(cur)
            mm, ss = m.group(2).split(":")
            cur = {"start": int(mm) * 60 + int(ss), "role": m.group(1), "text": ""}
        elif cur is not None:
            if cur["text"]:
                cur["text"] += "\n"
            cur["text"] += t
    if cur is not None:
        turns.append(cur)
    turns.sort(key=lambda x: x["start"])
    for i, tn in enumerate(turns):
        tn["end"] = turns[i + 1]["start"] if i + 1 < len(turns) else tn["start"] + 30
    return turns

def gt_role(turns, t):
    for tn in turns:
        if tn["start"] <= t < tn["end"]:
            return tn["role"]
    # 最近
    best = min(turns, key=lambda x: abs(x["start"] - t))
    return best["role"]

cam = json.load(open(CAM, encoding="utf-8"))["segments"]
wes = json.load(open(WES, encoding="utf-8"))["segments"]
turns = parse_docx_turns(DOCX)

n = min(len(cam), len(wes))
cam_ok = wes_ok = 0
disagree = []
for i in range(n):
    abs_t = BASE + float(cam[i]["start"])
    g = gt_role(turns, abs_t)
    c = cam[i]["speaker"]
    w = wes[i]["speaker"]
    # 映射 SPEAKER_XX -> 角色 需要全局：先用多数投票建 cam->role, wes->role
    # 但为逐句直接比，先做全局映射
    pass

# 全局映射（多数投票）
def build_map(segs, turns, base):
    groups = {}
    for i, s in enumerate(segs):
        g = gt_role(turns, base + float(s["start"]))
        groups.setdefault(s["speaker"], {})
        groups[s["speaker"]][g] = groups[s["speaker"]].get(g, 0) + 1
    return {k: max(v, key=v.get) for k, v in groups.items()}

cam_map = build_map(cam, turns, BASE)
wes_map = build_map(wes, turns, BASE)
print("CAM++ 标签->角色映射:", cam_map)
print("WeSpeaker 标签->角色映射:", wes_map)

cam_ok = wes_ok = agree = 0
disagree = []
for i in range(n):
    g = gt_role(turns, BASE + float(cam[i]["start"]))
    c = cam_map.get(cam[i]["speaker"]) == g
    w = wes_map.get(wes[i]["speaker"]) == g
    cam_ok += c
    wes_ok += w
    if cam[i]["speaker"] != wes[i]["speaker"]:
        agree += 1
        disagree.append((i, BASE + float(cam[i]["start"]), cam[i]["speaker"], wes[i]["speaker"], g, cam[i]["text"]))

print(f"\n=== 独立真值评测（MOSS 交付文档，{n} 句）===")
print(f"  CAM++ 准确率:   {cam_ok/n*100:.1f}%  ({cam_ok}/{n})")
print(f"  WeSpeaker 准确率: {wes_ok/n*100:.1f}%  ({wes_ok}/{n})")
print(f"  两方法标签不一致: {agree} 句 ({agree/n*100:.1f}%)")
print(f"\n=== 不一致句明细（CAM++ / WeSpeaker / 真值 / 文本）===")
for i, t, c, w, g, txt in disagree:
    mm = int(t)//60; ss = int(t)%60
    print(f"  [{mm:02d}:{ss:02d}] CAM={c} WES={w} GT={g} | {txt[:50]}")
