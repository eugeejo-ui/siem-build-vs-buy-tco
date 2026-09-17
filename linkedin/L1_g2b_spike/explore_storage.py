# -*- coding: utf-8 -*-
"""L1-b 1단계: 스토리지 포착 키워드 탐색 + 응답 구조 확인."""
import json, pathlib, time, urllib.parse
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


def call(op, tries=3, **kw):
    q = {"serviceKey": enc, "type": "json", "pageNo": "1", "numOfRows": "3", "inqryDiv": "1"}
    q.update(kw)
    url = f"{BASE}/{op}?" + "&".join(
        f"{k}={v if k == 'serviceKey' else urllib.parse.quote(str(v), safe='')}"
        for k, v in q.items())
    for i in range(tries):
        try:
            r = requests.get(url, timeout=90)
            return json.loads(mask(r.text))
        except json.JSONDecodeError:
            return {"_raw": mask(r.text)[:300]}
        except Exception as e:                   # noqa: BLE001
            if i == tries - 1:
                return {"_err": mask(str(e))[:120]}
            time.sleep(3)


def unwrap(d):
    if "_err" in d or "_raw" in d:
        return None, [], d.get("_err") or d.get("_raw")
    b = (d.get("response") or {}).get("body") or {}
    it = b.get("items")
    if isinstance(it, dict):
        it = it.get("item", [])
    if isinstance(it, dict):
        it = [it]
    return b.get("totalCount"), (it or []), None


print("[키워드] prdctClsfcNoNm(품명) 필터")
KEYWORDS = ["스토리지", "디스크어레이", "저장장치", "네트워크저장장치",
            "자기디스크장치", "반도체디스크", "서버", "자기테이프장치"]
hits = {}
for kw in KEYWORDS:
    tc, items, err = unwrap(call("getShoppingMallPrdctInfoList", prdctClsfcNoNm=kw, numOfRows="1"))
    hits[kw] = tc
    note = err if err else (items[0].get("prdctClsfcNoNm") if items else "-")
    print(f"  {kw:<16} totalCount={str(tc):<8} {str(note)[:50]}")
    time.sleep(0.5)

(HERE / "raw").mkdir(exist_ok=True)
(HERE / "raw/keyword_hits.json").write_text(
    json.dumps(hits, ensure_ascii=False, indent=2), encoding="utf-8")

best = max((k for k, v in hits.items() if v), key=lambda k: hits[k], default=None)
if best:
    print(f"\n[구조] 최다 적중 키워드 '{best}' 표본")
    tc, items, err = unwrap(call("getShoppingMallPrdctInfoList",
                                 prdctClsfcNoNm=best, numOfRows="3"))
    for i, it in enumerate(items[:2], 1):
        print(f"\n  -- 표본 {i} --")
        for k in ("prdctLrgclsfcNm", "prdctMidclsfcNm", "prdctClsfcNoNm",
                  "dtilPrdctClsfcNoNm", "prdctSpecNm", "prdctMakrNm",
                  "cntrctCorpNm", "cntrctPrceAmt", "prdctUnit"):
            print(f"    {k:<20} {str(it.get(k))[:70]}")
