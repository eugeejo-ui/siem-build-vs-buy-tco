"""인증 실패 원인 분리: 키 인코딩 형태 문제인가, 미등록 문제인가.

키는 이 프로세스 밖으로 나가지 않는다. 출력 전 항상 마스킹한다.
"""
import pathlib
import urllib.parse

import requests

ROOT = pathlib.Path(__file__).parent.parent.parent
BASE = "https://apis.data.go.kr/1230000/at/ShoppingMallPrdctInfoService/getShoppingMallPrdctInfoList"

enc = next(l.split("=", 1)[1].strip()
           for l in (ROOT / ".env").read_text(encoding="utf-8").splitlines()
           if l.startswith("G2B_SERVICE_KEY="))
dec = urllib.parse.unquote(enc)

TAIL = "&type=json&pageNo=1&numOfRows=3&inqryDiv=1&inqryBgnDate=20260101&inqryEndDate=20260131"


def mask(t):
    for f in (enc, dec, urllib.parse.quote(dec, safe=""), urllib.parse.quote_plus(dec)):
        t = t.replace(f, "<KEY>")
    return t


def show(tag, r):
    body = mask(r.text)
    for marker in ("errMsg", "returnAuthMsg", "returnReasonCode", "resultCode", "resultMsg", "totalCount"):
        for line in body.splitlines():
            if marker in line:
                print(f"    {line.strip()}")
                break
    print(f"  [{tag}] HTTP {r.status_code}")


print("키 형태 비교 (같은 엔드포인트, 같은 파라미터)")
print(f"  Encoding 길이 {len(enc)} / Decoding 길이 {len(dec)}")

# A: 이미 인코딩된 키를 URL 문자열에 그대로 — 재인코딩 없음
show("A · Encoding 키 원문 URL", requests.get(BASE + "?serviceKey=" + enc + TAIL, timeout=30))

# B: 디코딩한 키를 params 로 — requests 가 인코딩
show("B · Decoding 키 + params", requests.get(BASE, params={
    "serviceKey": dec, "type": "json", "pageNo": "1", "numOfRows": "3",
    "inqryDiv": "1", "inqryBgnDate": "20260101", "inqryEndDate": "20260131"}, timeout=30))

# C: 다른 오퍼레이션 — API 단위 구독 문제인지 확인
show("C · MAS계약 오퍼레이션", requests.get(
    BASE.replace("getShoppingMallPrdctInfoList", "getMASCntrctPrdctInfoList")
    + "?serviceKey=" + enc + "&type=json&pageNo=1&numOfRows=3&inqryDiv=1", timeout=30))
