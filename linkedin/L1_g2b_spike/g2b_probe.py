"""L1-b 탐색 스크립트 (스파이크용 — L2에서 정식 수집기로 승격 여부 판단).

목적: 나라장터 종합쇼핑몰 API에 온프렘 스토리지 단가가 쓸 만한 형태로 있는지 판정.
원칙: 전량 수집하지 않는다. 표본만 본다. 인증키는 어떤 출력에도 남기지 않는다.
"""
import json
import os
import pathlib
import sys
import urllib.parse

import requests

BASE = "https://apis.data.go.kr/1230000/at/ShoppingMallPrdctInfoService"
HERE = pathlib.Path(__file__).parent
RAW = HERE / "raw"          # .gitignore 로 차단된 경로
ROOT = HERE.parent.parent


def load_key():
    """.env 에서 인증키를 읽는다. Encoding 키를 unquote 해서 반환한다.

    requests 가 params 를 다시 인코딩하므로, 이미 퍼센트 인코딩된 키를 그대로
    넘기면 '%2B' 가 '%252B' 가 되어 인증이 깨진다.
    """
    env = ROOT / ".env"
    if not env.exists():
        sys.exit(".env 없음")
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("G2B_SERVICE_KEY="):
            raw = line.split("=", 1)[1].strip()
            if not raw:
                sys.exit("G2B_SERVICE_KEY 값이 비어 있음")
            return urllib.parse.unquote(raw)
    sys.exit("G2B_SERVICE_KEY 항목 없음")


KEY = load_key()


def mask(text):
    """어떤 문자열에서든 키 흔적을 지운다. 저장·출력 직전에 반드시 통과시킨다."""
    out = text
    for form in (KEY, urllib.parse.quote(KEY, safe=""), urllib.parse.quote_plus(KEY)):
        out = out.replace(form, "<SERVICE_KEY>")
    return out


def call(op, save_as=None, **params):
    """오퍼레이션 1회 호출. (상태코드, 파싱된 body 또는 원문) 반환."""
    p = {"serviceKey": KEY, "type": "json", "pageNo": "1", "numOfRows": "5"}
    p.update({k: v for k, v in params.items() if v is not None})
    try:
        r = requests.get(f"{BASE}/{op}", params=p, timeout=30)
    except Exception as e:                      # noqa: BLE001
        return None, f"REQUEST_FAILED: {mask(str(e))}"

    body = mask(r.text)
    if save_as:
        RAW.mkdir(exist_ok=True)
        (RAW / save_as).write_text(body, encoding="utf-8")
    try:
        return r.status_code, json.loads(body)
    except json.JSONDecodeError:
        return r.status_code, body[:1500]       # XML 에러응답 등


def summarize(tag, status, data):
    print(f"\n{'=' * 60}\n[{tag}] HTTP {status}")
    if isinstance(data, str):
        print(data)
        return None
    hdr = (data.get("response") or {}).get("header") or data.get("header") or {}
    bdy = (data.get("response") or {}).get("body") or data.get("body") or {}
    print("resultCode:", hdr.get("resultCode"), "/", hdr.get("resultMsg"))
    print("totalCount:", bdy.get("totalCount"))
    items = (bdy.get("items") or {})
    if isinstance(items, dict):
        items = items.get("item") or []
    if isinstance(items, dict):
        items = [items]
    print("items:", len(items))
    return items


if __name__ == "__main__":
    # 1차: 인증 자체가 통하는지만 본다. 필터 없이 최소 호출.
    st, d = call("getShoppingMallPrdctInfoList", save_as="probe01_auth.json",
                 inqryDiv="1", inqryBgnDate="20260101", inqryEndDate="20260131")
    items = summarize("인증 확인 / 품목등록내역", st, d)
    if items:
        print("\n-- 첫 건 필드 --")
        for k, v in list(items[0].items()):
            print(f"  {k}: {str(v)[:70]}")
