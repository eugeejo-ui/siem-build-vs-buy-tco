# -*- coding: utf-8 -*-
"""
audit_combo.py — V5 종합: 원 모델값 대 검증값 A·B

검증값 A  : "오류"로 판정한 항목만 모두 고친 값
검증값 B  : A 위에 "가정 선택" 항목을 한쪽으로 몰아 적용한 범위
    B-유리 : 오픈소스에 유리한 쪽 선택
    B-불리 : 오픈소스에 불리한 쪽 선택
참고 경로 : A에서 S3 검색 방식만 바꾼 것(Elastic 무료판 = S3 검색 불가),
           A에서 검색 가능 기간을 Splunk와 같게 맞춘 것(D10)

판정 근거는 model_audit/findings/*.md, 항목 정의는 AUDIT_PLAN.md §4.2.
실행: python model_audit/audit_combo.py → out/combo.json, 표준출력 요약
"""
import json
from dataclasses import replace

import audit_calc as ac
import audit_impact as ai
import cost_model as cm

B0 = ac.BASE
WAGE_2026 = {"security_consultant_annual": ai.KOSA_2026_IT_CONSULTANT_MONTHLY * 12}

# --- 검증값 A: 오류 항목 전부 수정 -------------------------------------------------
A = replace(
    B0,
    # 공통
    capacity_basis="migrate",                          # D1·D2 (기본은 이관 — 원 모델과 가장 가까운 쪽)
    az_transfer_usd_per_gb=ai.inter_az_per_gb(),       # A1
    s3_tier_prices_usd=ai.s3_standard_tiers(),         # D9
    ebs_free_ratio=ai.FREE_ELASTIC,                    # D11 (Elastic 기준)
    # 오픈소스
    os_s3_with_replicas=False,                         # D4
    os_nodes_count_object=False,                       # C1
    os_search_cache_ratio=0.2,                         # S4 (OpenSearch 검색 노드)
    os_search_node_cache_tb=10,
    os_search_node_usd_month=ai.od(ai.OS_NODE),
    os_node_sizing="ratio", os_node_ram_gib=64,        # C2
    os_node_usd_month=ai.od(ai.OS_NODE),
    os_extra_nodes=5, os_extra_usd_month=ai.C3_USD,    # C3
    # Splunk
    sp_license_tiers=ai.SPLUNK_TERM,                   # S1·S3
    sp_rf=3, sp_sf=2, sp_frozen_copies=3,              # D6
    sp_extra_nodes=2, sp_extra_usd_month=ai.C4_USD,    # C4
    sp_indexer_usd_month=ai.od(ai.ES_NODE),            # C5
    sp_admin_fte=0.25,                                 # L1 (오픈소스와 같게)
    sp_build_usd=ai.PS_IMP_BASE,                       # L2
)

RI3 = ai.ri("m6i.2xlarge", "ri_3y_standard_all_upfront") / ai.M6I_2X

B_FAV = replace(A, capacity_basis="new", ec2_price_factor=RI3,
                os_warm_usd_gb_month=ai.WARM_ST1, os_overhead=1.15 * 0.8,
                sp_admin_fte=1.5, sp_build_usd=ai.PS_IMP_STANDARD)
B_UNF = replace(A, capacity_basis="migrate", ec2_price_factor=1.0,
                backup_usd_gb_month=ai.snapshot_standard(), ebs_free_ratio=ai.FREE_AWS,
                sp_admin_fte=0.25, sp_build_usd=ai.PS_IMP_BASE)

A_NOSEARCH = replace(A, os_search_cache_ratio=0.0)     # Elastic 무료판: S3분은 검색 불가 백업
A_D10 = replace(A, os_search_cache_ratio=0.0, tiering_ratio=640 / 730,
                os_warm_usd_gb_month=ai.WARM_ST1)      # 검색 가능 90일로 Splunk와 같게

CASES = [
    ("원 모델", B0, None),
    ("검증 A", A, WAGE_2026),
    ("검증 B-유리", B_FAV, WAGE_2026),
    ("검증 B-불리", B_UNF, WAGE_2026),
    ("참고: A + S3 검색 불가", A_NOSEARCH, WAGE_2026),
    ("참고: A + 검색 90일 대칭", A_D10, WAGE_2026),
]

OPTS = (cm.SELF_HOSTED_TIERED, cm.SELF_HOSTED, cm.SPLUNK)
GBS = (20, 50, 100)
PAIRS = ai.PAIRS
BUCKETS = ("software", "disk", "server", "extra", "build", "ops")


def run(led):
    out = []
    for name, a, ov in CASES:
        lx = led.with_values(ov) if ov else led
        row = {"case": name, "tco": {}, "breakdown": {}, "breakeven": {}, "labor_scenarios": {}}
        for o in OPTS:
            for g in GBS:
                rows, total = ac.tco(o, g, lx, "base", 5, a)
                row["tco"][f"{o}@{g}"] = round(total / 1e6, 1)
                if g == 50:
                    bt = ac.bucket_totals(rows)
                    row["breakdown"][o] = {k: round(v / 1e6, 1) for k, v in bt.items()}
                    row["breakdown"][o]["nodes_by_year"] = [r.nodes for r in rows]
        mg = ac.managed_total(50, lx, "base", 5, a)
        row["tco"]["managed_siem@50"] = round(mg / 1e6, 1)
        for pname, x, y, yrs in PAIRS:
            row["breakeven"][pname] = ac.breakeven_detail(x, y, lx, "base", yrs, a)
        for lab in ("no_ops", "none"):
            al = replace(a, labor=lab)
            row["labor_scenarios"][lab] = {
                pname: ac.breakeven_detail(x, y, lx, "base", yrs, al)
                for pname, x, y, yrs in PAIRS[:3]
            }
        out.append(row)
    return out


if __name__ == "__main__":
    led = ac.load()
    res = run(led)
    (ai.HERE / "out" / "combo.json").write_text(json.dumps(res, ensure_ascii=False, indent=1),
                                                encoding="utf-8")
    for r in res:
        t = r["tco"]
        be = r["breakeven"]
        print(f"\n== {r['case']}")
        print("  5년 총비용(백만원)  티어링 20/50/100:",
              t["self_hosted_tiered@20"], t["self_hosted_tiered@50"], t["self_hosted_tiered@100"],
              "| 로컬 50:", t["self_hosted@50"],
              "| Splunk 20/50/100:", t["splunk@20"], t["splunk@50"], t["splunk@100"],
              "| 관리형 50:", t["managed_siem@50"])
        for o, bd in r["breakdown"].items():
            print(f"  50GB 분해 {ai.SHORT[o]:6s}", bd)
        print("  손익분기  티어링-관리형5y", ai.fmt(be["tiered_vs_managed_5y"]),
              "| 티어링-Splunk5y", ai.fmt(be["tiered_vs_splunk_5y"]),
              "| 티어링-관리형3y", ai.fmt(be["tiered_vs_managed_3y"]),
              "| 로컬-Splunk5y", ai.fmt(be["local_vs_splunk_5y"]))
        for lab, d in r["labor_scenarios"].items():
            print(f"  인건비 {lab:7s}", " | ".join(f"{k} {ai.fmt(v)}" for k, v in d.items()))
