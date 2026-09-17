# -*- coding: utf-8 -*-
"""L2 나라장터 수집기 — 스토리지 장비 조달 단가를 용량 구간별로 집계한다.

사용법
    python g2b_collect.py explore   # 품명 키워드 탐색 (날짜 범위 포함)
    python g2b_collect.py collect   # 확정 품명으로 전 기간 수집·집계

원칙
- 인증키는 .env 에서만 읽고, 출력·저장 전 반드시 mask()를 통과시킨다.
- 원본 응답은 raw/ (gitignore) 에만 둔다. out/ 에는 가공 결과만 둔다.
- 원 프로젝트(src/, data/)는 읽지도 쓰지도 않는다. 이 파일은 조달 데이터만 다룬다.
"""
import json
import pathlib
import re
import statistics
import sys
import time
import urllib.parse
from collections import Counter

import requests

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
RAW = HERE / "raw"
OUT = HERE / "out"
BASE = "https://apis.data.go.kr/1230000/at/ShoppingMallPrdctInfoService"
OP = "getShoppingMallPrdctInfoList"

# 2025-01-01 ~ 조회일. 넓은 범위는 응답이 느려 반기 단위로 나눈다.
WINDOWS = [
    ("20250101", "20250630"),
    ("20250701", "20251231"),
    ("20260101", "20260630"),
    ("20260701", "20260916"),
]
EXPLORE_WINDOW = ("20260101", "20260630")   # L1에서 362건이 확인된 구간

EXPLORE_KEYWORDS = [
    "디스크어레이", "스토리지", "저장장치", "네트워크", "NAS",
    "테이프", "백업", "디스크", "반도체", "서버",
]

# 용량 구간 (TB). 경계는 하한 포함, 상한 미포함.
BANDS = [("~10", 0, 10), ("10~50", 10, 50), ("50~100", 50, 100),
         ("100~500", 100, 500), ("500~", 500, float("inf"))]

VENDOR_CANON = [
    ("dell", "Dell"), ("hitachi", "Hitachi"), ("ibm", "IBM"),
    ("infortrend", "Infortrend"), ("fujitsu", "Fujitsu"), ("netapp", "NetApp"),
    ("hpe", "HPE"), ("hewlett", "HPE"), ("seagate", "Seagate"),
    ("lenovo", "Lenovo"), ("huawei", "Huawei"), ("synology", "Synology"),
    ("qnap", "QNAP"), ("pure storage", "Pure Storage"),
]


# ---------------------------------------------------------------------------
# 인증키
# ---------------------------------------------------------------------------
def _load_key():
    env = ROOT / ".env"
    if not env.exists():
        sys.exit(".env 없음")
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("G2B_SERVICE_KEY="):
            val = line.split("=", 1)[1].strip()
            if val:
                return val
    sys.exit("G2B_SERVICE_KEY 없음")


KEY_ENC = _load_key()
KEY_DEC = urllib.parse.unquote(KEY_ENC)
_KEY_FORMS = {KEY_ENC, KEY_DEC, urllib.parse.quote(KEY_DEC, safe=""),
              urllib.parse.quote_plus(KEY_DEC)}


def mask(text):
    for f in _KEY_FORMS:
        text = text.replace(f, "<SERVICE_KEY>")
    return text


# ---------------------------------------------------------------------------
# 호출
# ---------------------------------------------------------------------------
CALLS = 0


def call(**params):
    """1회 호출. (totalCount, items, error) 반환.

    serviceKey 는 Encoding 원문을 URL에 그대로 붙이고, 나머지 값만 인코딩한다.
    """
    global CALLS
    q = {"type": "json", "pageNo": "1", "numOfRows": "100", "inqryDiv": "1"}
    q.update({k: str(v) for k, v in params.items()})
    url = (f"{BASE}/{OP}?serviceKey={KEY_ENC}&"
           + "&".join(f"{k}={urllib.parse.quote(v, safe='')}" for k, v in q.items()))
    last = None
    for attempt in range(3):
        CALLS += 1
        try:
            r = requests.get(url, timeout=120)
            body = json.loads(mask(r.text))
            b = (body.get("response") or {}).get("body") or {}
            it = b.get("items")
            if isinstance(it, dict):
                it = it.get("item", [])
            if isinstance(it, dict):
                it = [it]
            tc = b.get("totalCount")
            return (int(tc) if tc is not None else None), (it or []), None
        except json.JSONDecodeError:
            return None, [], mask(r.text)[:200]
        except Exception as e:                     # noqa: BLE001
            last = mask(str(e))[:120]
            time.sleep(5 * (attempt + 1))
    return None, [], last


# ---------------------------------------------------------------------------
# 파싱
# ---------------------------------------------------------------------------
# '{용량}/{캐시}(캐시)' 형식을 우선 적용한다 (L1 확정 형식).
_CAP_WITH_CACHE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(PB|TB|GB)\s*/\s*\d+(?:[.,]\d+)?\s*(?:GB|TB)\s*\(?\s*캐시", re.I)
_CAP_ANY = re.compile(r"(\d+(?:[.,]\d+)?)\s*(PB|TB|GB)\b", re.I)
_CACHE_NEAR = re.compile(r"캐시")
_UNIT = {"PB": 1000.0, "TB": 1.0, "GB": 0.001}


def parse_capacity_tb(spec):
    """규격명에서 디스크 용량(TB)을 뽑는다. (tb, 사유) 반환. 실패 시 tb=None.

    L1 교훈: '64GB(캐시)' 처럼 캐시 수치만 있는 본체 SKU를 용량으로 오인하면
    단가가 수억원/TB 로 튄다. 캐시 표기가 바로 뒤따르는 수치는 후보에서 뺀다.
    """
    spec = spec or ""
    m = _CAP_WITH_CACHE.search(spec)
    if not m:
        cands = [c for c in _CAP_ANY.finditer(spec)
                 if not _CACHE_NEAR.search(spec[c.end():c.end() + 8])]
        if not cands:
            return None, "용량 표기 없음(캐시만 또는 무표기)"
        m = cands[0]
    val = float(m.group(1).replace(",", ""))
    unit = m.group(2).upper()
    if val <= 0:
        return None, "용량 0 표기"
    if unit == "GB" and val < 500:
        return None, "소용량 수치만 있음(디스크 용량으로 보기 어려움)"
    return val * _UNIT[unit], None


def norm_vendor(name):
    raw = (name or "").strip()
    low = raw.lower()
    for key, canon in VENDOR_CANON:
        if key in low:
            return canon
    return raw or "?"


def band_of(tb):
    for label, lo, hi in BANDS:
        if lo <= tb < hi:
            return label
    return None


# ---------------------------------------------------------------------------
# explore
# ---------------------------------------------------------------------------
def explore():
    bgn, end = EXPLORE_WINDOW
    print(f"[탐색] 품명(prdctClsfcNoNm) 부분일치 · 등록일 {bgn}~{end}")
    print("       L1은 날짜 범위 없이 조회해 건수가 과소 집계되었으므로 재확인한다.\n")
    report = {}
    for kw in EXPLORE_KEYWORDS:
        tc, items, err = call(prdctClsfcNoNm=kw, inqryBgnDate=bgn, inqryEndDate=end)
        names = Counter(it.get("prdctClsfcNoNm") for it in items)
        mids = Counter(it.get("prdctMidclsfcNm") for it in items)
        report[kw] = {"totalCount": tc, "error": err,
                      "sample_pumyeong": names.most_common(8),
                      "sample_midclass": mids.most_common(4)}
        head = f"  {kw:<8} totalCount={str(tc):<7}"
        print(head + (f" 오류: {err}" if err else ""))
        for nm, c in names.most_common(6):
            print(f"           {c:>3}  {nm}")
        time.sleep(0.5)
    RAW.mkdir(exist_ok=True)
    (RAW / "explore_keywords.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n호출 {CALLS}회")


# ---------------------------------------------------------------------------
# collect
# ---------------------------------------------------------------------------
def collect(pumyeong_list, windows=WINDOWS, raw_name="collect_items.json"):
    """확정된 품명 목록으로 수집한다. 품명은 완전일치로 한 번 더 거른다."""
    rows = []
    for pm in pumyeong_list:
        for bgn, end in windows:
            page, got = 1, 0
            while True:
                tc, items, err = call(prdctClsfcNoNm=pm, inqryBgnDate=bgn,
                                      inqryEndDate=end, pageNo=page)
                if err:
                    print(f"  [오류] {pm} {bgn}~{end} p{page}: {err}")
                    break
                for it in items:
                    if (it.get("prdctClsfcNoNm") or "") == pm:
                        rows.append(it)
                got += len(items)
                if not items or tc is None or got >= tc:
                    break
                page += 1
                time.sleep(0.4)
            print(f"  {pm} {bgn}~{end}: {got}건 조회 (누적 적합 {len(rows)}건)")
    RAW.mkdir(exist_ok=True)
    (RAW / raw_name).write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return rows


def summarize(rows, prefix="g2b", windows=WINDOWS):
    # 1) 파싱
    parsed, fails = [], Counter()
    for it in rows:
        tb, why = parse_capacity_tb(it.get("prdctSpecNm"))
        try:
            amt = float(it.get("cntrctPrceAmt") or 0)
        except (TypeError, ValueError):
            amt = 0.0
        if tb is None:
            fails[why] += 1
            continue
        if amt <= 0:
            fails["가격 없음"] += 1
            continue
        parsed.append({
            "prdctIdntNo": it.get("prdctIdntNo"),
            "pumyeong": it.get("prdctClsfcNoNm"),
            "detail": it.get("dtilPrdctClsfcNoNm"),
            "vendor": norm_vendor(it.get("prdctMakrNm")),
            "vendor_raw": it.get("prdctMakrNm"),
            "contractor": it.get("cntrctCorpNm"),
            "spec": it.get("prdctSpecNm"),
            "unit": it.get("prdctUnit"),
            "price_krw": amt,
            "capacity_tb": tb,
            "krw_per_tb": amt / tb,
            "registered": it.get("rgstDt"),
            "contract_begin": it.get("cntrctBgnDate"),
            "contract_end": it.get("cntrctEndDate"),
        })

    # 2) 중복 제거 — 같은 물품식별번호·같은 가격은 한 건으로 본다.
    #    재등록·계약 갱신으로 동일 제품이 여러 번 잡히면 분포가 한쪽으로 쏠린다.
    seen, uniq = set(), []
    for p in parsed:
        k = (p["prdctIdntNo"] or p["spec"], round(p["price_krw"]))
        if k in seen:
            continue
        seen.add(k)
        uniq.append(p)

    # 3) 구간별 분포
    bands = {}
    for label, _, _ in BANDS:
        vals = sorted(p["krw_per_tb"] for p in uniq if band_of(p["capacity_tb"]) == label)
        bands[label] = {
            "n": len(vals),
            "min": vals[0] if vals else None,
            "median": statistics.median(vals) if vals else None,
            "max": vals[-1] if vals else None,
        }

    summary = {
        "source": "조달청 나라장터쇼핑몰 품목정보 서비스 getShoppingMallPrdctInfoList",
        "pumyeong": sorted({p["pumyeong"] for p in uniq}),
        "windows": windows,
        "rows_total": len(rows),
        "parsed": len(parsed),
        "parse_rate": len(parsed) / len(rows) if rows else 0.0,
        "parse_fail_reasons": dict(fails),
        "unique_after_dedupe": len(uniq),
        "vendors_top": Counter(p["vendor"] for p in uniq).most_common(12),
        "bands": bands,
        "api_calls": CALLS,
    }
    OUT.mkdir(exist_ok=True)
    (OUT / f"{prefix}_bands.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / f"{prefix}_items.json").write_text(
        json.dumps(uniq, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def print_summary(s):
    print(f"\n조회 {s['rows_total']}건 · 용량 파싱 {s['parsed']}건 ({s['parse_rate']*100:.1f}%)"
          f" · 중복 제거 후 {s['unique_after_dedupe']}건")
    for why, c in s["parse_fail_reasons"].items():
        print(f"  파싱 제외 {c:>4}건 — {why}")
    print("\n용량 구간별 원/TB")
    print(f"  {'구간':<10}{'건수':>5}{'최저':>13}{'중앙':>13}{'최고':>14}")
    for label, b in s["bands"].items():
        if b["n"]:
            print(f"  {label:<10}{b['n']:>5}{b['min']:>13,.0f}{b['median']:>13,.0f}{b['max']:>14,.0f}")
        else:
            print(f"  {label:<10}{0:>5}{'-':>13}{'-':>13}{'-':>14}")
    print("\n제조사 상위")
    for v, c in s["vendors_top"]:
        print(f"  {c:>4}  {v}")
    print(f"\n호출 {s['api_calls']}회")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "explore"
    if mode == "explore":
        explore()
    elif mode == "collect":
        pms = sys.argv[2:] or ["하드디스크어레이"]
        print(f"[수집] 품명 {pms} · 기간 {WINDOWS[0][0]}~{WINDOWS[-1][1]}")
        print_summary(summarize(collect(pms)))
    elif mode == "summarize":
        # 저장된 원본으로 집계만 다시 한다. API 호출 없음.
        rows = json.loads((RAW / "collect_items.json").read_text(encoding="utf-8"))
        print(f"[재집계] raw/collect_items.json {len(rows)}건 · API 호출 없음")
        print_summary(summarize(rows))
    elif mode == "reference":
        # 본표에 쓰지 않는 참고 표본. 호출량을 아끼려 한 반기만 조회한다.
        pm = sys.argv[2]
        win = [EXPLORE_WINDOW]
        print(f"[참고 표본] 품명 {pm} · 기간 {win[0][0]}~{win[0][1]} · 본표 미사용")
        rows = collect([pm], windows=win, raw_name=f"ref_{pm}.json")
        print_summary(summarize(rows, prefix=f"ref_{pm}", windows=win))
    else:
        sys.exit("mode: explore | collect [품명 ...] | reference 품명")
