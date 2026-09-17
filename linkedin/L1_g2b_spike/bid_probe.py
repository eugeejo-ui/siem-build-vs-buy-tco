# -*- coding: utf-8 -*-
"""지금 접근 가능한 입찰공고정보서비스에 스토리지 조달이 잡히는지 본다."""
import json, pathlib, urllib.parse
import requests

ROOT = pathlib.Path(__file__).parent.parent.parent
enc = next(l.split("=", 1)[1].strip()
           for l in (ROOT / ".env").read_text(encoding="utf-8").splitlines()
           if l.startswith("G2B_SERVICE_KEY="))
dec = urllib.parse.unquote(enc)
BASE = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService"


def mask(t):
    for f in (enc, dec, urllib.parse.quote_plus(dec)):
        t = t.replace(f, "<KEY>")
    return t


def call(op, **kw):
    q = {"serviceKey": enc, "type": "json", "pageNo": "1", "numOfRows": "3",
         "inqryDiv": "1", "inqryBgnDt": "202606010000", "inqryEndDt": "202608312359"}
    q.update(kw)
    url = BASE + "/" + op + "?" + "&".join(f"{k}={v}" for k, v in q.items())
    r = requests.get(url, timeout=30)
    try:
        return json.loads(mask(r.text))
    except json.JSONDecodeError:
        return {"_raw": mask(r.text)[:300]}


d = call("getBidPblancListInfoThng")
body = (d.get("response") or {}).get("body") or {}
print("전체 물품 입찰공고 건수(2026-06~08):", body.get("totalCount"))
items = (body.get("items") or [])
if isinstance(items, dict):
    items = items.get("item", [])
if items:
    print("\n-- 응답 필드 --")
    for k, v in items[0].items():
        s = str(v)
        if s and s not in ("", "null"):
            print(f"  {k}: {s[:60]}")

print("\n\n=== 스토리지 키워드 검색 ===")
for kw in ("스토리지", "디스크", "저장장치", "서버"):
    d = call("getBidPblancListInfoThng", bidNtceNm=urllib.parse.quote(kw), numOfRows="1")
    b = (d.get("response") or {}).get("body") or {}
    print(f"  공고명 '{kw}': totalCount={b.get('totalCount')}")
