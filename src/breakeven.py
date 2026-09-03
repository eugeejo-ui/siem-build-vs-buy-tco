"""
breakeven.py — 손익분기점 산출 (Phase 5)

역할
    Phase 4까지는 "로그량을 넣으면 비용이 나오는" 방향이었다.
    본 모듈은 그 반대로, "두 선택지의 비용이 같아지는 로그량"을 찾는다.

    프로젝트가 답하려는 질문("일일 로그량 몇 GB부터 구매가 유리한가")에
    직접 답하는 단계이며, 최종 산출물의 핵심 숫자가 여기서 나온다.

계산 방법 — 스캔 + 이분탐색 결합
    비용 차이 곡선 d(gb) = TCO_A(gb) - TCO_B(gb) 의 부호가 바뀌는 지점이 손익분기점이다.
    단, 이 곡선은 매끄럽지 않다. cost_model의 노드 수 계산에 올림(ceil)과
    HA 최소 대수(max)가 들어 있어 계단식으로 튀며, 실측 결과 국소 요철도 확인되었다.
    (예: base 시나리오에서 58GB, 63GB, 65GB 부근에서 차이가 일시적으로 반등)

    따라서 이분탐색만 쓰면 요철에 걸려 엉뚱한 지점을 낼 수 있다. 그래서
      1단계 (스캔)     : 전 구간을 일정 간격으로 훑어 부호가 바뀌는 구간을 모두 찾는다.
      2단계 (이분탐색) : 각 구간 안에서만 정밀하게 좁힌다.
    두 단계를 결합해 교차가 여러 번 일어나는 경우도 놓치지 않는다.

비교 쌍 선정 (의도적 취사선택)
    선택지 5종의 모든 조합은 10쌍이나, 손익분기 해석에 의미 있는 쌍만 계산한다.
    자체구축 계열(2) × 상용 계열(3) = 6쌍.
    "자체구축 vs 자체구축+티어링" 같은 동일 진영 내 비교는 손익분기가 아니라
    구성 선택의 문제이므로 제외한다. 이 취사선택은 산출물에 명시해야 한다.
"""

from dataclasses import dataclass

import cost_model as cm
import tco_engine as te


# 분석 구간은 config에서 가져온다(tco_engine과 중복 정의 해소).
# 기존 이름(MIN_GB/MAX_GB)은 외부 참조가 있어 그대로 유지한다.
from config import ANALYSIS_MIN_GB as MIN_GB, ANALYSIS_MAX_GB as MAX_GB

# 스캔 간격 — 좁을수록 요철 포착률이 오르지만 계산량이 늘어난다
SCAN_STEP = 5
# 이분탐색 정밀도 (GB)
TOLERANCE = 0.5
MAX_ITER = 40

SELF_HOSTED_SIDE = [cm.SELF_HOSTED, cm.SELF_HOSTED_TIERED]
COMMERCIAL_SIDE = [cm.MANAGED_SIEM, cm.SPLUNK, cm.SPLUNK_SMARTSTORE]


@dataclass
class BreakevenPoint:
    """한 쌍의 손익분기 결과."""
    option_a: str          # 자체구축 계열
    option_b: str          # 상용 계열
    which: str
    years: int
    crossings: list        # 교차 로그량(GB) 목록. 비어 있으면 전 구간 미교차
    cheaper_at_min: str    # 최소 구간에서 저렴한 쪽
    cheaper_at_max: str    # 최대 구간에서 저렴한 쪽

    @property
    def primary(self):
        """대표 손익분기점. 교차가 없으면 None."""
        return self.crossings[0] if self.crossings else None

    @property
    def multiple_crossings(self):
        """교차가 2회 이상이면 계단 효과로 해석에 주의가 필요하다."""
        return len(self.crossings) > 1


def _diff(gb, option_a, option_b, sc, led, grow):
    """두 선택지의 TCO 차이. 양수면 A가 비싸다."""
    s = te._with_volume(sc, gb)
    a = te.compute_tco(option_a, s, led, grow=grow).total
    b = te.compute_tco(option_b, s, led, grow=grow).total
    return a - b


def _bisect(lo, hi, option_a, option_b, sc, led, grow):
    """[lo, hi] 구간에서 부호가 바뀌는 지점을 이분탐색으로 좁힌다.

    호출 전에 d(lo)와 d(hi)의 부호가 다름이 보장되어야 한다.
    """
    d_lo = _diff(lo, option_a, option_b, sc, led, grow)
    for _ in range(MAX_ITER):
        if hi - lo <= TOLERANCE:
            break
        mid = (lo + hi) / 2
        d_mid = _diff(mid, option_a, option_b, sc, led, grow)
        if d_mid == 0:
            return mid
        if (d_lo < 0) == (d_mid < 0):
            lo, d_lo = mid, d_mid
        else:
            hi = mid
    return round((lo + hi) / 2, 1)


def find_breakeven(option_a, option_b, led, which="base", years=5,
                   grow=True, tiering_ratio=0.7, min_gb=MIN_GB, max_gb=MAX_GB,
                   scan_step=SCAN_STEP):
    """두 선택지의 손익분기점을 찾는다.

    1단계 스캔으로 부호 전환 구간을 모두 찾고, 2단계로 각 구간을 정밀화한다.

    Returns
    -------
    BreakevenPoint
    """
    sc = cm.Scenario(daily_gb=min_gb, years=years, which=which,
                     tiering_ratio=tiering_ratio)

    # --- 1단계: 스캔 ---
    points = []
    gb = min_gb
    samples = []
    while gb <= max_gb:
        samples.append((gb, _diff(gb, option_a, option_b, sc, led, grow)))
        gb += scan_step

    # --- 2단계: 부호 전환 구간마다 이분탐색 ---
    for (g1, d1), (g2, d2) in zip(samples, samples[1:]):
        if d1 == 0:
            points.append(float(g1))
            continue
        if (d1 < 0) != (d2 < 0):
            points.append(_bisect(g1, g2, option_a, option_b, sc, led, grow))

    d_min = samples[0][1]
    d_max = samples[-1][1]
    return BreakevenPoint(
        option_a=option_a,
        option_b=option_b,
        which=which,
        years=years,
        crossings=points,
        cheaper_at_min=option_b if d_min > 0 else option_a,
        cheaper_at_max=option_b if d_max > 0 else option_a,
    )


def find_all(led, which="base", years=5, grow=True, tiering_ratio=0.7):
    """핵심 6쌍(자체구축 계열 × 상용 계열)의 손익분기점을 모두 산출한다.

    계산 불가 쌍은 결과에서 제외하고 errors에 사유를 남긴다.
    """
    results = []
    errors = {}
    for a in SELF_HOSTED_SIDE:
        for b in COMMERCIAL_SIDE:
            try:
                results.append(find_breakeven(a, b, led, which=which,
                                              years=years, grow=grow,
                                              tiering_ratio=tiering_ratio))
            except Exception as e:
                errors[f"{a} vs {b}"] = f"{type(e).__name__}: {e}"
    return results, errors


def breakeven_range(option_a, option_b, led, years=5, grow=True,
                    tiering_ratio=0.7):
    """low/base/high 세 시나리오의 손익분기점을 함께 낸다.

    손익분기점도 단일 숫자가 아니라 범위로 제시해야 한다(작업원칙 1항).
    가정값이 많은 프로젝트에서 단일 지점을 제시하면 확정된 것처럼 오인된다.
    """
    out = {}
    for which in ("low", "base", "high"):
        try:
            bp = find_breakeven(option_a, option_b, led, which=which,
                                years=years, grow=grow,
                                tiering_ratio=tiering_ratio)
            out[which] = bp.primary
        except Exception as e:
            out[which] = None
    return out


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    from pricing_loader import load

    led = load()

    print("=" * 72)
    print("손익분기점 — 5년, base, 로그량 증가 반영, 자체구축 티어링 70%")
    print("=" * 72)
    results, errors = find_all(led)
    for bp in results:
        if bp.primary is None:
            print(f"  {bp.option_a:20s} vs {bp.option_b:20s}  교차 없음 "
                  f"(전 구간 {bp.cheaper_at_min} 우세)")
        else:
            extra = f"  ※ 교차 {len(bp.crossings)}회" if bp.multiple_crossings else ""
            print(f"  {bp.option_a:20s} vs {bp.option_b:20s}  "
                  f"{bp.primary:>6.1f} GB/day{extra}")
            print(f"    → 이하 구간: {bp.cheaper_at_min} 유리 / "
                  f"이상 구간: {bp.cheaper_at_max} 유리")
    for k, e in errors.items():
        print(f"  {k}: 제외 ({e[:50]})")

    print("\n" + "=" * 72)
    print("시나리오별 손익분기 범위 — 자체구축+티어링 vs 관리형 SIEM")
    print("=" * 72)
    rng = breakeven_range(cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM, led)
    for k, v in rng.items():
        print(f"  {k:>5s}: {v if v is not None else '교차 없음'}")
