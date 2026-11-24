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

# 核心8只（八大宽基各取龙头）—— 与前端 CORE8 保持一致；改这里即可换名单
CORE8 = [
    "1.510300",  # 沪深300
    "1.510050",  # 上证50
    "1.510180",  # 上证180
    "1.510500",  # 中证500
    "1.512100",  # 中证1000
    "1.588000",  # 科创50
    "0.159915",  # 创业板
    "1.515800",  # 中证800
]
INDICES = [("1.000001", "上证指数"), ("0.399001", "深证成指"), ("0.399006", "创业板指"), ("1.000688", "科创50")]

# 10 分钟对齐时间点（与前端 minuteIndex / intraday.hist 对齐）
TIMES_10M = ["09:40", "09:50", "10:00", "10:10", "10:20", "10:30", "10:40", "10:50",
             "11:00", "11:10", "11:20", "11:30",
             "13:10", "13:20", "13:30", "13:40", "13:50", "14:00", "14:10", "14:20",
             "14:30", "14:40", "14:50", "15:00"]
_TIME_SET = set(TIMES_10M)
# 5 分钟 K 线 bar 结束时刻序列（用于聚合到 10 分钟）
_AM5 = ["09:35", "09:40", "09:45", "09:50", "09:55", "10:00", "10:05", "10:10",
        "10:15", "10:20", "10:25", "10:30", "10:35", "10:40", "10:45", "10:50",
        "10:55", "11:00", "11:05", "11:10", "11:15", "11:20", "11:25", "11:30"]
_PM5 = ["13:05", "13:10", "13:15", "13:20", "13:25", "13:30", "13:35", "13:40",
        "13:45", "13:50", "13:55", "14:00", "14:05", "14:10", "14:15", "14:20",
        "14:25", "14:30", "14:35", "14:40", "14:45", "14:50", "14:55", "15:00"]

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
    try:
        diff2 = fetch_ulist(sess, ",".join(s for s, _ in INDICES), IDX_FIELDS)
        for d in diff2:
            f12, f13 = d.get("f12"), d.get("f13")
            if f12 is None or f13 is None:
                continue
            idx[f"{f13}.{f12}"] = {k: d.get(k) for k in ("f2", "f3", "f4", "f12", "f14")}
    except Exception as e:
        print(f"[quotes] warn: 东财指数获取失败({e})，尝试腾讯兜底")
    if len(idx) < len(INDICES):
        # 兑底：腾讯行情（东财对海外 IP 可能不给指数数据；ETF 正常）
        idx.update(fetch_idx_tencent(idx))
    return quotes, idx


def fetch_idx_tencent(existing):
    """腾讯 qt.gtimg.cn 兜底抓指数，返回与东财 idx 同构的 dict。
    INDICES 元素形如 ("1.000001", "上证指数")（secid, 名称）。
    腾讯 s_ 简化格式字段：[1]名称 [2]代码 [3]现价 [4]涨跌额 [5]涨跌幅"""
    out = {}
    try:
        q = ",".join(f"s_{'sh' if s.startswith('1.') else 'sz'}{s.split('.')[1]}" for s, _ in INDICES)
        r = requests.get(f"https://qt.gtimg.cn/q={q}", timeout=TIMEOUT)
        r.encoding = "gbk"
        name_of = {s.split(".")[1]: n for s, n in INDICES}
        secid_of = {s.split(".")[1]: s for s, _ in INDICES}
        have = {e.split(".")[1] for e in existing}
        for part in r.text.split(";"):
            p = part.split("=")
            if len(p) < 2 or "~" not in p[1]:
                continue
            f = p[1].split("~")
            if len(f) < 6:
                continue
            code = f[2]
            if code not in name_of or code in have:
                continue
            out[secid_of[code]] = {
                "f2": float(f[3]), "f3": float(f[5]), "f4": float(f[4]),
                "f12": code, "f14": name_of[code],
            }
        print(f"[quotes] 腾讯兜底指数: {len(out)} 只")
    except Exception as e:
        print(f"[quotes] warn: 腾讯指数兜底也失败: {e}")
    return out


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


def sum_amt(quotes, secids):
    """累加指定 secid 列表的当日成交额(f6)，单位：元"""
    total = 0.0
    for secid in secids:
        q = quotes.get(secid)
        if q and q.get("f6"):
            try:
                total += float(q["f6"])
            except (TypeError, ValueError):
                pass
    return total


def update_intraday(quotes):
    """累加当前时刻成交额，追加到 data/intraday.json 的今日曲线。
    同时维护全池21只(points)与核心8只(points8)，每 10 分钟一个点。"""
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))  # 北京时间
    date = now.strftime("%Y-%m-%d")
    mm = (now.minute // 10) * 10
    t = f"{now.hour:02d}:{mm:02d}"

    total = sum_amt(quotes, [s for s, _ in ETFS])
    total8 = sum_amt(quotes, CORE8)
    if total <= 0:
        return

    ipath = os.path.join(DATA_DIR, "intraday.json")
    data = {"ok": True, "date": date, "points": [], "points8": [], "hist": {}, "hist8": {}, "total_yi": 0.0, "total8_yi": 0.0}
    if os.path.exists(ipath):
        try:
            with open(ipath, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {"ok": True, "date": date, "points": [], "points8": [], "hist": {}, "hist8": {}, "total_yi": 0.0, "total8_yi": 0.0}
    if data.get("date") != date:
        data = {"ok": True, "date": date, "points": [], "points8": [],
                "hist": data.get("hist", {}), "hist8": data.get("hist8", {}),
                "total_yi": 0.0, "total8_yi": 0.0}

    def upd(pts, v):
        lst = [p for p in (pts or []) if p.get("t") != t]
        lst.append({"t": t, "v": round(v / 1e8, 2)})
        lst.sort(key=lambda p: p["t"])
        return lst

    data["points"] = upd(data.get("points"), total)
    if total8 > 0:
        data["points8"] = upd(data.get("points8"), total8)
    data["total_yi"] = round(total / 1e8, 2)
    data["total8_yi"] = round(total8 / 1e8, 2)
    data["updated"] = now.strftime("%Y-%m-%d %H:%M")

    tmp = ipath + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, ipath)


def fetch_5min_today(sess, secid):
    """抓当日 5 分钟 K 线 -> {HH:MM: 成交额(元)}"""
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    data = get_json(sess, url, {
        "secid": secid, "klt": "5", "fqt": "1", "end": "20500101", "lmt": "48",
        "fields1": "f1,f2,f3", "fields2": "f51,f52,f53,f54,f55,f56,f57",
    })
    kl = (data or {}).get("data", {}).get("klines") or []
    out = {}
    for line in kl:
        p = line.split(",")
        if len(p) < 7:
            continue
        parts = p[0].split(" ")
        if len(parts) != 2:
            continue
        t = parts[1][:5]
        try:
            amt = float(p[6])
        except ValueError:
            continue
        out[t] = out.get(t, 0.0) + amt
    return out


def agg_10min_cum(day_map):
    """{HH:MM: 5min成交额} -> [{t, v(亿)}] 10分钟累计曲线（上午/下午分开累计）"""
    pts = []
    cum = 0.0
    for t in _AM5:
        cum += day_map.get(t, 0.0)
        if t in _TIME_SET:
            pts.append({"t": t, "v": round(cum / 1e8, 2)})
    cum = 0.0
    for t in _PM5:
        cum += day_map.get(t, 0.0)
        if t in _TIME_SET:
            pts.append({"t": t, "v": round(cum / 1e8, 2)})
    return pts


def append_today_to_hist(sess):
    """收盘后(15:00)：抓当日 5 分钟 K 线聚合出当日 10 分钟累计曲线，
    追加到 intraday.json 的 hist / hist8（核心8只），各自滚动保留最近 20 个交易日。"""
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    date = now.strftime("%Y-%m-%d")
    if now.hour < 15 or now.weekday() >= 5:
        return

    def collect(secids):
        day_map = {}
        for secid in secids:
            try:
                m = fetch_5min_today(sess, secid)
                for t, v in m.items():
                    day_map[t] = day_map.get(t, 0.0) + v
            except Exception:
                pass
            time.sleep(0.1)
        return day_map

    pool_map = collect([s for s, _ in ETFS])
    core8_map = collect(CORE8)
    ipath = os.path.join(DATA_DIR, "intraday.json")
    data = {"ok": True, "date": date, "points": [], "points8": [], "hist": {}, "hist8": {}, "total_yi": 0.0, "total8_yi": 0.0}
    if os.path.exists(ipath):
        try:
            with open(ipath, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass

    def append_hist(hist, day_map, tag):
        if not day_map:
            return hist
        pts = agg_10min_cum(day_map)
        if len(pts) < 20:
            return hist
        hist = dict(hist or {})
        hist[date] = pts
        dates = sorted(hist)
        for old in dates[:-20]:
            hist.pop(old, None)
        print(f"[intraday] 已追加 {date} 至 {tag}（共 {len(hist)} 天）")
        return hist

    data["hist"] = append_hist(data.get("hist"), pool_map, "hist")
    data["hist8"] = append_hist(data.get("hist8"), core8_map, "hist8")
    data["hist_days"] = len(data.get("hist") or {})
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
    append_today_to_hist(sess)  # 收盘后追加当日曲线至 hist（滚动20天）

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
