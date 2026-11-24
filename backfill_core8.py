#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性工具：回补核心8只（CORE8）近20个交易日的日内10分钟累计成交额曲线，
写入 data/intraday.json 的 hist8 字段，供前端「核心8只·日内成交对比」近20日均值基准使用。

用法:  python backfill_core8.py
"""
import datetime as dt
import json
import os
import sys
import time

import requests

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
IPATH = os.path.join(DATA_DIR, "intraday.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# 与 fetch_quotes.py CORE8 保持一致
CORE8 = [
    "1.510300", "1.510050", "1.510180", "1.510500",
    "1.512100", "1.588000", "0.159915", "1.515800",
]

TIMEOUT = 20

# 5 分钟 bar 结束时刻（与 fetch_quotes.py 一致）
_AM5 = ["09:35", "09:40", "09:45", "09:50", "09:55", "10:00", "10:05", "10:10",
        "10:15", "10:20", "10:25", "10:30", "10:35", "10:40", "10:45", "10:50",
        "10:55", "11:00", "11:05", "11:10", "11:15", "11:20", "11:25", "11:30"]
_PM5 = ["13:05", "13:10", "13:15", "13:20", "13:25", "13:30", "13:35", "13:40",
        "13:45", "13:50", "13:55", "14:00", "14:05", "14:10", "14:15", "14:20",
        "14:25", "14:30", "14:35", "14:40", "14:45", "14:50", "14:55", "15:00"]
_TIME_SET = set(_AM5) | set(_PM5)


def make_session():
    s = requests.Session()
    s.trust_env = False
    s.headers.update({"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"})
    return s


def fetch_5min_multi_day(sess, secid, days=22):
    """拉近 days 个交易日的 5 分钟K线 -> {date: {HH:MM: 成交额(元)}}"""
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    data = None
    for i in range(3):
        try:
            r = sess.get(url, params={
                "secid": secid, "klt": "5", "fqt": "1", "end": "20500101",
                "lmt": str(days * 48),
                "fields1": "f1,f2,f3", "fields2": "f51,f52,f53,f54,f55,f56,f57",
            }, timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
            break
        except Exception as e:
            if i == 2:
                print(f"  [warn] {secid} 拉取失败: {e}")
                return {}
            time.sleep(1 + i)
    kl = (data or {}).get("data", {}).get("klines") or []
    out = {}
    for line in kl:
        p = line.split(",")
        if len(p) < 7:
            continue
        parts = p[0].split(" ")
        if len(parts) != 2:
            continue
        d, t = parts[0], parts[1][:5]
        if t not in _TIME_SET:
            continue
        try:
            amt = float(p[6])
        except ValueError:
            continue
        out.setdefault(d, {})[t] = out.setdefault(d, {}).get(t, 0.0) + amt
    return out


def agg_10min_cum(day_map):
    """{HH:MM: 5min成交额} -> [{t, v(亿)}] 10分钟累计曲线（上午/下午分开累计）"""
    pts, cum = [], 0.0
    for t in _AM5:
        cum += day_map.get(t, 0.0)
        if t in _TIME_SET and t in day_map:
            pts.append({"t": t, "v": round(cum / 1e8, 2)})
    cum = 0.0
    for t in _PM5:
        cum += day_map.get(t, 0.0)
        if t in _TIME_SET and t in day_map:
            pts.append({"t": t, "v": round(cum / 1e8, 2)})
    return pts


def main():
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d")
    sess = make_session()

    # {date: {HH:MM: 合计成交额}} 8只逐只累加
    merged = {}
    for secid in CORE8:
        print(f"[backfill] 拉取 {secid} 近22日5分钟线 ...")
        per = fetch_5min_multi_day(sess, secid)
        for d, m in per.items():
            if d >= today:      # 跳过今天（未收盘，收盘后由 Actions 正式写入）
                continue
            slot = merged.setdefault(d, {})
            for t, v in m.items():
                slot[t] = slot.get(t, 0.0) + v
        time.sleep(0.3)

    hist8 = {}
    for d in sorted(merged):
        pts = agg_10min_cum(merged[d])
        if len(pts) >= 20:      # 完整交易日（≥20个10分钟点）才收录
            hist8[d] = pts
    dates = sorted(hist8)
    hist8 = {d: hist8[d] for d in dates[-20:]}   # 滚动保留最近20日
    print(f"[backfill] 聚合完成：{len(hist8)} 个交易日（{dates[0] if dates else '-'} ~ {dates[-1] if dates else '-'}）")
    if not hist8:
        print("[backfill] 无有效数据，退出")
        sys.exit(1)

    data = {"ok": True, "date": today, "points": [], "points8": [], "hist": {}, "hist8": {}, "total_yi": 0.0, "total8_yi": 0.0}
    if os.path.exists(IPATH):
        try:
            with open(IPATH, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass

    # 合并：回补数据以最新抓取为准（8只完整合计），直接覆盖同日期
    old8 = dict(data.get("hist8") or {})
    for d, pts in hist8.items():
        old8[d] = pts
    dates = sorted(old8)
    data["hist8"] = {d: old8[d] for d in dates[-20:]}

    tmp = IPATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, IPATH)
    print(f"[backfill] hist8 已写入 {IPATH}（{len(data['hist8'])} 天）")


if __name__ == "__main__":
    main()
