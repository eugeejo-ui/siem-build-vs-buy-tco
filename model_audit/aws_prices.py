# -*- coding: utf-8 -*-
"""
aws_prices.py — 원 프로젝트 검증용 AWS 서울 리전 단가 수집 (인증 불필요)

출처: AWS Price List Bulk API
  - AmazonEC2  ap-northeast-2 CSV (약 200MB, 줄 단위로 읽으며 거른다)
      인스턴스 온디맨드·예약(1년/3년), EBS 볼륨·스냅샷·gp3 추가 성능, 리전 내 전송
  - AmazonS3   ap-northeast-2 JSON
      Standard 사용량 구간, 요청 요금, 다른 스토리지 클래스
  - AWSDataTransfer ap-northeast-2 JSON (EC2 파일에 리전 내 전송이 없을 때 대비)

결과: model_audit/out/aws_prices.json
원 프로젝트 파일은 건드리지 않는다. 링크드인 코드도 불러 쓰지 않는다.
"""
import csv
import json
import pathlib
import time

import requests

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "out"
BASE = "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws"
EC2_CSV = f"{BASE}/AmazonEC2/current/ap-northeast-2/index.csv"
S3_JSON = f"{BASE}/AmazonS3/current/ap-northeast-2/index.json"
DT_JSON = f"{BASE}/AWSDataTransfer/current/ap-northeast-2/index.json"

FAMILIES = ("m6i", "r6i", "c6i", "m7i", "r7i")
SIZES = ("large", "xlarge", "2xlarge", "4xlarge", "8xlarge")
INSTANCE_TYPES = {f"{f}.{s}" for f in FAMILIES for s in SIZES}
EBS_API = {"gp3", "gp2", "io2", "sc1", "st1"}
HOURS_PER_MONTH = 730  # AWS 요금 페이지의 월 환산 기준


def _get(url, **kw):
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=180, **kw)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(3)


def _lines(resp):
    for raw in resp.iter_lines():
        yield raw.decode("utf-8") if isinstance(raw, bytes) else raw


def fetch_ec2():
    resp = _get(EC2_CSV, stream=True)
    lines = _lines(resp)
    meta = [next(lines) for _ in range(5)]
    reader = csv.reader(lines)
    header = next(reader)
    ix = {h: i for i, h in enumerate(header)}

    def col(row, name):
        i = ix.get(name)
        return row[i] if i is not None and i < len(row) else ""

    inst, ebs, dt = [], [], []
    for row in reader:
        fam = col(row, "Product Family")
        if fam == "Compute Instance":
            it = col(row, "Instance Type")
            if it not in INSTANCE_TYPES:
                continue
            if (col(row, "Tenancy") != "Shared" or col(row, "Operating System") != "Linux"
                    or col(row, "Pre Installed S/W") != "NA"
                    or col(row, "License Model") != "No License required"
                    or col(row, "CapacityStatus") != "Used"
                    or col(row, "operation") != "RunInstances"):
                continue
            inst.append({
                "instance": it,
                "vcpu": col(row, "vCPU"),
                "memory": col(row, "Memory"),
                "term": col(row, "TermType"),
                "lease": col(row, "LeaseContractLength"),
                "purchase": col(row, "PurchaseOption"),
                "class": col(row, "OfferingClass"),
                "unit": col(row, "Unit"),
                "usd": float(col(row, "PricePerUnit") or 0),
                "offer": col(row, "OfferTermCode"),
            })
        elif fam in ("Storage", "Storage Snapshot", "System Operation", "Provisioned Throughput"):
            api = col(row, "Volume API Name")
            if fam == "Storage" and api not in EBS_API:
                continue
            if fam in ("System Operation", "Provisioned Throughput") and api not in ("gp3", "io2"):
                continue
            if col(row, "TermType") != "OnDemand":
                continue
            ebs.append({
                "family": fam, "volume": api, "usagetype": col(row, "usageType"),
                "unit": col(row, "Unit"), "usd": float(col(row, "PricePerUnit") or 0),
                "desc": col(row, "PriceDescription"),
                "begin": col(row, "StartingRange"), "end": col(row, "EndingRange"),
            })
        elif fam == "Data Transfer":
            dt.append({
                "transferType": col(row, "transferType"), "from": col(row, "From Location"),
                "to": col(row, "To Location"), "usagetype": col(row, "usageType"),
                "unit": col(row, "Unit"), "usd": float(col(row, "PricePerUnit") or 0),
                "desc": col(row, "PriceDescription"),
                "begin": col(row, "StartingRange"), "end": col(row, "EndingRange"),
            })
    resp.close()
    return {"meta": meta, "instances": inst, "ebs": ebs, "data_transfer": dt}


def summarize_instances(rows):
    """인스턴스별 월 환산 요금 — 온디맨드와 예약(표준, 1년/3년, 결제 방식별)."""
    out = {}
    offers = {}
    for r in rows:
        key = (r["instance"], r["term"], r["lease"], r["purchase"], r["class"], r["offer"])
        o = offers.setdefault(key, {"hourly": 0.0, "upfront": 0.0,
                                    "vcpu": r["vcpu"], "memory": r["memory"]})
        if r["unit"] == "Hrs":
            o["hourly"] += r["usd"]
        elif r["unit"] == "Quantity":
            o["upfront"] += r["usd"]
    for (it, term, lease, purchase, cls, _), o in offers.items():
        d = out.setdefault(it, {"vcpu": o["vcpu"], "memory": o["memory"], "prices": {}})
        if term == "OnDemand":
            label = "on_demand"
            months = 1
        else:
            years = 3 if lease.startswith("3") else 1
            months = 12 * years
            label = f"ri_{years}y_{cls.lower()}_{purchase.lower().replace(' ', '_')}"
        monthly = o["hourly"] * HOURS_PER_MONTH + (o["upfront"] / months if term != "OnDemand" else 0)
        d["prices"][label] = round(monthly, 2)
    for it, d in out.items():
        od = d["prices"].get("on_demand")
        if od:
            d["discount_vs_on_demand"] = {k: round(1 - v / od, 3)
                                         for k, v in d["prices"].items() if k != "on_demand"}
    return dict(sorted(out.items()))


def fetch_s3():
    d = _get(S3_JSON).json()
    rows = []
    for sku, p in d["products"].items():
        a = p.get("attributes", {})
        fam = p.get("productFamily")
        if fam not in ("Storage", "API Request", "Fee", "Data Transfer"):
            continue
        for term in d["terms"].get("OnDemand", {}).get(sku, {}).values():
            for pd in term["priceDimensions"].values():
                usd = float(pd["pricePerUnit"].get("USD", 0))
                rows.append({
                    "family": fam,
                    "storageClass": a.get("storageClass"),
                    "volumeType": a.get("volumeType"),
                    "group": a.get("group"),
                    "usagetype": a.get("usagetype"),
                    "unit": pd.get("unit"),
                    "begin": pd.get("beginRange"),
                    "end": pd.get("endRange"),
                    "usd": usd,
                    "desc": pd.get("description"),
                })
    return {"version": d.get("version"), "published": d.get("publicationDate"), "rows": rows}


def fetch_datatransfer():
    try:
        d = _get(DT_JSON).json()
    except requests.RequestException as e:
        return {"error": str(e)}
    rows = []
    for sku, p in d["products"].items():
        a = p.get("attributes", {})
        if a.get("transferType") not in ("IntraRegion", "IntraRegion Inbound", "IntraRegion Outbound"):
            continue
        for term in d["terms"].get("OnDemand", {}).get(sku, {}).values():
            for pd in term["priceDimensions"].values():
                rows.append({
                    "transferType": a.get("transferType"),
                    "from": a.get("fromLocation"), "to": a.get("toLocation"),
                    "usagetype": a.get("usagetype"), "unit": pd.get("unit"),
                    "usd": float(pd["pricePerUnit"].get("USD", 0)),
                    "desc": pd.get("description"),
                })
    return {"version": d.get("version"), "published": d.get("publicationDate"), "rows": rows}


def main():
    OUT.mkdir(exist_ok=True)
    t0 = time.time()
    ec2 = fetch_ec2()
    print(f"EC2 CSV: 인스턴스 {len(ec2['instances'])}행, EBS {len(ec2['ebs'])}행, "
          f"전송 {len(ec2['data_transfer'])}행 ({time.time() - t0:.0f}초)")
    s3 = fetch_s3()
    print(f"S3 JSON: {len(s3['rows'])}행 (version {s3['version']})")
    dt = fetch_datatransfer()
    print(f"DataTransfer JSON: {len(dt.get('rows', []))}행 {dt.get('error', '')}")
    result = {
        "retrieved": time.strftime("%Y-%m-%d"),
        "sources": {"ec2_csv": EC2_CSV, "s3_json": S3_JSON, "datatransfer_json": DT_JSON},
        "ec2_meta": ec2["meta"],
        "instances": summarize_instances(ec2["instances"]),
        "ebs": ec2["ebs"],
        "ec2_data_transfer_intra_region": [r for r in ec2["data_transfer"]
                                            if "IntraRegion" in r["transferType"]],
        "s3": {"version": s3["version"], "published": s3["published"],
               "rows": [r for r in s3["rows"] if r["usd"] > 0]},
        "datatransfer": dt,
    }
    (OUT / "aws_prices.json").write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    print("저장:", OUT / "aws_prices.json")


if __name__ == "__main__":
    main()
