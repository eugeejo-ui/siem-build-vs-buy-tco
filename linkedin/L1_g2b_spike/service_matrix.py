# -*- coding: utf-8 -*-
"""같은 키로 조달청 4개 서비스를 친다.

판별 원리: 코드 30(SERVICE_KEY_IS_NOT_REGISTERED)이 아닌 응답이 나오면
그 API는 인증을 통과한 것이다. 파라미터 오류가 나와도 '통과'다.
"""
import pathlib, re, urllib.parse
import requests

ROOT = pathlib.Path(__file__).parent.parent.parent
enc = next(l.split("=", 1)[1].strip()
           for l in (ROOT / ".env").read_text(encoding="utf-8").splitlines()
           if l.startswith("G2B_SERVICE_KEY="))
dec = urllib.parse.unquote(enc)

SERVICES = [
    ("15129471 종합쇼핑몰 품목정보", "1230000/at/ShoppingMallPrdctInfoService", "getShoppingMallPrdctInfoList"),
    ("15129397 낙찰정보",          "1230000/as/ScsbidInfoService",           "getScsbidListSttusThng"),
    ("15129427 계약정보",          "1230000/ao/CntrctInfoService",           "getCntrctInfoListThng"),
    ("15129394 입찰공고",          "1230000/ad/BidPublicInfoService",        "getBidPblancListInfoThng"),
]


def mask(t):
    for f in (enc, dec, urllib.parse.quote_plus(dec)):
        t = t.replace(f, "<KEY>")
    return t


for name, path, op in SERVICES:
    url = (f"https://apis.data.go.kr/{path}/{op}"
           f"?serviceKey={enc}&type=json&pageNo=1&numOfRows=2&inqryDiv=1"
           f"&inqryBgnDate=20260101&inqryEndDate=20260131"
           f"&inqryBgnDt=202601010000&inqryEndDt=202601312359")
    try:
        r = requests.get(url, timeout=25)
        b = mask(r.text)
        err = re.search(r'"errMsg"\s*:\s*"([^"]+)"', b) or re.search(r"<errMsg>([^<]+)</errMsg>", b)
        rc = re.search(r'"resultCode"\s*:\s*"?([^",}]+)', b) or re.search(r"<resultCode>([^<]+)</resultCode>", b)
        rm = re.search(r'"resultMsg"\s*:\s*"([^"]+)"', b) or re.search(r"<resultMsg>([^<]+)</resultMsg>", b)
        tc = re.search(r'"totalCount"\s*:\s*"?(\d+)', b)

        if err and "SERVICE_KEY_IS_NOT_REGISTERED" in err.group(1):
            mark, detail = "인증실패", "코드30 미등록"
        elif err:
            mark, detail = "인증통과", f"다른오류: {err.group(1)}"
        elif rc:
            v = rc.group(1).strip()
            ok = v in ("00", "0")
            mark = "인증통과"
            detail = f"resultCode={v}" + (f" / {rm.group(1)}" if rm else "")
            if tc:
                detail += f" / totalCount={tc.group(1)}"
        else:
            mark, detail = "판정불가", b[:80].replace("\n", " ")
        print(f"[{mark}] {name:<26} HTTP {r.status_code}  {detail}")
    except Exception as e:
        print(f"[요청실패] {name:<26} {mask(str(e))[:70]}")
