# -*- coding: utf-8 -*-
"""
verify_fixed.py — V7 수정 후 대조

V6에서 수정한 원 모델(현행 src/ + data/pricing.yaml)이 V5 보고서의 **검증값 A**를
그대로 재현하는지 확인한다.

    기준값 = audit_calc(가정 A) + 수정 전 원장(커밋 e61f8f8) + 2026년 인건비
    대조값 = tco_engine.compute_tco / breakeven.find_breakeven (현행 원장)

  1) 5년·3년 총비용 — base, 로그 증가 반영. 허용 오차 5원
     (두 계산기의 반올림 위치가 한 곳 달라 최대 약 2원 차이가 난다)
  2) 손익분기 6쌍 × 5년·3년 — 교차점 목록 완전 일치

low/high는 대조하지 않는다. 현행 원장은 가정 선택 항목(약정 할인, 압축, Splunk 실계약가
비율 등)의 범위를 새로 가지므로 가정 A의 low/high와 정의가 다르다.

수정 전 원장은 git에서 읽는다(git 필요). pytest가 자동 수집하지 않도록 test_ 접두어를 쓰지 않는다.
실행: python model_audit/verify_fixed.py   (종료 코드 0 = 일치)
"""
import itertools
import subprocess
import sys
import tempfile
from pathlib import Path

import audit_calc as ac
import audit_combo as co
import breakeven as be  # audit_calc가 src 경로를 추가한 뒤 import
import cost_model as cm
import tco_engine as te
from pricing_loader import PricingLedger, load

PRE_V6_COMMIT = "e61f8f8"
TOL = 5.0  # 원
GBS = (5, 10, 20, 37, 50, 100, 150, 200)
YEARS = (3, 5)


def pre_v6_ledger():
    raw = subprocess.run(
        ["git", "show", f"{PRE_V6_COMMIT}:data/pricing.yaml"],
        cwd=ac.ROOT, capture_output=True, check=True,
    ).stdout
    tmp = Path(tempfile.mkdtemp()) / "pricing_pre_v6.yaml"
    tmp.write_bytes(raw)
    return PricingLedger(tmp)


def check_tco(new_led, ref_led):
    bad = n = 0
    worst = 0.0
    for opt, gb, years in itertools.product(ac.AUDITED, GBS, YEARS):
        sc = cm.Scenario(daily_gb=gb, years=years, which="base", tiering_ratio=0.7)
        new = te.compute_tco(opt, sc, new_led).total
        ref = ac.tco(opt, gb, ref_led, "base", years, co.A)[1]
        n += 1
        d = abs(new - ref)
        worst = max(worst, d)
        if d > TOL:
            bad += 1
            print(f"[불일치] {opt} {gb}GB {years}년: 현행 {new:,.0f} / 검증값 A {ref:,.0f}")
    print(f"총비용: {n}건 중 불일치 {bad}건 (최대 차이 {worst:.2f}원)")
    return bad


def check_breakeven(new_led, ref_led):
    bad = n = 0
    pairs = [(a, b) for a in ac.OPEN for b in (cm.MANAGED_SIEM, cm.SPLUNK, cm.SPLUNK_SMARTSTORE)]
    for (opt_a, opt_b), years in itertools.product(pairs, YEARS):
        new = be.find_breakeven(opt_a, opt_b, new_led, years=years).crossings
        ref = ac.breakeven(opt_a, opt_b, ref_led, "base", years, co.A)
        n += 1
        ok = new == ref
        bad += 0 if ok else 1
        flag = "" if ok else "  ← 불일치"
        print(f"  {opt_a:20s} vs {opt_b:18s} {years}년  현행 {new}  검증값 A {ref}{flag}")
    print(f"손익분기: {n}건 중 불일치 {bad}건")
    return bad


if __name__ == "__main__":
    new_led = load()
    ref_led = pre_v6_ledger().with_values(co.WAGE_2026)
    bad = check_tco(new_led, ref_led) + check_breakeven(new_led, ref_led)
    sys.exit(1 if bad else 0)
