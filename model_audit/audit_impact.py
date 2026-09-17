# -*- coding: utf-8 -*-
"""
audit_impact.py — V2 영향 측정

점검 항목마다 가정 하나만 바꿔 5년 총비용과 손익분기가 얼마나 움직이는지 잰다.
대안값 중 외부 근거 확인 전인 것은 label에 "(임시)"로 표시한다. V3에서 확정한다.

AWS 단가(인스턴스 요금, 약정 할인, 전송료, 스냅샷, S3 구간)는 out/aws_prices.json
(aws_prices.py 수집 결과)에서 읽는다.

실행: python model_audit/audit_impact.py  → out/impact.json, 표준출력 요약
"""
import json
import sys
from dataclasses import replace
from pathlib import Path

import audit_calc as ac
import cost_model as cm

HERE = Path(__file__).resolve().parent
PRICES = json.loads((HERE / "out" / "aws_prices.json").read_text(encoding="utf-8"))


def od(instance):
    return PRICES["instances"][instance]["prices"]["on_demand"]


def ri(instance, label):
    return PRICES["instances"][instance]["prices"][label]


def ebs(volume):
    for r in PRICES["ebs"]:
        if r["family"] == "Storage" and r["volume"] == volume:
            return r["usd"]
    raise KeyError(volume)


def snapshot_standard():
    for r in PRICES["ebs"]:
        if r["family"] == "Storage Snapshot" and r["unit"] == "GB-Mo" and "snapshot data stored" in r["desc"]:
            return r["usd"]
    raise KeyError("snapshot")


def s3_standard_tiers():
    rows = [r for r in PRICES["s3"]["rows"]
            if r["family"] == "Storage" and r["volumeType"] == "Standard" and r["unit"] == "GB-Mo"]
    rows.sort(key=lambda r: float(r["begin"]))
    bounds = tuple(float(r["end"]) for r in rows[:-1])
    assert bounds == tuple(float(b) for b in ac.S3_TIER_BOUNDS_GB), bounds
    return tuple(r["usd"] for r in rows)


def inter_az_per_gb():
    for r in PRICES["datatransfer"]["rows"]:
        if r["usagetype"] == "APN2-DataTransfer-Regional-Bytes":
            return r["usd"] * 2  # 송신·수신 양쪽 과금
    raise KeyError("inter-az")


B = ac.BASE
# 한국소프트웨어산업협회 「2026년 적용 SW기술자 평균임금」(2025-12-19 공표, 통계승인 제375001호)
# https://www.sw.or.kr/site/sw/ex/board/View.do?cbIdx=304&bcIdx=64717  (확인 2026-09-16)
KOSA_2026_IT_CONSULTANT_MONTHLY = 10_707_960
M6I_2X = od("m6i.2xlarge")
LOCAL_DAYS = 730 * (1 - B.tiering_ratio)     # 티어링 70%일 때 로컬에 남는 일수
HDD_SHARE = (LOCAL_DAYS - 30) / LOCAL_DAYS   # 최근 30일만 SSD, 나머지는 HDD


def _money(s):
    return float(s.replace("$", "").replace(",", ""))


def _band_lo(s):
    return float(s.split()[0])


def splunk_tiers(platform_sku, es_sku):
    """out/splunk_list_tiers.json(G-Cloud 14 Splunk EMEA 목록가 추출)에서 구간표를 만든다."""
    d = json.loads((HERE / "out" / "splunk_list_tiers.json").read_text(encoding="utf-8"))
    plat = {_band_lo(b): _money(p) for b, p in d[platform_sku]}
    es = {_band_lo(b): _money(p) for b, p in d[es_sku]}
    return tuple((lo, plat[lo], es[lo]) for lo in sorted(plat) if lo in es)


SPLUNK_TERM = splunk_tiers("SE-T-LIC-ST", "ES-T-LIC-ST")   # 설치형 1년 약정 + ES 약정
PS_IMP_BASE = 62_900     # Splunk PS 구축 패키지 Base (같은 목록)
PS_IMP_STANDARD = 151_000
ES_NODE = "c6i.8xlarge"  # ES 최소 사양 32 vCPU·32GB RAM을 만족하는 가장 작은 서울 인스턴스(조사 범위 내)
OS_NODE = "r6i.2xlarge"  # 8 vCPU·64GiB — Elastic hot/frozen 참조 구성의 64GB 노드
C3_USD = 3 * od("m6i.large") + od("c6i.2xlarge") + od("c6i.xlarge")
C4_USD = 2 * od(ES_NODE) + 300 * ebs("gp3")   # ES 검색 헤드 1 + 관리 1, 검색 헤드 디스크 300GB
WARM_ST1 = ebs("st1")
FREE_ELASTIC = 1 - 1 / 1.15                  # Elastic 블로그: 워터마크 여유 +15%
FREE_AWS = 1 - 0.95 * 0.8                    # AWS OpenSearch 산식: ÷0.95 ÷0.8

SCENARIOS = [
    ("BASE", "원 모델 그대로", B),
    ("D1", "신규 도입 — 처음엔 비어 있고 실제로 쌓인 만큼 (EBS 연말·S3 연평균)",
     replace(B, capacity_basis="new")),
    ("D2", "기존 2년치 이관 — 과거 로그량을 증가율로 역산 (EBS 연말·S3 연평균)",
     replace(B, capacity_basis="migrate")),
    ("D3", "오픈소스 용량 계수 1.15 → 0.92 (best_compression 약 20% 절감, 무료판 가능)",
     replace(B, os_overhead=1.15 * 0.8)),
    ("D4", "S3분 사본 제외 (스냅샷은 원본 샤드만 담음)", replace(B, os_s3_with_replicas=False)),
    ("D5", f"오픈소스 로컬분 중 최근 30일만 SSD, 나머지는 st1 HDD(${WARM_ST1})",
     replace(B, os_warm_usd_gb_month=WARM_ST1)),
    ("D6a", "Splunk 사본 rf=2·sf=2·아카이브 2벌 (보안 용도 최소)",
     replace(B, sp_rf=2, sp_sf=2, sp_frozen_copies=2)),
    ("D6b", "Splunk 사본 rf=3·sf=2·아카이브 3벌 (기본값·권장)",
     replace(B, sp_rf=3, sp_sf=2, sp_frozen_copies=3)),
    ("D8", f"Splunk cold를 sc1 → st1 (${WARM_ST1})", replace(B, sp_cold_usd_gb_month=WARM_ST1)),
    ("D9", f"S3 구간 체감 {s3_standard_tiers()}", replace(B, s3_tier_prices_usd=s3_standard_tiers())),
    ("D10", "검색 가능 기간을 Splunk와 같게 — 오픈소스 로컬 90일(최근 30일 SSD·60일 HDD), 나머지 640일은 S3에 원본 1벌(검색 불가), 서버는 로컬분 기준",
     replace(B, tiering_ratio=640 / 730, os_local_hdd_share=60 / 90,
             os_s3_with_replicas=False, os_nodes_count_object=False)),
    ("D11a", "EBS 여유 공간 — Elastic 기준(+15%)", replace(B, ebs_free_ratio=FREE_ELASTIC)),
    ("D11b", "EBS 여유 공간 — AWS OpenSearch 산식(÷0.95÷0.8)", replace(B, ebs_free_ratio=FREE_AWS)),
    ("C1", "오픈소스 서버 대수에서 S3분 제외 (S3분 검색 불가 전제)", replace(B, os_nodes_count_object=False)),
    ("C2a", f"15TB/대 유지, 서버를 64GiB {OS_NODE}(${od(OS_NODE)})로",
     replace(B, os_node_usd_month=od(OS_NODE))),
    ("C2b", f"공식 비율(hot 1:30·warm 1:160) — {OS_NODE} 64GiB, S3분은 대수 제외",
     replace(B, os_node_sizing="ratio", os_node_ram_gib=64, os_node_usd_month=od(OS_NODE),
             os_nodes_count_object=False)),
    ("C2c", "공식 비율(hot 1:30·warm 1:160) — 원 모델 m6i.2xlarge 32GiB 유지, S3분은 대수 제외",
     replace(B, os_node_sizing="ratio", os_node_ram_gib=32, os_nodes_count_object=False)),
    ("S4", f"S3분 검색(OpenSearch 검색 노드) — 캐시 20%, 노드당 캐시 10TB, {OS_NODE}; 대수는 로컬분 기준",
     replace(B, os_nodes_count_object=False, os_s3_with_replicas=False,
             os_search_cache_ratio=0.2, os_search_node_cache_tb=10,
             os_search_node_usd_month=od(OS_NODE))),
    ("C3", "오픈소스 전용 서버 — 관리 노드 3(m6i.large)+Wazuh 매니저 1(c6i.2xlarge)+대시보드 1(c6i.xlarge)",
     replace(B, os_extra_nodes=5, os_extra_usd_month=C3_USD)),
    ("C4", f"Splunk 서버 추가 — ES 검색 헤드 1·관리 1({ES_NODE}) + 검색 헤드 디스크 300GB",
     replace(B, sp_extra_nodes=2, sp_extra_usd_month=C4_USD)),
    ("C5", f"Splunk 인덱서를 ES 최소 사양 {ES_NODE}(${od(ES_NODE)})로",
     replace(B, sp_indexer_usd_month=od(ES_NODE))),
    ("C6a", "EC2 1년 약정(선결제 없음)",
     replace(B, ec2_price_factor=ri("m6i.2xlarge", "ri_1y_standard_no_upfront") / M6I_2X)),
    ("C6b", "EC2 3년 약정(전액 선결제)",
     replace(B, ec2_price_factor=ri("m6i.2xlarge", "ri_3y_standard_all_upfront") / M6I_2X)),
    ("A1", f"가용영역 간 복제 전송료 ${inter_az_per_gb()}/GB", replace(B, az_transfer_usd_per_gb=inter_az_per_gb())),
    ("A2", f"로컬 원본 1벌 스냅샷 백업 ${snapshot_standard()}/GB-월",
     replace(B, backup_usd_gb_month=snapshot_standard())),
    ("S1", "Splunk 라이선스를 공개 목록가(설치형 1년 약정 + ES 약정, 구간별)로",
     replace(B, sp_license_tiers=SPLUNK_TERM)),
    ("S2", "Splunk 90일 초과 보관 가산 적용 (Cloud 전용이라 설치형에는 부적용이 맞음 — 참고)",
     replace(B, sp_retention_uplift=True)),
    ("L1a", "Splunk 관리자 0.25명 (오픈소스 클러스터 운영과 같게)", replace(B, sp_admin_fte=0.25)),
    ("L1b", "Splunk 관리자 1.5명 (Splunk Lantern: 기본 1명 + 인덱서 클러스터 0.5명)", replace(B, sp_admin_fte=1.5)),
    ("L2a", f"Splunk 구축 — PS 구축 패키지 Base ${PS_IMP_BASE:,}", replace(B, sp_build_usd=PS_IMP_BASE)),
    ("L2b", f"Splunk 구축 — PS 구축 패키지 Standard ${PS_IMP_STANDARD:,}", replace(B, sp_build_usd=PS_IMP_STANDARD)),
    ("L5", "인건비 단가를 2026년 적용 공표로 (IT컨설턴트 월 10,707,960원 × 12)", B,
     {"security_consultant_annual": KOSA_2026_IT_CONSULTANT_MONTHLY * 12}),
    ("LAB1", "인건비 시나리오 — 운영 인건비 제외", replace(B, labor="no_ops")),
    ("LAB2", "인건비 시나리오 — 인건비 전부 제외", replace(B, labor="none")),
]

GBS = (20, 50, 100)
OPTS = (cm.SELF_HOSTED_TIERED, cm.SELF_HOSTED, cm.SPLUNK)
PAIRS = (
    ("tiered_vs_managed_5y", cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM, 5),
    ("tiered_vs_splunk_5y", cm.SELF_HOSTED_TIERED, cm.SPLUNK, 5),
    ("tiered_vs_managed_3y", cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM, 3),
    ("local_vs_splunk_5y", cm.SELF_HOSTED, cm.SPLUNK, 5),
)


def run(led, scenarios=SCENARIOS):
    base_tot = {(o, g): ac.tco(o, g, led, "base", 5, B)[1] for o in OPTS for g in GBS}
    out = []
    for sc in scenarios:
        sid, label, a = sc[:3]
        overrides = sc[3] if len(sc) > 3 else None
        lx = led.with_values(overrides) if overrides else led
        row = {"id": sid, "label": label, "tco": {}, "delta_pct": {}, "breakeven": {},
               "ledger_overrides": overrides or {}}
        for o in OPTS:
            for g in GBS:
                t = ac.tco(o, g, lx, "base", 5, a)[1]
                row["tco"][f"{o}@{g}"] = round(t / 1e6, 1)
                row["delta_pct"][f"{o}@{g}"] = round((t / base_tot[(o, g)] - 1) * 100, 1)
        for name, x, y, yrs in PAIRS:
            row["breakeven"][name] = ac.breakeven_detail(x, y, lx, "base", yrs, a)
        out.append(row)
    return out


SHORT = {cm.SELF_HOSTED_TIERED: "티어링", cm.SELF_HOSTED: "로컬",
         cm.SPLUNK: "Splunk", cm.MANAGED_SIEM: "관리형"}


def fmt(v):
    if v["crossings"]:
        return "/".join(f"{x:g}" for x in v["crossings"])
    if v["cheaper_at_min"] == v["cheaper_at_max"]:
        return f"없음({SHORT[v['cheaper_at_min']]} 전구간 저렴)"
    return "없음(?)"


if __name__ == "__main__":
    led = ac.load()
    res = run(led)
    (HERE / "out" / "impact.json").write_text(json.dumps(res, ensure_ascii=False, indent=1),
                                              encoding="utf-8")
    hdr = ("ID", "티어링50 Δ%", "로컬50 Δ%", "Splunk50 Δ%", "티어링50 5년 백만원",
           "BE 관리형5y", "BE Splunk5y", "BE 관리형3y", "BE 로컬vsSplunk")
    print(" | ".join(hdr))
    for r in res:
        d = r["delta_pct"]
        be = r["breakeven"]
        print(" | ".join([
            r["id"],
            f"{d['self_hosted_tiered@50']:+.1f}",
            f"{d['self_hosted@50']:+.1f}",
            f"{d['splunk@50']:+.1f}",
            f"{r['tco']['self_hosted_tiered@50']:.0f}",
            fmt(be["tiered_vs_managed_5y"]), fmt(be["tiered_vs_splunk_5y"]),
            fmt(be["tiered_vs_managed_3y"]), fmt(be["local_vs_splunk_5y"]),
        ]) + "   " + r["label"])
    sys.exit(0)
