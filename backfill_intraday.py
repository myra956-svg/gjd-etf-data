#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回补「跟踪池近20日 10分钟累计成交额」历史基准数据。

数据源：东方财富 push2his 5分钟K线(klt=5)，字段 f51(时间) / f57(成交额,元)。
对 21 只 ETF 逐只抓取最近 ~20 个交易日的 5 分钟 K 线，累加得到「跟踪池
每天每 10 分钟的合计累计成交额」，写入 data/intraday.json 的 hist 字段。

前端读取 hist 后，把过去 20 个交易日同一时点取平均，即得「近20日滚存
成交额基准曲线」，与今日实时曲线对比（放量/缩量）。

用法:
  python backfill_intraday.py            # 回补最近 20 个交易日(默认)
  python backfill_intraday.py --days 20  # 自定义天数
  python backfill_intraday.py --proxy    # 本地调试时走系统代理
"""
import argparse
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

# 与 fetch_quotes.py / gen_intraday_seed.py 保持一致
ETFS = [
    ("1.510300", "510300"), ("1.510330", "510330"), ("1.510310", "510310"), ("0.159919", "159919"),
    ("1.510050", "510050"), ("1.510180", "510180"),
    ("1.510500", "510500"), ("1.512500", "512500"), ("0.159922", "159922"),
    ("1.512100", "512100"), ("0.159845", "159845"), ("1.560010", "560010"), ("0.159629", "159629"),
    ("1.588000", "588000"), ("1.588080", "588080"), ("1.588050", "588050"),
    ("0.159915", "159915"), ("0.159977", "159977"), ("0.159952", "159952"),
    ("1.515800", "515800"), ("1.515850", "515850"),
]

# 10 分钟对齐的时间点（每段 10 分钟 bar 的结束时刻），与前端 minuteIndex 对齐
TIMES = ["09:40", "09:50", "10:00", "10:10", "10:20", "10:30", "10:40", "10:50",
         "11:00", "11:10", "11:20", "11:30",
         "13:10", "13:20", "13:30", "13:40", "13:50", "14:00", "14:10", "14:20",
         "14:30", "14:40", "14:50", "15:00"]
TIME_SET = set(TIMES)
AM_TIMES = [t for t in TIMES if t <= "11:30"]   # 上午段
PM_TIMES = [t for t in TIMES if t >= "13:10"]   # 下午段


def make_session(use_proxy):
    s = requests.Session()
    s.trust_env = use_proxy  # 本地调试走系统代理；云端直连
    s.headers.update({"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"})
    return s


def fetch_5min(sess, secid, lmt=1200):
    """抓取单只 ETF 最近 lmt 条 5 分钟 K 线。返回 list["YYYY-MM-DD HH:MM,..."]"""
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid, "klt": "5", "fqt": "1", "end": "20500101", "lmt": str(lmt),
        "fields1": "f1,f2,f3",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
    }
    for attempt in range(3):
        try:
            r = sess.get(url, params=params, timeout=25)
            r.raise_for_status()
            data = r.json()
            kl = ((data or {}).get("data") or {}).get("klines") or []
            if kl:
                return kl
        except Exception as e:
            if attempt == 2:
                print(f"  [warn] {secid} 抓取失败: {e}", file=sys.stderr)
            time.sleep(1 + attempt)
    return []


def parse_5min(klines):
    """解析 5 分钟 K 线 -> {date: {"HH:MM": 成交额(元)}}"""
    out = {}
    for line in klines:
        p = line.split(",")
        if len(p) < 7:
            continue
        dt_part = p[0].split(" ")
        if len(dt_part) != 2:
            continue
        date, t = dt_part[0], dt_part[1][:5]
        try:
            amt = float(p[6])
        except ValueError:
            continue
        out.setdefault(date, {})[t] = out.get(date, {}).get(t, 0.0) + amt
    return out


def to_10min_cum(day_map):
    """把某天的 5 分钟成交额聚合为 10 分钟累计成交额曲线。
    上午/下午分开累计（午休不跨段）。返回 [{"t": "09:40", "v": 亿元}, ...]"""
    pts = []
    cum = 0.0
    # 上午：5min 时间 09:35..11:30，10min 点 09:40..11:30
    am_seq = ["09:35", "09:40", "09:45", "09:50", "09:55", "10:00", "10:05",
              "10:10", "10:15", "10:20", "10:25", "10:30", "10:35", "10:40",
              "10:45", "10:50", "10:55", "11:00", "11:05", "11:10", "11:15",
              "11:20", "11:25", "11:30"]
    for t in am_seq:
        cum += day_map.get(t, 0.0)
        if t in TIME_SET:
            pts.append({"t": t, "v": round(cum / 1e8, 2)})
    cum = 0.0
    pm_seq = ["13:05", "13:10", "13:15", "13:20", "13:25", "13:30", "13:35",
              "13:40", "13:45", "13:50", "13:55", "14:00", "14:05", "14:10",
              "14:15", "14:20", "14:25", "14:30", "14:35", "14:40", "14:45",
              "14:50", "14:55", "15:00"]
    for t in pm_seq:
        cum += day_map.get(t, 0.0)
        if t in TIME_SET:
            pts.append({"t": t, "v": round(cum / 1e8, 2)})
    return pts


def run(days=20, use_proxy=False):
    sess = make_session(use_proxy)
    # 每只 ETF 抓最近 (days+1)*48 条 5 分钟 K 线（预留今天半日）
    lmt = (days + 2) * 48
    per_day = {}  # date -> {t: 合计成交额(元)}
    for secid, code in ETFS:
        kl = fetch_5min(sess, secid, lmt=lmt)
        parsed = parse_5min(kl)
        for date, m in parsed.items():
            d = per_day.setdefault(date, {})
            for t, v in m.items():
                d[t] = d.get(t, 0.0) + v
        print(f"  {code}: {len(kl)} 条 5min K线, 覆盖 {len(parsed)} 天")
        time.sleep(0.2)

    # 全部交易日按日期排序，取最近 days 个完整交易日（剔除今天，今天未收盘）
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).strftime("%Y-%m-%d")
    all_dates = sorted(d for d in per_day if d != today)
    dates = all_dates[-days:]
    hist = {}
    for d in dates:
        pts = to_10min_cum(per_day[d])
        # 只保留有数据的完整日（>=20 个点）
        if len(pts) >= 20:
            hist[d] = pts
    print(f"历史基准: {len(hist)} 个交易日 -> {list(hist)[0] if hist else '-'} ~ {list(hist)[-1] if hist else '-'}")

    # 合并写入 intraday.json，保留今日 points
    data = {"ok": True, "date": today, "points": [], "hist": {}, "total_yi": 0.0}
    if os.path.exists(IPATH):
        try:
            with open(IPATH, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass
    data["hist"] = hist
    data["hist_days"] = len(hist)
    tmp = IPATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, IPATH)
    print(f"已写入 {IPATH}: hist={len(hist)}天, points={len(data.get('points') or [])}点")
    return hist


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=20)
    ap.add_argument("--proxy", action="store_true")
    args = ap.parse_args()
    run(args.days, args.proxy)
