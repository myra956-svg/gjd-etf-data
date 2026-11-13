#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
国家队宽基ETF - 盘中行情快照抓取脚本
在 GitHub Actions 服务器端抓取东财公开行情（无浏览器 CORS 限制），
输出 data/quotes.json，供前端经 raw.githubusercontent.com 跨域读取。

用法:
  python fetch_quotes.py            # 抓取当前行情快照
  python fetch_quotes.py --local    # 本地调试(不走云)
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
OUT_PATH = os.path.join(DATA_DIR, "quotes.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
TIMEOUT = 15

# (secid, code) —— 与前端 index.html 的 ETF_GROUPS 保持一致
ETFS = [
    ("1.510300", "510300"), ("1.510330", "510330"), ("1.510310", "510310"), ("0.159919", "159919"),
    ("1.510050", "510050"), ("1.510180", "510180"),
    ("1.510500", "510500"), ("1.512500", "512500"), ("0.159922", "159922"),
    ("1.512100", "512100"), ("0.159845", "159845"), ("1.560010", "560010"), ("0.159629", "159629"),
    ("1.588000", "588000"), ("1.588080", "588080"), ("1.588050", "588050"),
    ("0.159915", "159915"), ("0.159977", "159977"), ("0.159952", "159952"),
    ("1.515800", "515800"), ("1.515850", "515850"),
]
INDICES = [("1.000001", "上证指数"), ("0.399001", "深证成指"), ("0.399006", "创业板指"), ("1.000688", "科创50")]

QUOTE_FIELDS = "f2,f3,f4,f5,f6,f8,f10,f12,f13,f14,f15,f16,f17,f18"
IDX_FIELDS = "f2,f3,f4,f12,f14"


def make_session():
    s = requests.Session()
    s.trust_env = False
    s.headers.update({"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"})
    return s


def get_json(sess, url, params=None, retries=3):
    for i in range(retries):
        try:
            r = sess.get(url, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if i == retries - 1:
                raise
            time.sleep(1 + i)
    return None


def fetch_ulist(sess, secids, fields):
    """东财批量行情，带双 host 容错。返回 list[dict]"""
    hosts = ["push2.eastmoney.com", "push2delay.eastmoney.com"]
    last_err = None
    for host in hosts:
        try:
            url = f"https://{host}/api/qt/ulist.np/get"
            data = get_json(sess, url, {"fltt": "2", "invt": "2", "fields": fields, "secids": secids})
            diff = (data or {}).get("data", {}).get("diff")
            if diff:
                return diff if isinstance(diff, list) else list(diff.values())
        except Exception as e:
            last_err = e
    raise RuntimeError(f"东财批量行情失败: {last_err}")


def fetch_quotes_and_idx(sess):
    quotes = {}
    diff = fetch_ulist(sess, ",".join(s for s, _ in ETFS), QUOTE_FIELDS)
    for d in diff:
        f12, f13 = d.get("f12"), d.get("f13")
        if f12 is None or f13 is None:
            continue
        quotes[f"{f13}.{f12}"] = {k: d.get(k) for k in
                                  ("f2", "f3", "f4", "f5", "f6", "f8", "f10", "f12", "f13", "f14", "f15", "f16", "f17", "f18")}
    idx = {}
    diff2 = fetch_ulist(sess, ",".join(s for s, _ in INDICES), IDX_FIELDS)
    for d in diff2:
        f12, f13 = d.get("f12"), d.get("f13")
        if f12 is None or f13 is None:
            continue
        idx[f"{f13}.{f12}"] = {k: d.get(k) for k in ("f2", "f3", "f4", "f12", "f14")}
    return quotes, idx


def fetch_avg_one(sess, secid):
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    data = get_json(sess, url, {
        "secid": secid, "klt": "101", "fqt": "1", "end": "20500101", "lmt": "20",
        "fields1": "f1,f2,f3", "fields2": "f51,f52,f53,f54,f55,f56,f57",
    })
    kl = (data or {}).get("data", {}).get("klines") or []
    s, n = 0.0, 0
    for k in kl:
        p = k.split(",")
        if len(p) >= 7:
            try:
                s += float(p[6]); n += 1
            except ValueError:
                pass
    return round(s / n, 2) if n else 0.0


def fetch_flow_one(sess, secid):
    url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
    data = get_json(sess, url, {
        "secid": secid, "klt": "101", "lmt": "1",
        "fields1": "f1,f2,f3,f7", "fields2": "f51,f52,f53,f54,f55,f56",
    })
    kl = (data or {}).get("data", {}).get("klines") or []
    if not kl:
        return 0.0
    p = kl[-1].split(",")
    try:
        return round(float(p[1]), 2)
    except (ValueError, IndexError):
        return 0.0


def update_intraday(quotes):
    """累加当前时刻跟踪池 21 只的成交额(f6)，追加到 data/intraday.json 的今日曲线。
    每 10 分钟一个点，时间对齐到 10 分钟。"""
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))  # 北京时间
    date = now.strftime("%Y-%m-%d")
    mm = (now.minute // 10) * 10
    t = f"{now.hour:02d}:{mm:02d}"

    total = 0.0
    for secid, _ in ETFS:
        q = quotes.get(secid)
        if q and q.get("f6"):
            try:
                total += float(q["f6"])
            except (TypeError, ValueError):
                pass
    if total <= 0:
        return

    ipath = os.path.join(DATA_DIR, "intraday.json")
    data = {"ok": True, "date": date, "points": [], "hist": {}, "total_yi": 0.0}
    if os.path.exists(ipath):
        try:
            with open(ipath, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {"ok": True, "date": date, "points": [], "hist": {}, "total_yi": 0.0}
    if data.get("date") != date:
        data = {"ok": True, "date": date, "points": [], "hist": data.get("hist", {}), "total_yi": 0.0}

    pts = [p for p in (data.get("points") or []) if p.get("t") != t]
    pts.append({"t": t, "v": round(total / 1e8, 2)})
    pts.sort(key=lambda p: p["t"])
    data["points"] = pts
    data["total_yi"] = round(total / 1e8, 2)
    data["updated"] = now.strftime("%Y-%m-%d %H:%M")

    tmp = ipath + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, ipath)


def run():
    sess = make_session()
    quotes, idx = fetch_quotes_and_idx(sess)
    if not quotes:
        raise RuntimeError("行情为空")

    update_intraday(quotes)

    avg, flow = {}, {}
    for secid, code in ETFS:
        try:
            avg[code] = fetch_avg_one(sess, secid)
        except Exception:
            avg[code] = 0.0
        try:
            flow[code] = fetch_flow_one(sess, secid)
        except Exception:
            flow[code] = 0.0
        time.sleep(0.15)

    out = {
        "ok": True,
        "ts": int(time.time()),
        "date": (dt.datetime.utcnow() + dt.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M"),
        "quotes": quotes,
        "idx": idx,
        "avg": avg,
        "flow": flow,
    }
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = OUT_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, OUT_PATH)
    print(f"[quotes] ok quotes={len(quotes)} idx={len(idx)} avg={len(avg)} flow={len(flow)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", action="store_true")
    args = ap.parse_args()
    try:
        run()
    except Exception as e:
        print(f"[quotes] FAIL: {e}")
        sys.exit(1)
