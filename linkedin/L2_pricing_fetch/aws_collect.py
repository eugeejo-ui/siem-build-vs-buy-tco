# -*- coding: utf-8 -*-
"""L2 AWS 수집기 — 서울 리전 디스크 단가를 공식 Price List Bulk API에서 가져온다.

역할
- 비교표의 AWS 금액은 원 모델(`storage_cost()`)을 호출해 산출한다. 원장이 유일한 숫자 출처다.
- 이 수집기는 그 원장 단가가 **현재 공식 가격과 일치하는지 대조**하고,
  원장에 없는 **S3 사용량 구간 단가**를 참고값으로 보존한다.

특징
- 인증 불필요 (Bulk API)
- EC2 오퍼 파일(EBS 포함)은 CSV 202MB. 메모리에 올리지 않고 줄 단위로 읽으며 거른다.
- 원 프로젝트 파일은 읽기만 한다(pricing_loader 호출).
"""
import csv
import io
import json
import pathlib
import sys

import requests

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = HERE / "out"
sys.path.insert(0, str(ROOT / "src"))

S3_URL = ("https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/"
          "AmazonS3/current/ap-northeast-2/index.json")
EC2_CSV_URL = ("https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/"
               "AmazonEC2/current/ap-northeast-2/index.csv")
EBS_VOLUMES = {"gp3", "io2", "sc1", "st1"}
# 같은 의미인데 볼륨마다 표기가 다르다 (io2 만 'GB-month').
STORAGE_UNITS = {"GB-Mo", "GB-month"}


# ---------------------------------------------------------------------------
# S3
# ---------------------------------------------------------------------------
def fetch_s3():
    d = requests.get(S3_URL, timeout=120).json()
    rows = []
    for sku, p in d["products"].items():
        if p.get("productFamily") != "Storage":
            continue
        a = p.get("attributes", {})
        for term in d["terms"].get("OnDemand", {}).get(sku, {}).values():
            for pd in term["priceDimensions"].values():
                if pd.get("unit") != "GB-Mo":
                    continue
                usd = float(pd["pricePerUnit"]["USD"])
                if usd <= 0:
                    continue
                rows.append({
                    "storageClass": a.get("storageClass"),
                    "volumeType": a.get("volumeType"),
                    "usagetype": a.get("usagetype"),
                    "begin_gb": float(pd.get("beginRange") or 0),
                    "end_gb": (None if pd.get("endRange") in (None, "Inf")
                               else float(pd["endRange"])),
                    "usd_per_gb_month": usd,
                    "description": pd.get("description"),
                })
    rows.sort(key=lambda r: (str(r["volumeType"]), r["begin_gb"]))
    return {"version": d.get("version"), "published": d.get("publicationDate"), "rows": rows}


def s3_standard_tiers(s3):
    """S3 Standard(General Purpose) 사용량 구간 단가만 추린다.

    volumeType 'Standard' 이면서 usagetype 이 TimedStorage-ByteHrs 계열인 것.
    """
    tiers = [r for r in s3["rows"]
             if r["volumeType"] == "Standard"
             and (r["usagetype"] or "").endswith("TimedStorage-ByteHrs")]
    # 같은 구간이 중복될 수 있어 시작점 기준으로 1건만 남긴다
    uniq = {}
    for r in tiers:
        uniq.setdefault(r["begin_gb"], r)
    return [uniq[k] for k in sorted(uniq)]


# ---------------------------------------------------------------------------
# EBS (CSV 스트리밍)
# ---------------------------------------------------------------------------
def fetch_ebs():
    r = requests.get(EC2_CSV_URL, stream=True, timeout=300)
    r.raise_for_status()
    meta, header, out = {}, None, []
    scanned = 0
    for i, raw in enumerate(r.iter_lines()):
        line = raw.decode("utf-8")
        if i < 5:
            k, _, v = line.partition(",")
            meta[k.strip('"')] = v.strip('"')
            continue
        if i == 5:
            header = next(csv.reader(io.StringIO(line)))
            idx = {name: header.index(name) for name in (
                "Product Family", "Volume API Name", "Unit", "PricePerUnit",
                "TermType", "usageType", "PriceDescription", "Currency")}
            continue
        scanned += 1
        # 빠른 사전 필터 — 파싱 비용을 줄인다
        if "Storage" not in line or "GB-Mo" not in line:
            continue
        cols = next(csv.reader(io.StringIO(line)))
        if cols[idx["Product Family"]] != "Storage":
            continue
        if cols[idx["TermType"]] != "OnDemand" or cols[idx["Unit"]] != "GB-Mo":
            continue
        vol = cols[idx["Volume API Name"]]
        if vol not in EBS_VOLUMES:
            continue
        out.append({
            "volume": vol,
            "usd_per_gb_month": float(cols[idx["PricePerUnit"]]),
            "currency": cols[idx["Currency"]],
            "usagetype": cols[idx["usageType"]],
            "description": cols[idx["PriceDescription"]],
        })
    r.close()
    uniq = {}
    for row in out:
        uniq.setdefault(row["volume"], row)
    return {"version": meta.get("Version"), "published": meta.get("Publication Date"),
            "rows_scanned": scanned, "volumes": uniq}


# ---------------------------------------------------------------------------
# 원장 대조
# ---------------------------------------------------------------------------
def crosscheck(s3, ebs):
    from pricing_loader import load
    led = load()
    ledger = {
        "ssd_price.base (gp3)": led.get("ssd_price", "base"),
        "ssd_price.high (io2)": led.get("ssd_price", "high"),
        "hdd_price.base (sc1)": led.get("hdd_price", "base"),
        "hdd_price.high (st1)": led.get("hdd_price", "high"),
        "object_price.base (S3 Standard 첫 구간)": led.get("object_price", "base"),
    }
    std = s3_standard_tiers(s3)
    official = {
        "ssd_price.base (gp3)": ebs["volumes"].get("gp3", {}).get("usd_per_gb_month"),
        "ssd_price.high (io2)": ebs["volumes"].get("io2", {}).get("usd_per_gb_month"),
        "hdd_price.base (sc1)": ebs["volumes"].get("sc1", {}).get("usd_per_gb_month"),
        "hdd_price.high (st1)": ebs["volumes"].get("st1", {}).get("usd_per_gb_month"),
        "object_price.base (S3 Standard 첫 구간)": std[0]["usd_per_gb_month"] if std else None,
    }
    result = []
    for k in ledger:
        a, b = ledger[k], official[k]
        result.append({"item": k, "ledger": a, "official": b,
                       "match": (a is not None and b is not None and abs(a - b) < 1e-9)})
    return result, std


def main():
    print("[S3] 서울 리전 JSON 수신")
    s3 = fetch_s3()
    print(f"  version {s3['version']} · 저장 단가 행 {len(s3['rows'])}개")

    print("[EBS] 서울 리전 EC2 CSV 스트리밍 (약 202MB)")
    ebs = fetch_ebs()
    print(f"  version {ebs['version']} · 스캔 {ebs['rows_scanned']:,}줄 · "
          f"추출 {sorted(ebs['volumes'])}")

    checks, std = crosscheck(s3, ebs)
    print("\n[원장 대조] data/pricing.yaml ↔ 공식 Bulk API")
    for c in checks:
        mark = "일치" if c["match"] else "불일치"
        print(f"  {mark:<4} {c['item']:<40} 원장 {c['ledger']} / 공식 {c['official']}")

    print("\n[S3 Standard 사용량 구간] 원장에는 첫 구간 단일값만 있음")
    for t in std:
        end = "∞" if t["end_gb"] is None else f"{t['end_gb']/1024:,.0f}TB"
        print(f"  {t['begin_gb']/1024:>6,.0f}TB ~ {end:<8} ${t['usd_per_gb_month']}")

    OUT.mkdir(exist_ok=True)
    (OUT / "aws_prices.json").write_text(json.dumps({
        "s3": {"version": s3["version"], "published": s3["published"],
               "standard_tiers": std, "all_storage_rows": s3["rows"]},
        "ebs": ebs,
        "ledger_crosscheck": checks,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n저장: out/aws_prices.json")


if __name__ == "__main__":
    main()
