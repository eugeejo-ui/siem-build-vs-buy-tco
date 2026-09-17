# -*- coding: utf-8 -*-
"""
audit_bep.py — 보고서 §3.6 계산 풀이의 숫자

손익분기를 교과서식 "이익 P = 수익 R − 비용 C"로 풀기 위해, 각 선택지의 5년 총비용을
두 지점을 이은 직선(절편 + 기울기 × 1년차 하루 로그량)으로 근사한다.

    오픈소스 대 상대 선택지
      p  = 상대의 기울기(로그 1GB/day당 상대 5년 비용)       → 오픈소스를 고르면 내지 않게 되는 돈
      v  = 오픈소스의 기울기(로그 1GB/day당 오픈소스 5년 비용)
      FC = 오픈소스 절편 − 상대 절편(로그량과 무관하게 오픈소스가 더 내는 돈)
      P  = (p − v) × Q − FC,  BEP = FC ÷ (p − v)

실제 손익분기는 서버 대수 계단 때문에 직선 근사와 1GB 안팎 다르며,
표의 "실제"는 audit_calc.breakeven(구간 스캔 + 이분 탐색) 값이다.

실행: python model_audit/audit_bep.py
"""
from dataclasses import replace

import audit_calc as ac
import audit_combo as co
import audit_impact as ai
import cost_model as cm

T, L, S, M = cm.SELF_HOSTED_TIERED, cm.SELF_HOSTED, cm.SPLUNK, cm.MANAGED_SIEM


def line(opt, led, a, x1=30, x2=90):
    """두 지점(1년차 하루 로그량 x1, x2)의 5년 총비용을 이은 직선의 (절편, 기울기), 백만원."""
    t1 = ac.tco(opt, x1, led, "base", 5, a)[1] / 1e6
    t2 = ac.tco(opt, x2, led, "base", 5, a)[1] / 1e6
    slope = (t2 - t1) / (x2 - x1)
    return t1 - slope * x1, slope


def bep_row(label, opt, rival, led, a, x1=30, x2=90):
    fo, v = line(opt, led, a, x1, x2)
    fr, p = line(rival, led, a, x1, x2)
    fc = fo - fr
    pv = p - v
    approx = fc / pv
    actual = ac.breakeven(opt, rival, led, "base", 5, a)
    return (f"| {label} | {p:.2f} | {v:.2f} | {pv:.2f} | {fc:.1f} | "
            f"{pv:.2f}×Q − ({fc:.1f}) | {approx:.1f} | {actual or '교차 없음'} |")


def cumulative_steps():
    """원 모델 → 검증값 A, 오픈소스(티어링) 대 관리형에 영향을 주는 수정만 차례로 누적."""
    led = ac.load()
    lw = led.with_values(co.WAGE_2026)
    B = ac.BASE
    a = replace(B, capacity_basis="migrate")
    steps = [("원 모델", B, led), ("+ 인건비 2026년 값", B, lw), ("+ 실제 쌓인 양(이관)", a, lw)]
    a = replace(a, os_s3_with_replicas=False)
    steps.append(("+ S3에는 원본 1벌", a, lw))
    a = replace(a, os_nodes_count_object=False)
    steps.append(("+ 서버 대수에서 S3 용량 제외", a, lw))
    a = replace(a, os_search_cache_ratio=0.2, os_search_node_cache_tb=10,
                os_search_node_usd_month=ai.od(ai.OS_NODE))
    steps.append(("+ S3 검색용 서버", a, lw))
    a = replace(a, os_node_sizing="ratio", os_node_ram_gib=64, os_node_usd_month=ai.od(ai.OS_NODE))
    steps.append(("+ 서버 사양·대수를 공식 비율로", a, lw))
    a = replace(a, os_extra_nodes=5, os_extra_usd_month=ai.C3_USD)
    steps.append(("+ 관리·매니저·대시보드 서버", a, lw))
    a = replace(a, ebs_free_ratio=ai.FREE_ELASTIC)
    steps.append(("+ 디스크 여유 15%", a, lw))
    a = replace(a, az_transfer_usd_per_gb=ai.inter_az_per_gb(), s3_tier_prices_usd=ai.s3_standard_tiers())
    steps.append(("+ 가용영역 전송료, S3 구간 요금", a, lw))
    # 마지막 단계의 오픈소스 가정이 검증값 A와 같아야 한다
    assert all(getattr(a, f) == getattr(co.A, f) for f in a.__dataclass_fields__
               if f.startswith("os_") or f in ("capacity_basis", "ebs_free_ratio",
                                               "az_transfer_usd_per_gb", "s3_tier_prices_usd"))
    for name, aa, lx in steps:
        fo, v = line(T, lx, aa)
        fm, p = line(M, lx, aa)
        fc, pv = fo - fm, p - v
        print(f"| {name} | {fc:.1f} | {pv:.2f} | {fc / pv:.1f} | {ac.breakeven(T, M, lx, 'base', 5, aa)} |")


def check_table():
    led = ac.load()
    fo, v = line(T, led, ac.BASE)
    fm, p = line(M, led, ac.BASE)
    fc = fo - fm
    for q in (20, 45, 60):
        r = p * q
        c = fc + v * q
        real = (ac.tco(M, q, led, "base", 5, ac.BASE)[1] - ac.tco(T, q, led, "base", 5, ac.BASE)[1]) / 1e6
        print(f"| {q}GB | {r:,.0f} | {c:,.0f} | {r - c:+,.0f} | {real:+,.0f} |")


if __name__ == "__main__":
    led = ac.load()
    lw = led.with_values(co.WAGE_2026)
    print("## 손익분기 직선 근사 (p, v, p−v, FC, P, BEP 근사, 실제)")
    print(bep_row("원 모델 · 티어링 대 관리형", T, M, led, ac.BASE))
    print(bep_row("원 모델 · 티어링 대 Splunk", T, S, led, ac.BASE))
    print(bep_row("A · 티어링 대 관리형", T, M, lw, co.A))
    print(bep_row("A · 티어링 대 Splunk", T, S, lw, co.A))
    print(bep_row("A · 로컬 대 Splunk", L, S, lw, co.A, 20, 50))
    print("\n## 원 모델 검산 (Q, R, C, P 근사, 실제 차이)")
    check_table()
    print("\n## 누적 경로 (FC, p−v, BEP 근사, 실제)")
    cumulative_steps()
