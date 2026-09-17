# -*- coding: utf-8 -*-
"""키 전송 형태 x 스킴 매트릭스. 이전 테스트는 A와 B가 동일 바이트를 보냈으므로 무효."""
import pathlib, urllib.parse, json, re
import requests

ROOT = pathlib.Path(__file__).parent.parent.parent
enc = next(l.split("=", 1)[1].strip()
           for l in (ROOT / ".env").read_text(encoding="utf-8").splitlines()
           if l.startswith("G2B_SERVICE_KEY="))
dec = urllib.parse.unquote(enc)
dbl = urllib.parse.quote(enc, safe="")          # 이중 인코딩

PATH = "/1230000/at/ShoppingMallPrdctInfoService/getShoppingMallPrdctInfoList"
Q = "type=json&pageNo=1&numOfRows=3&inqryDiv=1&inqryBgnDate=20260101&inqryEndDate=20260131"


def mask(t):
    for f in (enc, dec, dbl, urllib.parse.quote_plus(dec)):
        t = t.replace(f, "<KEY>")
    return t


def verdict(r):
    b = mask(r.text)
    m = re.search(r'"errMsg"\s*:\s*"([^"]+)"', b) or re.search(r"<errMsg>([^<]+)</errMsg>", b)
    c = re.search(r'"resultCode"\s*:\s*"?([^",}]+)', b) or re.search(r"<resultCode>([^<]+)</resultCode>", b)
    t = re.search(r'"totalCount"\s*:\s*"?(\d+)', b)
    if m:
        return f"ERR {m.group(1)}"
    if c:
        return f"resultCode={c.group(1).strip()}" + (f" totalCount={t.group(1)}" if t else "")
    return b[:90].replace("\n", " ")


def run(label, url):
    try:
        r = requests.get(url, timeout=25)
        print(f"  {label:<44} HTTP {r.status_code}  {verdict(r)}")
    except Exception as e:
        print(f"  {label:<44} FAIL {mask(str(e))[:70]}")


for scheme in ("https", "http"):
    print(f"\n[{scheme}] apis.data.go.kr")
    base = f"{scheme}://apis.data.go.kr{PATH}"
    run("1 Encoding 키 원문 (재인코딩 없음)", f"{base}?serviceKey={enc}&{Q}")
    run("2 Decoding 키 원문 (인코딩 안 함)", f"{base}?serviceKey={dec}&{Q}")
    run("3 Encoding 키를 한 번 더 인코딩", f"{base}?serviceKey={dbl}&{Q}")
    run("4 serviceKey 단독 (다른 파라미터 없음)", f"{base}?serviceKey={enc}")
    run("5 _type=json 표기", f"{base}?serviceKey={enc}&_type=json&pageNo=1&numOfRows=3&inqryDiv=1")
