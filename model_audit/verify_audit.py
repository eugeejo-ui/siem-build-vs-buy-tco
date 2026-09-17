# -*- coding: utf-8 -*-
"""
verify_audit.py — V1 재현 확인

audit_calc의 기본 가정(= 원 모델)으로 계산한 결과가 원 모델과 같은지 확인한다.
  1) 연차별 4덩어리(software·storage·build·ops)와 합계 — 원 단위(허용 오차 0.5원)
  2) 대표 손익분기점 — 원 모델 breakeven.find_breakeven과 같은 값

pytest가 자동 수집하지 않도록 test_ 접두어를 쓰지 않는다.
실행: python model_audit/verify_audit.py   (종료 코드 0 = 일치)

[2026-09-16 V6 이후] 원 모델(src/, data/)이 수정되어, 이 스크립트는 **수정 전 트리**에
대고 돌려야 의미가 있습니다. 현행 트리에서는 폐기된 원장 항목(compute_price 등)을 찾다가
중단됩니다. 수정 전 트리를 풀어 AUDIT_MODEL_ROOT로 지정하십시오.

    git archive e61f8f8 src data | tar -x -C <임시 폴더>
    AUDIT_MODEL_ROOT=<임시 폴더> python model_audit/verify_audit.py

수정 후 대조(현행 모델 = 검증값 A)는 verify_fixed.py가 맡습니다.
"""
import itertools
import sys

import audit_calc as ac
import breakeven as be  # audit_calc가 src 경로를 추가한 뒤 import
import cost_model as cm
import tco_engine as te

TOL = 0.5  # 원

GBS = (5, 10, 20, 37, 50, 100, 150, 200)
YEARS = (3, 5)
WHICH = ("low", "base", "high")
GROW = (True, False)


def check_tco(led):
    bad = 0
    n = 0
    for opt, gb, years, which, grow in itertools.product(ac.AUDITED, GBS, YEARS, WHICH, GROW):
        sc = cm.Scenario(daily_gb=gb, years=years, which=which, tiering_ratio=0.7)
        ref = te.compute_tco(opt, sc, led, grow=grow)
        a = ac.Assumptions(grow=grow)
        rows, total = ac.tco(opt, gb, led, which, years, a)
        n += 1
        diffs = []
        for r_ref, r in zip(ref.yearly, rows):
            for k in ("software", "storage", "build", "ops"):
                d = abs(getattr(r_ref, k) - getattr(r, k))
                if d > TOL:
                    diffs.append((r.year, k, getattr(r_ref, k), getattr(r, k)))
        if abs(ref.total - total) > TOL:
            diffs.append(("합계", ref.total, total))
        if diffs:
            bad += 1
            print(f"[불일치] {opt} {gb}GB {years}년 {which} grow={grow}: {diffs[:3]}")
    print(f"TCO 재현: {n}건 중 불일치 {bad}건")
    return bad


def check_breakeven(led):
    bad = 0
    pairs = [(a, b) for a in ac.OPEN for b in (cm.MANAGED_SIEM, cm.SPLUNK, cm.SPLUNK_SMARTSTORE)]
    for (opt_a, opt_b), years, which in itertools.product(pairs, YEARS, WHICH):
        ref = be.find_breakeven(opt_a, opt_b, led, which=which, years=years).crossings
        mine = ac.breakeven(opt_a, opt_b, led, which=which, years=years)
        ok = ref == mine
        bad += 0 if ok else 1
        flag = "" if ok else "  ← 불일치"
        print(f"  {opt_a:20s} vs {opt_b:18s} {years}년 {which:4s}  원 {ref}  재현 {mine}{flag}")
    print(f"손익분기 재현: {len(pairs) * len(YEARS) * len(WHICH)}건 중 불일치 {bad}건")
    return bad


if __name__ == "__main__":
    led = ac.load()
    bad = check_tco(led) + check_breakeven(led)
    sys.exit(1 if bad else 0)
