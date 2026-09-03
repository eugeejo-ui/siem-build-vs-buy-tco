"""
tco_engine.py — TCO 누적 엔진 (Phase 4)

역할
    cost_model.py가 산출하는 "한 해치 비용"을 계약 기간(3년/5년) 전체로 누적하고,
    선택지들을 나란히 비교한다.

핵심 설계 — 로그량의 연차별 증가
    로그량은 매년 증가한다(IDC Global DataSphere: 기업 데이터 CAGR 23~26%,
    본 프로젝트 가정 20~30%). 이를 반영하는 방식은 두 가지다.
      방식 B (기본): 1년차 daily_gb → 2년차 daily_gb×(1+g) → ... 매년 증가
      방식 A (옵션): 전 기간 daily_gb 고정
    기본을 B로 두는 이유: 로그가 매년 는다는 것은 원장에 확보된 전제이며,
    이를 무시하면 자체구축의 "나중에 용량이 터진다"는 특성이 드러나지 않는다.

    ※ 시계열 예측(모델 학습)은 하지 않는다. 결정론적 모델 원칙(phase00).
      증가율은 원장의 low/base/high 범위를 그대로 곱하는 단순 복리 적용일 뿐이다.

경계
    로그량이 증가해 분석 상한(200 GB/day)을 넘으면 경고를 남긴다.
    상한을 넘은 구간의 계산은 외삽이므로 신뢰도가 떨어진다.
"""

from dataclasses import dataclass, field

import cost_model as cm


ANALYSIS_MAX_GB = 200   # 분석 구간 상한 (phase00)


@dataclass
class TCOResult:
    """한 선택지의 다년 누적 결과."""
    option: str
    years: int
    which: str
    yearly: list                    # 연차별 CostBreakdown
    total: float = field(init=False)
    exceeded_analysis_range: bool = field(init=False, default=False)

    def __post_init__(self):
        self.total = round(sum(b.total for b in self.yearly), 2)

    # 덩어리별 다년 합계 (Phase 5/6에서 항목별 비교에 사용)
    def bucket_total(self, bucket):
        return round(sum(getattr(b, bucket) for b in self.yearly), 2)


def _volume_at_year(base_gb, growth_pct, year, grow):
    """year년차의 로그량. grow=False면 고정."""
    if not grow:
        return base_gb
    g = growth_pct / 100.0
    return base_gb * ((1 + g) ** (year - 1))


def compute_tco(option, sc: cm.Scenario, led, grow=True):
    """한 선택지의 계약 기간 전체 TCO를 누적한다.

    Parameters
    ----------
    option : str
        선택지 식별자 (cost_model.ALL_OPTIONS).
    sc : Scenario
        기준 시나리오. sc.daily_gb는 1년차 로그량, sc.years는 계약 기간.
    led : PricingLedger
    grow : bool
        True(기본)면 로그량을 매년 증가(방식 B), False면 고정(방식 A).

    Returns
    -------
    TCOResult
    """
    growth = led.get("log_growth_rate", sc.which) if grow else 0.0
    exceeded = False
    yearly = []

    for year in range(1, sc.years + 1):
        vol = _volume_at_year(sc.daily_gb, growth, year, grow)
        if vol > ANALYSIS_MAX_GB:
            exceeded = True
        # 그 해의 로그량으로 시나리오를 복제
        year_sc = _with_volume(sc, vol)
        yearly.append(cm.annual_cost(option, year_sc, led, year))

    result = TCOResult(option=option, years=sc.years, which=sc.which, yearly=yearly)
    result.exceeded_analysis_range = exceeded
    return result


def _with_volume(sc: cm.Scenario, new_gb):
    """daily_gb만 바꾼 새 Scenario를 만든다(나머지 파라미터 유지)."""
    from dataclasses import replace
    return replace(sc, daily_gb=new_gb)


def compare(sc: cm.Scenario, led, options=None, grow=True):
    """여러 선택지의 TCO를 한 번에 계산해 딕셔너리로 반환한다.

    계산 불가(원장 빈칸 등) 선택지는 결과에서 제외하고 errors에 사유를 남긴다.
    빈 값을 조용히 0으로 만들지 않는다.
    """
    options = options or cm.ALL_OPTIONS
    results = {}
    errors = {}
    for opt in options:
        try:
            results[opt] = compute_tco(opt, sc, led, grow=grow)
        except Exception as e:
            errors[opt] = f"{type(e).__name__}: {e}"
    return results, errors


def cheapest(results):
    """결과 딕셔너리에서 최저 TCO 선택지를 반환한다."""
    if not results:
        return None
    return min(results.values(), key=lambda r: r.total)


def rank(results):
    """TCO 오름차순 정렬 목록."""
    return sorted(results.values(), key=lambda r: r.total)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    from pricing_loader import load

    led = load()

    print("=" * 70)
    print("TCO 비교 — 5년, base, 로그량 매년 증가(방식 B)")
    print("=" * 70)

    for gb in [10, 20, 50, 100]:
        sc = cm.Scenario(daily_gb=gb, years=5, which="base", tiering_ratio=0.7)
        results, errors = compare(sc, led)
        ranked = rank(results)
        print(f"\n[{gb} GB/day 시작]")
        for r in ranked:
            flag = " ⚠상한초과" if r.exceeded_analysis_range else ""
            print(f"  {r.option:22s} {r.total/1_000_000:>8,.0f} 백만원{flag}")
        if errors:
            for opt, e in errors.items():
                print(f"  {opt:22s} (제외: {e[:40]})")

    print("\n" + "=" * 70)
    print("증가 반영 여부 비교 (50GB/day, 자체구축, 5년)")
    print("=" * 70)
    sc = cm.Scenario(daily_gb=50, years=5, which="base")
    grow_on = compute_tco(cm.SELF_HOSTED, sc, led, grow=True)
    grow_off = compute_tco(cm.SELF_HOSTED, sc, led, grow=False)
    print(f"  증가 반영(B): {grow_on.total/1_000_000:>8,.0f} 백만원")
    print(f"  고정(A)     : {grow_off.total/1_000_000:>8,.0f} 백만원")
    print(f"  차이        : {(grow_on.total-grow_off.total)/1_000_000:>8,.0f} 백만원")
