# -*- coding: utf-8 -*-
"""L1-b 2단계: 하드디스크어레이 품목의 규격명 형식과 표본 규모 확인."""
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
    q = {"serviceKey": enc, "type": "json", "pageNo": "1", "numOfRows": "10", "inqryDiv": "1"}
    q.update(kw)
    url = f"{BASE}/{op}?" + "&".join(
        f"{k}={v if k == 'serviceKey' else urllib.parse.quote(str(v), safe='')}"
        for k, v in q.items())
    for i in range(tries):
        try:
            return json.loads(mask(requests.get(url, timeout=90).text))
        except json.JSONDecodeError as e:
            return {"_raw": str(e)[:200]}
        except Exception as e:                   # noqa: BLE001
            if i == tries - 1:
                return {"_err": mask(str(e))[:120]}
            time.sleep(4)


def unwrap(d):
    if "_err" in d or "_raw" in d:
        return None, []
    b = (d.get("response") or {}).get("body") or {}
    it = b.get("items")
    if isinstance(it, dict):
        it = it.get("item", [])
    if isinstance(it, dict):
        it = [it]
    return b.get("totalCount"), (it or [])


# 1. 날짜 범위별 실제 규모
print("[규모] 하드디스크어레이 — 등록일 구간별")
for bgn, end in [("20250101", "20251231"), ("20260101", "20260630")]:
    tc, _ = unwrap(call("getShoppingMallPrdctInfoList", prdctClsfcNoNm="디스크어레이",
                        inqryBgnDate=bgn, inqryEndDate=end, numOfRows="1"))
    print(f"  {bgn}~{end}: totalCount={tc}")
    time.sleep(0.5)

# 2. 규격명 형식 — 표본 수집
print("\n[규격명] 하드디스크어레이 표본")
tc, items = unwrap(call("getShoppingMallPrdctInfoList",
                        prdctClsfcNoNm="디스크어레이", numOfRows="10"))
print(f"  (날짜 무제한 totalCount={tc}, 수집 {len(items)}건)\n")
for i, it in enumerate(items, 1):
    print(f"  [{i}] 제조사={it.get('prdctMakrNm')} | 단가={it.get('cntrctPrceAmt')} {it.get('prdctUnit')}")
    print(f"      세부품명: {it.get('dtilPrdctClsfcNoNm')}")
    print(f"      규격명  : {str(it.get('prdctSpecNm'))[:170]}")
    print(f"      할인금액: {it.get('dscntAmt')} | 계약기간: {it.get('cntrctBgnDate')}~{it.get('cntrctEndDate')}")
    print()

(HERE / "raw").mkdir(exist_ok=True)
(HERE / "raw/diskarray_sample.json").write_text(
    json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
