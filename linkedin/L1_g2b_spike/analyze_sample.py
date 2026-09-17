# -*- coding: utf-8 -*-
"""L1-b 3단계: 표본 대량 수집 후 5개 이월 질문 판정."""
import json, pathlib, re, time, urllib.parse
from collections import Counter
import requests

HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent.parent
enc = next(l.split("=", 1)[1].strip()
           for l in (ROOT / ".env").read_text(encoding="utf-8").splitlines()
           if l.startswith("G2B_SERVICE_KEY="))
dec = urllib.parse.unquote(enc)
BASE = "https://apis.data.go.kr/1230000/at/ShoppingMallPrdctInfoService"


def mask(t):
    for f in (enc, dec, urllib.parse.quote_plus(dec)):
        t = t.replace(f, "<KEY>")
    return t


def fetch(page, rows=100):
    q = {"serviceKey": enc, "type": "json", "pageNo": str(page), "numOfRows": str(rows),
         "inqryDiv": "1", "prdctClsfcNoNm": "디스크어레이",
         "inqryBgnDate": "20260101", "inqryEndDate": "20260630"}
    url = f"{BASE}/getShoppingMallPrdctInfoList?" + "&".join(
        f"{k}={v if k == 'serviceKey' else urllib.parse.quote(str(v), safe='')}"
        for k, v in q.items())
    for i in range(3):
        try:
            d = json.loads(mask(requests.get(url, timeout=120).text))
            b = (d.get("response") or {}).get("body") or {}
            it = b.get("items")
            if isinstance(it, dict):
                it = it.get("item", [])
            return b.get("totalCount"), (it or [])
        except Exception:                        # noqa: BLE001
            time.sleep(5)
    return None, []


allitems = []
for pg in (1, 2, 3, 4):
    tc, items = fetch(pg)
    allitems.extend(items)
    print(f"  page {pg}: +{len(items)}건 (totalCount={tc})")
    if not items:
        break
    time.sleep(1)

print(f"\n수집 총계 {len(allitems)}건\n" + "=" * 64)

# --- Q1/Q2. 규격명에서 용량 파싱 -----------------------------------------
CAP = re.compile(r"(\d+(?:\.\d+)?)\s*(TB|GB|PB)\b", re.I)
parsed, failed = [], []
for it in allitems:
    spec = it.get("prdctSpecNm") or ""
    m = CAP.search(spec)
    if m:
        val, unit = float(m.group(1)), m.group(2).upper()
        tb = val * (1000 if unit == "PB" else 1 if unit == "TB" else 1 / 1000)
        parsed.append((tb, it))
    else:
        failed.append(spec)

rate = len(parsed) / len(allitems) * 100 if allitems else 0
print(f"[Q1] 규격명 용량 파싱 성공 {len(parsed)}/{len(allitems)} = {rate:.1f}%")
if failed:
    print(f"     실패 예시: {failed[0][:90]}")

# --- Q3. 제조사 분포 ------------------------------------------------------
print(f"\n[Q3] 제조사 분포 (상위 12)")
for nm, c in Counter((it.get("prdctMakrNm") or "?") for it in allitems).most_common(12):
    print(f"     {c:>4}건  {nm}")

GLOBAL = ["dell", "hpe", "hp", "netapp", "ibm", "lenovo", "hitachi", "pure", "emc", "효성", "삼성"]
g = [it for it in allitems if any(v in (it.get("prdctMakrNm") or "").lower() for v in GLOBAL)]
print(f"     → 글로벌 벤더 매칭: {len(g)}건")

# --- Q5. dscntAmt 채움률 --------------------------------------------------
filled = sum(1 for it in allitems if it.get("dscntAmt") not in (None, "", 0, "0"))
print(f"\n[Q5] dscntAmt 채움 {filled}/{len(allitems)} = {filled/len(allitems)*100 if allitems else 0:.1f}%")

# --- TB당 단가 ------------------------------------------------------------
print(f"\n[단가] TB당 계약단가 (원)")
rows = []
for tb, it in parsed:
    try:
        amt = float(it.get("cntrctPrceAmt") or 0)
    except (TypeError, ValueError):
        continue
    if amt > 0 and tb > 0:
        rows.append((amt / tb, tb, amt, it.get("prdctMakrNm"), (it.get("prdctSpecNm") or "")[:60]))
rows.sort()
if rows:
    print(f"     건수 {len(rows)} | 최저 {rows[0][0]:,.0f} | 중앙 {rows[len(rows)//2][0]:,.0f} | 최고 {rows[-1][0]:,.0f}")
    print("\n     -- 표본 6건 --")
    for r in rows[:3] + rows[-3:]:
        print(f"     {r[0]:>12,.0f}/TB  {r[1]:>7.1f}TB  {r[3]}")
        print(f"                   {r[4]}")

(HERE / "raw").mkdir(exist_ok=True)
(HERE / "raw/diskarray_bulk.json").write_text(
    json.dumps(allitems, ensure_ascii=False, indent=2), encoding="utf-8")
