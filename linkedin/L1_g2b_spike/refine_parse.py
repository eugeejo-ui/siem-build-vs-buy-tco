# -*- coding: utf-8 -*-
"""L1-b 4단계: 캐시 오탐 제거 후 실제 파싱률과 TB당 단가 재산출."""
import json, pathlib, re
from collections import Counter

HERE = pathlib.Path(__file__).parent
items = json.loads((HERE / "raw/diskarray_bulk.json").read_text(encoding="utf-8"))

CACHE_HINT = re.compile(r"\(\s*캐시\s*\)|캐시")
CAP = re.compile(r"(\d+(?:[.,]\d+)?)\s*(PB|TB|GB)\b", re.I)


def capacity_tb(spec):
    """규격명에서 디스크 용량(TB)을 뽑는다. 캐시 수치는 제외한다.

    관측된 형식: '디스크어레이, {제조사}, {모델}, {용량}/{캐시}(캐시)'
    캐시만 있고 용량이 없는 건은 파싱 실패로 처리한다.
    """
    # '/' 앞 토큰이 용량, 뒤가 캐시인 패턴을 우선 적용
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(PB|TB|GB)\s*/\s*\d+(?:[.,]\d+)?\s*(?:GB|TB)\s*\(?\s*캐시",
                  spec, re.I)
    if not m:
        # 캐시 표기가 붙은 수치는 후보에서 제외
        cands = [mm for mm in CAP.finditer(spec)
                 if not CACHE_HINT.search(spec[mm.end():mm.end() + 8])]
        if not cands:
            return None, "캐시만 기재"
        m = cands[0]
    val = float(m.group(1).replace(",", ""))
    unit = m.group(2).upper()
    if unit == "GB" and val < 500:          # 500GB 미만 단일 수치는 디스크 용량으로 보기 어려움
        return None, "용량 미기재(소용량 수치만)"
    return val * {"PB": 1000, "TB": 1, "GB": 0.001}[unit], None


def norm_vendor(v):
    v = (v or "?").strip()
    low = v.lower()
    for key, canon in [("dell", "Dell"), ("hitachi", "Hitachi"), ("ibm", "IBM"),
                       ("infortrend", "Infortrend"), ("fujitsu", "Fujitsu"),
                       ("netapp", "NetApp"), ("hpe", "HPE"), ("seagate", "Seagate"),
                       ("lenovo", "Lenovo"), ("huawei", "Huawei")]:
        if key in low:
            return canon
    return v


ok, fail = [], Counter()
for it in items:
    tb, why = capacity_tb(it.get("prdctSpecNm") or "")
    if tb:
        ok.append((tb, it))
    else:
        fail[why] += 1

print(f"[Q1 정정] 용량 파싱 성공 {len(ok)}/{len(items)} = {len(ok)/len(items)*100:.1f}%")
for why, c in fail.most_common():
    print(f"          실패 {c:>3}건 — {why}")

print(f"\n[Q3 정정] 제조사 정규화 후")
for nm, c in Counter(norm_vendor(it.get("prdctMakrNm")) for it in items).most_common(8):
    print(f"          {c:>4}건  {nm}")

rows = []
for tb, it in ok:
    try:
        amt = float(it.get("cntrctPrceAmt") or 0)
    except (TypeError, ValueError):
        continue
    if amt > 0:
        rows.append((amt / tb, tb, amt, norm_vendor(it.get("prdctMakrNm"))))
rows.sort()

print(f"\n[단가] TB당 계약단가 — 유효 {len(rows)}건")
if rows:
    def pct(p):
        return rows[min(int(len(rows) * p), len(rows) - 1)][0]
    print(f"       최저 {rows[0][0]:>12,.0f}")
    print(f"       25%  {pct(.25):>12,.0f}")
    print(f"       중앙 {pct(.50):>12,.0f}")
    print(f"       75%  {pct(.75):>12,.0f}")
    print(f"       최고 {rows[-1][0]:>12,.0f}")

    print(f"\n       -- 제조사별 중앙값 (5건 이상) --")
    byv = {}
    for r in rows:
        byv.setdefault(r[3], []).append(r[0])
    for v, xs in sorted(byv.items(), key=lambda kv: -len(kv[1])):
        if len(xs) >= 5:
            xs.sort()
            print(f"       {v:<14} {len(xs):>3}건  중앙 {xs[len(xs)//2]:>11,.0f}원/TB"
                  f"  범위 {xs[0]:,.0f}~{xs[-1]:,.0f}")

    print(f"\n       -- 대용량(100TB 이상) 상위 --")
    big = sorted([r for r in rows if r[1] >= 100], key=lambda r: r[0])[:6]
    for r in big:
        print(f"       {r[0]:>10,.0f}원/TB  {r[1]:>8.0f}TB  {r[2]:>15,.0f}원  {r[3]}")
