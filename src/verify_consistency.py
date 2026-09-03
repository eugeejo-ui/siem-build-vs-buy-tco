"""
verify_consistency.py — 자기 검증 (Phase 10)

역할
    문서에 적힌 숫자가 코드가 실제로 산출하는 값과 일치하는지 대조한다.

왜 필요한가
    분석 과정에서 값이 여러 번 바뀌었다. 인상률 조정으로 손익분기가 60.2→44.2GB로,
    시뮬레이션 시행 횟수 변경으로 중앙값이 45.0→46.4GB로 이동했다.
    그때마다 관련 문서를 갱신했으나, 사람이 손으로 옮긴 숫자는 누락되기 쉽다.

    특히 위험한 것은 "본문은 갱신했는데 요약이나 권고표는 그대로인" 경우다.
    한 문서 안에서 앞뒤가 어긋나면 읽는 사람이 어느 쪽을 믿어야 할지 알 수 없다.

    이 스크립트는 코드를 실행해 정답을 구한 뒤, 문서에 그 숫자가 실제로
    적혀 있는지 확인한다. 사람의 기억이 아니라 실행 결과를 기준으로 삼는다.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cost_model as cm
import tco_engine as te
import breakeven as be
import sensitivity as sn
from pricing_loader import load

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

results = []   # (구분, 항목, 통과여부, 메시지)


def check(category, name, passed, msg=""):
    results.append((category, name, passed, msg))


def read(path):
    p = ROOT / path if not str(path).startswith("/") else Path(path)
    return p.read_text(encoding="utf-8") if p.exists() else ""


# =============================================================================
# 1. 코드 산출값 vs 문서 기재값
# =============================================================================

def verify_numbers(led):
    print("\n[1] 코드 산출값과 문서 기재값 대조")

    # --- 손익분기점 (5년, base) ---
    bp5 = be.find_breakeven(cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM, led, years=5)
    bp3 = be.find_breakeven(cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM, led, years=3)
    bp_splunk = be.find_breakeven(cm.SELF_HOSTED_TIERED, cm.SPLUNK, led, years=5)

    docs_to_check = {
        "phase05_breakeven.md": [f"{bp5.primary}", f"{bp3.primary}"],
        "phase08a_presales_cisco.md": [f"{bp5.primary}", f"{bp3.primary}"],
    }
    for doc, values in docs_to_check.items():
        text = read(f"docs/{doc}")
        if not text:
            check("수치", f"{doc} 존재", False, "파일 없음")
            continue
        for v in values:
            check("수치", f"{doc}: 손익분기 {v}GB", v in text,
                  f"문서에 '{v}'가 없음")

    # --- 교차 없음 (계층화 미적용) ---
    bp_none = be.find_breakeven(cm.SELF_HOSTED, cm.MANAGED_SIEM, led,
                                tiering_ratio=0.0)
    for doc in ("phase05_breakeven.md", "phase08a_presales_cisco.md",
                "README.md", "README.ko.md"):
        text = read(doc if doc.startswith("README") else f"docs/{doc}")
        has_claim = ("교차 없음" in text or "교차점 없음" in text
                     or "no crossing" in text.lower() or "never won" in text.lower()
                     or "전 구간" in text)
        check("수치", f"{doc}: 교차없음 서술", 
              (bp_none.primary is None) == has_claim,
              "코드는 교차없음인데 문서에 서술이 없거나 그 반대")

    # --- 몬테카를로 (1500회) ---
    mc = sn.monte_carlo(cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM, led, trials=1500)
    lo, hi = mc.interval()
    med = mc.percentiles[50]
    for doc in ("phase06_sensitivity.md", "phase08a_presales_cisco.md"):
        text = read(f"docs/{doc}")
        check("수치", f"{doc}: MC 중앙값 {med}", str(med) in text,
              f"'{med}'가 문서에 없음")
        check("수치", f"{doc}: MC 구간 {lo}~{hi}",
              str(lo) in text and str(hi) in text,
              f"'{lo}' 또는 '{hi}'가 문서에 없음")

    # --- 계층화 효과 (Dell판) ---
    vals = {}
    for r in (0.0, 0.7):
        sc = cm.Scenario(daily_gb=50, years=5, which="base", tiering_ratio=r)
        vals[r] = te.compute_tco(cm.SELF_HOSTED_TIERED, sc, led).total / 1e6
    text = read("docs/phase08b_presales_dell.md")
    for r, v in vals.items():
        s = f"{v:,.0f}"
        check("수치", f"Dell판: 계층화 {int(r*100)}% = {s}백만", s in text,
              f"'{s}'가 문서에 없음")

    # --- 라이선스 비중 ---
    sc = cm.Scenario(daily_gb=50, years=5, which="base")
    r = te.compute_tco(cm.SPLUNK, sc, led)
    share = round(r.bucket_total("software") / r.total * 100)
    check("수치", f"Dell판: 라이선스 비중 {share}%",
          f"{share}%" in read("docs/phase08b_presales_dell.md"),
          f"'{share}%'가 문서에 없음")

    return {"bp5": bp5.primary, "bp3": bp3.primary, "mc_med": med,
            "mc_lo": lo, "mc_hi": hi, "share": share}


# =============================================================================
# 2. 문서 내부 일관성 (같은 문서 안에서 앞뒤가 맞는가)
# =============================================================================

def verify_internal(nums):
    print("[2] 문서 내부 일관성")

    # Cisco판: 요약(1절)의 구간과 4.3절의 구간이 같아야 한다
    text = read("docs/phase08a_presales_cisco.md")
    lo, hi = int(nums["mc_lo"]), int(nums["mc_hi"])
    summary_ok = f"{lo}~{hi}GB" in text or f"{lo}~{hi} GB" in text
    check("일관성", f"Cisco판 요약 구간 {lo}~{hi}GB", summary_ok,
          "요약의 구간이 4.3절과 다름")

    # 권고표 경계가 신뢰구간 하한과 일치해야 한다
    rec_ok = f"{lo}GB 미만" in text
    check("일관성", f"Cisco판 권고 경계 {lo}GB", rec_ok,
          "권고표 경계가 신뢰구간 하한과 불일치")

    # 옛 수치 잔존 확인
    stale = ["45.0 GB", "35.2", "56.1", "60.2 GB", "500/500"]
    for doc in DOCS.glob("phase*.md"):
        t = doc.read_text(encoding="utf-8")
        for s in stale:
            # 조정 경위 서술은 예외
            if s in t and "조정 전" not in t and "최초 500회" not in t:
                check("일관성", f"{doc.name}: 옛 수치 '{s}' 잔존", False,
                      "갱신 누락 가능성")


# =============================================================================
# 3. 링크·경로 무결성
# =============================================================================

def verify_links():
    print("[3] 링크 및 경로 무결성")

    targets = list(DOCS.glob("*.md")) + [ROOT / "README.md", ROOT / "README.ko.md"]
    for f in targets:
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8")
        base = f.parent
        for link in re.findall(r"\]\((?!http)([^)#]+)\)", text):
            target = (base / link).resolve()
            check("링크", f"{f.name} → {link}", target.exists(), "대상 파일 없음")


# =============================================================================
# 4. 원장 상태 점검
# =============================================================================

def verify_ledger(led):
    print("[4] 가격 원장 상태")

    # confirmed/partial 항목은 출처 URL이 있어야 한다 (무료 항목 예외)
    missing = [k for k, _ in led.missing_source() if k != "self_hosted_license"]
    check("원장", "confirmed/partial 출처 URL", not missing,
          f"URL 누락: {missing}")

    # 계산에 실제로 쓰이는 항목이 pending이면 안 된다
    blocked = {k for k, _, _ in led.blocked_items()}
    used_in_calc = {
        "ssd_price", "hdd_price", "object_price", "compute_price",
        "security_consultant_annual", "usd_krw", "splunk_ingest",
        "managed_siem", "splunk_es_uplift", "sizing_tb_per_node_selfhosted",
        "ha_minimum_nodes", "log_retention_days", "log_growth_rate",
        "price_escalation_rate",
    }
    conflict = blocked & used_in_calc
    check("원장", "계산 사용 항목의 가용성", not conflict,
          f"계산에 쓰이는데 pending: {conflict}")

    # assumed 항목은 민감도 대상에 포함되어야 한다
    targets = set(sn.collect_targets(led))
    assumed = {k for k, _, st in led.sensitivity_targets() if st == "assumed"}
    # 스위치형은 제외 대상
    assumed -= sn.EXCLUDED_TARGETS
    # low/high가 없는 항목은 흔들 수 없으므로 제외
    assumed = {k for k in assumed
               if led.item(k).low is not None and led.item(k).high is not None
               and led.item(k).low != led.item(k).high}
    check("원장", "assumed 항목의 민감도 포함", assumed <= targets,
          f"민감도에서 누락: {assumed - targets}")


# =============================================================================
# 5. 작업 원칙 준수
# =============================================================================

def verify_principles(led):
    print("[5] 작업 원칙 준수")

    # 원칙 4: 불리한 결론을 숨기지 않았는가
    for doc, kw in [("phase08a_presales_cisco.md", "교차"),
                    ("phase08b_presales_dell.md", "0.07%")]:
        check("원칙", f"원칙4 불리한 결과 명시 ({doc})",
              kw in read(f"docs/{doc}"), "불리한 결과 서술 누락")

    # 원칙 5: 자사 제품 혼동 금지 — Splunk를 경쟁사로 표현하지 않았는가
    text = read("docs/phase08a_presales_cisco.md")
    check("원칙", "원칙5 Splunk를 경쟁사로 표현하지 않음",
          "경쟁사" not in text, "Splunk를 경쟁사로 서술")

    # 원칙 10: 계산 경로 분리 — 두 경로가 다른 결과를 내는가
    sc = cm.Scenario(daily_gb=50, years=5, which="base")
    a = cm.compute_capacity(cm.SPLUNK, sc, led).total_tb
    b = cm.compute_capacity(cm.SELF_HOSTED, sc, led).total_tb
    check("원칙", "원칙10 Splunk/Elastic 경로 분리", abs(a - b) > 0.1,
          "두 경로가 같은 결과 — 계수 혼용 의심")

    # 원칙 11: 근거 없는 값일수록 범위가 넓은가
    def spread(k):
        it = led.item(k)
        return it.high / it.low if it.low else 0
    check("원칙", "원칙11 탐지룰 범위가 가장 넓음",
          spread("build_effort_detection_rules") >= spread("build_effort_initial"),
          "근거 없는 항목의 범위가 좁음")

    # 원칙 13: 스토리라인 기반 차트 — 배치 안내 문서 존재
    check("원칙", "원칙13 차트 배치 안내 존재",
          (DOCS / "CHART_PLACEMENT.md").exists(), "배치 안내 문서 없음")


# =============================================================================
# 6. 산출물 완결성
# =============================================================================

def verify_deliverables():
    print("[6] 산출물 완결성")

    expected_docs = [
        "phase00_scope.md", "phase01_organization_profile.md",
        "phase02_cost_structure.md", "phase03_pricing_data.md",
        "phase03b_storage_layer.md", "phase04_tco_engine.md",
        "phase05_breakeven.md", "phase06_sensitivity.md",
        "phase07_qualitative.md", "phase08a_presales_cisco.md",
        "phase08b_presales_dell.md", "phase10_verification.md",
    ]
    for d in expected_docs:
        check("산출물", f"문서 {d}", (DOCS / d).exists(), "누락")

    figs = ROOT / "outputs" / "figures"
    for n in range(1, 7):
        for lang in ("ko", "en"):
            matches = list(figs.glob(f"0{n}_*_{lang}.png"))
            check("산출물", f"차트 0{n}_{lang}", len(matches) == 1,
                  f"{len(matches)}개 발견")

    for f in ("README.md", "README.ko.md"):
        check("산출물", f, (ROOT / f).exists(), "누락")

    # 문서 정렬 순서
    names = sorted(d.name for d in DOCS.glob("phase*.md"))
    expected_order = sorted(expected_docs)
    check("산출물", "문서 정렬 순서", names == expected_order,
          f"정렬 불일치: {names}")


# =============================================================================

def main():
    led = load()
    print("=" * 72)
    print("Phase 10 자기 검증")
    print("=" * 72)

    nums = verify_numbers(led)
    verify_internal(nums)
    verify_links()
    verify_ledger(led)
    verify_principles(led)
    verify_deliverables()

    # --- 결과 ---
    print("\n" + "=" * 72)
    failed = [r for r in results if not r[2]]
    by_cat = {}
    for cat, name, ok, msg in results:
        by_cat.setdefault(cat, [0, 0])
        by_cat[cat][0 if ok else 1] += 1

    print(f"{'구분':<10}{'통과':>6}{'실패':>6}")
    print("-" * 72)
    for cat, (ok, ng) in by_cat.items():
        print(f"{cat:<10}{ok:>6}{ng:>6}")
    print("-" * 72)
    print(f"{'합계':<10}{len(results)-len(failed):>6}{len(failed):>6}")

    if failed:
        print("\n[실패 항목]")
        for cat, name, ok, msg in failed:
            print(f"  ✗ [{cat}] {name}")
            if msg:
                print(f"      {msg}")
        return 1
    print("\n전 항목 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
