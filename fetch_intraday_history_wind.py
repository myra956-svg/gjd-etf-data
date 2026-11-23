#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 wind get_fund_kline(10分钟K线) 回补「跟踪池近20日累计成交额」历史基准。

直接调用 WorkBuddy 会话内的 wind MCP HTTP 接口（本地回环，stateless），
逐只抓 21 只 ETF 的近 20 个交易日 10 分钟 K 线，累加 TURNOVER(成交额,元)，
聚合出「跟踪池每天每 10 分钟的合计累计成交额」，写入 data/intraday.json 的 hist。

为什么不用东财：本地网络对 push2his 历史接口不通（直连/代理均失败），
且东财无 10 分钟粒度、需 5 分钟聚合；wind 直接给 10 分钟 bar，字段干净。
"""
import json
import os
import time
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
IPATH = os.path.join(DATA_DIR, "intraday.json")

# 21 只跟踪池 ETF 的 wind 代码（与 fetch_quotes.py ETFS 一致）
WINDS = [
    "510300.SH", "510330.SH", "510310.SH", "159919.SZ",
    "510050.SH", "510180.SH",
    "510500.SH", "512500.SH", "159922.SZ",
    "512100.SH", "159845.SZ", "560010.SH", "159629.SZ",
    "588000.SH", "588080.SH", "588050.SH",
    "159915.SZ", "159977.SZ", "159952.SZ",
    "515800.SH", "515850.SH",
]

# 10 分钟对齐时间点（与前端 minuteIndex / gen_intraday_seed 对齐）
TIMES = ["09:40", "09:50", "10:00", "10:10", "10:20", "10:30", "10:40", "10:50",
         "11:00", "11:10", "11:20", "11:30",
         "13:10", "13:20", "13:30", "13:40", "13:50", "14:00", "14:10", "14:20",
         "14:30", "14:40", "14:50", "15:00"]

BEGIN = "2026-10-26"
END = "2026-11-20"


def _wind_cfg():
    cfg = json.loads(os.environ["CODEBUDDY_MCP_CONFIG"])
    w = cfg["mcpServers"]["wind-finance"]
    return w["url"], dict(w.get("headers", {}))


def _rpc(url, headers, method, params):
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    req = urllib.request.Request(url, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json, text/event-stream")
    for k, v in headers.items():
        req.add_header(k, v)
    data = json.dumps(body).encode()
    r = urllib.request.urlopen(req, data, timeout=90)
    raw = r.read().decode()
    txt = raw
    if "data:" in txt:
        lines = [l for l in txt.splitlines() if l.startswith("data:")]
        txt = lines[-1][5:].strip() if lines else raw
    return json.loads(txt)


def call_fund_kline(url, headers, windcode, beg, end):
    resp = _rpc(url, headers, "tools/call", {
        "name": "get_fund_kline",
        "arguments": {"windcode": windcode, "begin_date": beg, "end_date": end,
                      "period": "4", "count": 0},
    })
    content = resp["result"]["content"]
    text = content[0]["text"]
    return json.loads(text)


def main():
    url, headers = _wind_cfg()
    # 初始化（stateless，幂等）
    try:
        _rpc(url, headers, "initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "py", "version": "1.0"}})
    except Exception:
        pass

    per_day = {}  # date -> {HH:MM: 合计成交额(元)}
    for wc in WINDS:
        ok = False
        for attempt in range(3):
            try:
                d = call_fund_kline(url, headers, wc, BEGIN, END)
                cols = [c["name"] for c in d["data"]["columns"]]
                ti, to = cols.index("TIME"), cols.index("TURNOVER")
                n = 0
                for row in d["data"]["rows"]:
                    t = row[ti]  # "2026-11-18T09:40:00.000+08:00"
                    date, tm = t[:10], t[11:16]
                    try:
                        amt = float(row[to])
                    except (ValueError, TypeError):
                        continue
                    dd = per_day.setdefault(date, {})
                    dd[tm] = dd.get(tm, 0.0) + amt
                    n += 1
                print(f"  {wc}: {n} 条")
                ok = True
                break
            except Exception as e:
                if attempt == 2:
                    print(f"  [warn] {wc} 失败: {e}")
                time.sleep(1 + attempt)
        time.sleep(0.15)

    # 聚合为 10 分钟累计曲线（上午/下午分开累计）
    hist = {}
    for date in sorted(per_day):
        m = per_day[date]
        pts = []
        cum = 0.0
        for t in TIMES[:12]:   # 上午
            cum += m.get(t, 0.0)
            pts.append({"t": t, "v": round(cum / 1e8, 2)})
        cum = 0.0
        for t in TIMES[12:]:   # 下午
            cum += m.get(t, 0.0)
            pts.append({"t": t, "v": round(cum / 1e8, 2)})
        if len(pts) >= 20:
            hist[date] = pts

    # 写入 intraday.json，保留今日 points
    data = {"ok": True, "date": END, "points": [], "hist": {}, "total_yi": 0.0}
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

    days = list(hist)
    print(f"\n历史基准: {len(hist)} 个交易日 -> {days[0] if days else '-'} ~ {days[-1] if days else '-'}")
    if hist:
        # 打印最后一天的曲线作校验
        last = hist[days[-1]]
        print(f"样例({days[-1]}) 首末点:", last[0], "->", last[-1])
    print(f"已写入 {IPATH}")


if __name__ == "__main__":
    main()
