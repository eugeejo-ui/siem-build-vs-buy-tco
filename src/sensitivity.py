"""
sensitivity.py — 민감도 분석 (Phase 6)

역할
    Phase 5에서 나온 손익분기점(예: 60.2 GB/day)은 base 가정 하나로 계산한 값이다.
    본 모듈은 그 숫자가 근거 약한 가정값을 흔들었을 때 얼마나 움직이는지 확인한다.

    "60.2GB"라고 확정해 말할 수 있는 숫자인지, 아니면 "45~90GB 어딘가"라고
    말해야 하는 숫자인지가 여기서 갈린다. 프로젝트 원칙 1항(가정값은 범위와
    민감도로 제시)을 실제로 구현하는 단계다.

두 가지 분석
    1. 단변수 민감도 (tornado)
       한 항목만 low↔high로 흔들고 나머지는 base 고정.
       "어느 항목이 결론을 가장 크게 움직이는가"를 순위로 낸다.
       PricingLedger.with_override()가 있어야 항목을 분리해 흔들 수 있다.

    2. 다변수 시뮬레이션 (몬테카를로)
       모든 불확실 항목을 동시에 무작위로 흔들어 수천 번 반복.
       손익분기점의 분포(백분위수)를 낸다.
       단변수는 "한 번에 하나만 틀릴 때"를 보지만, 현실은 여러 값이 동시에
       빗나가므로 결합 효과를 봐야 결론의 실제 불확실성을 알 수 있다.

       ※ 이는 시계열 예측(모델 학습)이 아니라, 이미 정해둔 low~high 범위 안에서
         값을 무작위 추출하는 것이다. 결정론적 모델 원칙(phase00)과 충돌하지 않으며,
         오히려 원칙 1항을 정량적으로 구현한다.

분포 가정
    각 항목의 low~high 범위 안에서 삼각분포를 기본으로 쓴다.
    이유: 최솟값·최댓값·최빈값(base)만 알고 그 사이 형태는 모르는 상황에
    가장 흔히 쓰이는 분포이며, 균등분포보다 base 근처에 무게를 둔다.
    균등분포도 옵션으로 제공한다(가정을 더 보수적으로 두고 싶을 때).
"""

import random
import statistics
from dataclasses import dataclass, field

import cost_model as cm
import breakeven as be


# 손익분기가 없을 때(전 구간 한쪽 우세) 표시할 값
NO_CROSSING = None

# 기본 시뮬레이션 횟수
DEFAULT_TRIALS = 2000

# 환율은 confirmed이지만 범위가 넓고 계약 기간 내내 복리로 작용하므로 포함한다.
EXTRA_TARGETS = ["usd_krw"]

# 흔들면 의미가 없거나 계산이 깨지는 항목은 제외한다.
EXCLUDED_TARGETS = {
    # 0/1 스위치라 연속 분포로 흔들 수 없다. 시나리오 분기로 별도 처리.
    "smartstore_remote_full_search",
}


@dataclass
class TornadoRow:
    """단변수 민감도 한 항목의 결과."""
    key: str
    name: str
    status: str
    low_result: float
    base_result: float
    high_result: float

    @property
    def swing(self):
        """손익분기점이 움직인 폭(GB). 클수록 결론을 크게 흔든다."""
        vals = [v for v in (self.low_result, self.high_result) if v is not None]
        if not vals or self.base_result is None:
            return 0.0
        return round(max(vals) - min(vals), 2)

    @property
    def direction(self):
        """값이 커질 때 손익분기점이 어느 쪽으로 가는가."""
        if self.low_result is None or self.high_result is None:
            return "판정불가"
        if self.high_result > self.low_result:
            return "↑ (자체구축 불리)"
        if self.high_result < self.low_result:
            return "↓ (자체구축 유리)"
        return "영향 없음"


@dataclass
class MonteCarloResult:
    """다변수 시뮬레이션 결과."""
    trials: int
    values: list                  # 각 시행의 손익분기점
    no_crossing_count: int        # 교차가 없었던 시행 수
    percentiles: dict = field(init=False)
    mean: float = field(init=False)
    stdev: float = field(init=False)

    def __post_init__(self):
        vals = sorted(self.values)
        if not vals:
            self.percentiles = {}
            self.mean = 0.0
            self.stdev = 0.0
            return
        self.percentiles = {
            p: round(_percentile(vals, p), 1)
            for p in (5, 10, 25, 50, 75, 90, 95)
        }
        self.mean = round(statistics.fmean(vals), 1)
        self.stdev = round(statistics.pstdev(vals), 1) if len(vals) > 1 else 0.0

    @property
    def valid_trials(self):
        return len(self.values)

    def interval(self, lo=10, hi=90):
        """지정 백분위 구간. 결론을 '이 범위'로 서술할 때 쓴다."""
        if not self.percentiles:
            return None
        return (self.percentiles[lo], self.percentiles[hi])


def _percentile(sorted_vals, p):
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * p / 100.0
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def collect_targets(led, include_extra=True):
    """민감도 분석 대상 목록을 만든다.

    원장의 assumed/unverified 상태에서 자동 추출한 뒤,
    범위가 넓어 영향이 큰 confirmed 항목(환율)을 추가한다.
    사람이 기억에 의존해 목록을 만들면 누락이 생기므로 자동 추출을 기본으로 한다.
    """
    keys = [k for k, _, _ in led.sensitivity_targets()
            if k not in EXCLUDED_TARGETS]
    if include_extra:
        for k in EXTRA_TARGETS:
            if k not in keys:
                keys.append(k)
    # low/high가 모두 있어야 흔들 수 있다
    usable = []
    for k in keys:
        it = led.item(k)
        if it.low is not None and it.high is not None and it.low != it.high:
            usable.append(k)
    return usable


# =============================================================================
# 1. 단변수 민감도 (tornado)
# =============================================================================

def tornado(option_a, option_b, led, years=5, tiering_ratio=0.7,
            include_extra=True):
    """항목을 하나씩만 흔들어 손익분기점 변화를 측정한다.

    Returns
    -------
    list[TornadoRow]  swing 내림차순 정렬
    """
    base_bp = be.find_breakeven(option_a, option_b, led, which="base",
                                years=years, tiering_ratio=tiering_ratio)
    base_val = base_bp.primary

    rows = []
    for key in collect_targets(led, include_extra):
        it = led.item(key)
        results = {}
        for which in ("low", "high"):
            try:
                led_mod = led.with_override(key, which)
                bp = be.find_breakeven(option_a, option_b, led_mod,
                                       which="base", years=years,
                                       tiering_ratio=tiering_ratio)
                results[which] = bp.primary
            except Exception:
                results[which] = None
        rows.append(TornadoRow(
            key=key, name=it.name, status=it.status,
            low_result=results["low"],
            base_result=base_val,
            high_result=results["high"],
        ))

    return sorted(rows, key=lambda r: r.swing, reverse=True)


# =============================================================================
# 2. 다변수 시뮬레이션 (몬테카를로)
# =============================================================================

def _sample(low, base, high, mode, rng):
    """low~high 범위에서 값 하나를 뽑는다."""
    if mode == "uniform":
        return rng.uniform(low, high)
    # 삼각분포: base를 최빈값으로. base가 없거나 범위 밖이면 중앙값 사용.
    mode_val = base if (base is not None and low <= base <= high) else (low + high) / 2
    return rng.triangular(low, high, mode_val)


def monte_carlo(option_a, option_b, led, trials=DEFAULT_TRIALS, years=5,
                tiering_ratio=0.7, dist="triangular", seed=42,
                include_extra=True):
    """모든 불확실 항목을 동시에 흔들어 손익분기점 분포를 낸다.

    Parameters
    ----------
    dist : "triangular" | "uniform"
        삼각분포는 base 근처에 무게를 둔다. 균등분포는 더 보수적(넓은 분포).
    seed : int
        재현 가능성을 위해 고정. 같은 seed면 항상 같은 결과가 나와야 한다.

    Returns
    -------
    MonteCarloResult
    """
    rng = random.Random(seed)
    keys = collect_targets(led, include_extra)
    specs = [(k, led.item(k)) for k in keys]

    values = []
    no_crossing = 0

    for _ in range(trials):
        sampled = {}
        for k, it in specs:
            sampled[k] = _sample(it.low, it.base, it.high, dist, rng)
        try:
            led_mod = led.with_values(sampled)
            bp = be.find_breakeven(option_a, option_b, led_mod, which="base",
                                   years=years, tiering_ratio=tiering_ratio)
            if bp.primary is None:
                no_crossing += 1
            else:
                values.append(bp.primary)
        except Exception:
            no_crossing += 1

    return MonteCarloResult(trials=trials, values=values,
                            no_crossing_count=no_crossing)


# =============================================================================
# 출력 보조
# =============================================================================

def format_tornado(rows, top=None):
    """tornado 결과를 표 문자열로."""
    out = []
    out.append(f"{'항목':34s}{'상태':11s}{'low':>8s}{'base':>8s}{'high':>8s}{'변동폭':>9s}  방향")
    out.append("-" * 96)
    for r in (rows[:top] if top else rows):
        f = lambda v: f"{v:.1f}" if v is not None else "교차없음"
        out.append(f"{r.key:34s}{r.status:11s}{f(r.low_result):>8s}"
                   f"{f(r.base_result):>8s}{f(r.high_result):>8s}"
                   f"{r.swing:>9.1f}  {r.direction}")
    return "\n".join(out)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    from pricing_loader import load

    led = load()
    A, B = cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM

    print("=" * 96)
    print(f"단변수 민감도 (tornado) — {A} vs {B}, 5년")
    print("=" * 96)
    rows = tornado(A, B, led)
    print(format_tornado(rows))

    print("\n" + "=" * 96)
    print("다변수 시뮬레이션 (몬테카를로) — 전 항목 동시 변동")
    print("=" * 96)
    for label, target in [("관리형 SIEM", cm.MANAGED_SIEM),
                          ("Splunk", cm.SPLUNK)]:
        mc = monte_carlo(cm.SELF_HOSTED_TIERED, target, led, trials=500)
        print(f"\n[자체구축+티어링 vs {label}]  유효 시행 {mc.valid_trials}/{mc.trials}"
              f"  (교차없음 {mc.no_crossing_count})")
        if mc.percentiles:
            print(f"  평균 {mc.mean} GB, 표준편차 {mc.stdev}")
            print(f"  중앙값(P50) {mc.percentiles[50]} GB")
            print(f"  80% 구간(P10~P90): {mc.interval()[0]} ~ {mc.interval()[1]} GB")
            print(f"  90% 구간(P5~P95) : {mc.percentiles[5]} ~ {mc.percentiles[95]} GB")
