"""
make_charts.py — 제안서용 차트 생성 (Phase 9)

역할
    Phase 8 제안서 2종(Cisco판/Dell판)의 서술에서 "숫자만으로는 와닿지 않는 지점"에
    들어갈 차트를 생성한다. 차트는 6종이며, 각각 국문·영문 두 버전을 만든다.

설계 원칙
    1. 데이터는 계산 모듈에서 직접 가져온다.
       문서에 적힌 숫자를 손으로 옮기면 오차가 생기고, 원장이 바뀌어도 반영되지 않는다.
    2. 국문/영문 버전은 라벨만 다르고 데이터는 완전히 동일하다.
       한 벌의 데이터로 두 번 그린다.
    3. 각 차트는 제안서의 특정 절에 대응한다. 대응 관계를 파일명과 캡션에 남긴다.

산출물
    outputs/figures/ 아래에 PNG 12개.
"""

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cost_model as cm
import tco_engine as te
import breakeven as be
import sensitivity as sn
from pricing_loader import load


# --- 출력 경로 ----------------------------------------------------------------
OUT = Path(__file__).resolve().parent.parent / "outputs" / "figures"
OUT.mkdir(parents=True, exist_ok=True)

# --- 폰트 --------------------------------------------------------------------
# 한글이 깨지면 차트가 무용지물이 되므로 폰트를 명시적으로 지정한다.
#
# [환경 독립성] 하나의 폰트만 지정하면 그 폰트가 없는 환경에서 글자가 네모(□)로
# 깨진다. 실제로 Noto 폰트가 없는 로컬에서 실행했을 때 이 문제가 발생했다.
# 그래서 한글 폰트 후보를 우선순위대로 나열하고, 설치된 것 중 첫 번째를 쓴다.
#   - Malgun Gothic : Windows 기본 (로컬 실행 대비)
#   - AppleGothic   : macOS 기본
#   - Noto Sans CJK : Linux/CI 환경
#   - NanumGothic   : 리눅스에서 흔히 설치되는 한글 폰트
import matplotlib.font_manager as fm

KO_FONT_CANDIDATES = [
    "Malgun Gothic", "AppleGothic",
    "Noto Sans CJK KR", "Noto Sans CJK JP", "Noto Sans KR",
    "NanumGothic", "NanumBarunGothic", "UnDotum",
]
EN_FONT = "DejaVu Sans"


def _resolve_ko_font():
    """설치된 폰트 중 첫 번째 한글 폰트를 찾는다. 없으면 경고하고 기본값 사용."""
    installed = {f.name for f in fm.fontManager.ttflist}
    for name in KO_FONT_CANDIDATES:
        if name in installed:
            return name
    print("  [경고] 한글 폰트를 찾지 못했습니다. 한글이 깨질 수 있습니다.")
    print(f"         시도한 후보: {', '.join(KO_FONT_CANDIDATES)}")
    return EN_FONT


KO_FONT = _resolve_ko_font()

plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.dpi"] = 110
plt.rcParams["savefig.bbox"] = "tight"
plt.rcParams["axes.grid"] = True
plt.rcParams["grid.alpha"] = 0.3

# --- 색상 (선택지별 고정) -------------------------------------------------------
# 같은 선택지는 모든 차트에서 같은 색을 쓴다. 차트 간 대조가 쉬워진다.
COLORS = {
    cm.SELF_HOSTED:        "#C0392B",   # 자체구축(계층화 없음) — 경고색
    cm.SELF_HOSTED_TIERED: "#E67E22",   # 자체구축(계층화)
    cm.MANAGED_SIEM:       "#2E86C1",   # 관리형 SIEM
    cm.SPLUNK:             "#27AE60",   # Splunk
    cm.SPLUNK_SMARTSTORE:  "#16A085",   # Splunk + SmartStore
}

LABELS = {
    "ko": {
        cm.SELF_HOSTED:        "자체 구축 (계층화 없음)",
        cm.SELF_HOSTED_TIERED: "자체 구축 (계층화 70%)",
        cm.MANAGED_SIEM:       "관리형 SIEM",
        cm.SPLUNK:             "Splunk",
        cm.SPLUNK_SMARTSTORE:  "Splunk + SmartStore",
    },
    "en": {
        cm.SELF_HOSTED:        "Self-hosted (no tiering)",
        cm.SELF_HOSTED_TIERED: "Self-hosted (70% tiered)",
        cm.MANAGED_SIEM:       "Managed SIEM",
        cm.SPLUNK:             "Splunk",
        cm.SPLUNK_SMARTSTORE:  "Splunk + SmartStore",
    },
}


def _font(lang):
    return KO_FONT if lang == "ko" else EN_FONT


def _setup(lang):
    plt.rcParams["font.family"] = _font(lang)


def _save(fig, name, lang):
    path = OUT / f"{name}_{lang}.png"
    fig.savefig(path)
    plt.close(fig)
    print(f"  saved: {path.name}")


# =============================================================================
# 차트 1 — 선택지별 5년 TCO vs 일일 로그량
#   대응: Cisco판 4.1 / 4.2절
#   메시지: 계층화 없는 자체구축(빨간 선)은 어떤 지점에서도 최저가 아니다
# =============================================================================

def chart1_tco_curves(led, lang):
    _setup(lang)
    L = LABELS[lang]
    gbs = list(range(10, 121, 5))

    series = {}
    for opt in cm.ALL_OPTIONS:
        vals = []
        for gb in gbs:
            sc = cm.Scenario(
                daily_gb=gb, years=5, which="base",
                tiering_ratio=0.7 if opt == cm.SELF_HOSTED_TIERED else 0.0,
            )
            vals.append(te.compute_tco(opt, sc, led).total / 1e8)  # 억원
        series[opt] = vals

    fig, ax = plt.subplots(figsize=(9, 5.5))
    for opt, vals in series.items():
        # 계층화 없는 자체구축을 굵게 — 이 차트의 메시지가 그 선이기 때문
        lw = 2.8 if opt == cm.SELF_HOSTED else 1.9
        # Splunk와 SmartStore는 값이 거의 같아 선이 겹친다.
        # 실제로 차이가 작다는 것이 사실이므로 값을 왜곡하지 않고,
        # 점선으로 표시해 두 선이 존재함을 알 수 있게 한다.
        ls = "--" if opt == cm.SPLUNK_SMARTSTORE else "-"
        ax.plot(gbs, vals, label=L[opt], color=COLORS[opt],
                linewidth=lw, linestyle=ls)

    # 손익분기점 표시
    bp = be.find_breakeven(cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM, led)
    if bp.primary:
        ax.axvline(bp.primary, color="gray", linestyle="--", linewidth=1.2)
        ax.annotate(
            (f"손익분기 {bp.primary:.1f} GB" if lang == "ko"
             else f"Break-even {bp.primary:.1f} GB"),
            xy=(bp.primary, max(series[cm.SELF_HOSTED]) * 0.55),
            xytext=(bp.primary + 8, max(series[cm.SELF_HOSTED]) * 0.62),
            fontsize=9, color="gray",
            arrowprops=dict(arrowstyle="->", color="gray", lw=1),
        )

    # 중점 구간 음영
    ax.axvspan(20, 50, alpha=0.07, color="navy")
    # 손익분기 수직선과 겹치지 않도록 구간 왼쪽에 배치한다
    ax.text(22, ax.get_ylim()[1] * 0.04,
            "중점 검토 구간" if lang == "ko" else "Focus range",
            ha="left", fontsize=8.5, color="navy")

    if lang == "ko":
        ax.set_title("일일 로그량에 따른 5년 총소유비용", fontsize=14, pad=12)
        ax.set_xlabel("일일 로그량 (GB/day)")
        ax.set_ylabel("5년 총소유비용 (억원)")
    else:
        ax.set_title("5-Year TCO by Daily Log Volume", fontsize=14, pad=12)
        ax.set_xlabel("Daily Log Volume (GB/day)")
        ax.set_ylabel("5-Year TCO (100M KRW)")

    ax.legend(fontsize=9, loc="upper left")
    ax.set_xlim(10, 120)
    _save(fig, "01_tco_curves", lang)


# =============================================================================
# 차트 2 — 손익분기점 분포 (몬테카를로)
#   대응: Cisco판 4.3절
#   메시지: 44.2GB는 단일 숫자가 아니라 35~56GB 구간이다
# =============================================================================

def chart2_breakeven_distribution(led, lang, mc=None):
    _setup(lang)
    mc = mc or sn.monte_carlo(cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM,
                              led, trials=1500)

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.hist(mc.values, bins=35, color="#5499C7", edgecolor="white", alpha=0.85)

    p10, p90 = mc.interval()
    p50 = mc.percentiles[50]

    ax.axvspan(p10, p90, alpha=0.12, color="#2E86C1")
    ax.axvline(p50, color="#C0392B", linewidth=2)

    ax.annotate(
        (f"중앙값 {p50:.1f} GB" if lang == "ko" else f"Median {p50:.1f} GB"),
        xy=(p50, ax.get_ylim()[1] * 0.9),
        xytext=(p50 + 4, ax.get_ylim()[1] * 0.9),
        fontsize=10, color="#C0392B", fontweight="bold",
    )
    ax.text(
        (p10 + p90) / 2, ax.get_ylim()[1] * 0.05,
        (f"80% 구간  {p10:.1f} ~ {p90:.1f} GB" if lang == "ko"
         else f"80% interval  {p10:.1f} - {p90:.1f} GB"),
        ha="center", fontsize=9.5, color="#1A5276",
    )

    if lang == "ko":
        ax.set_title("손익분기점의 불확실성 — 가정값 동시 변동 시뮬레이션",
                     fontsize=14, pad=12)
        ax.set_xlabel("손익분기점 (GB/day)")
        ax.set_ylabel("시행 횟수")
        note = f"자체 구축(계층화) vs 관리형 SIEM · 5년 · {mc.valid_trials:,}회 시행"
    else:
        ax.set_title("Break-even Uncertainty — Monte Carlo Simulation",
                     fontsize=14, pad=12)
        ax.set_xlabel("Break-even Point (GB/day)")
        ax.set_ylabel("Frequency")
        note = f"Self-hosted (tiered) vs Managed SIEM · 5yr · {mc.valid_trials:,} trials"

    fig.text(0.5, -0.02, note, ha="center", fontsize=9, color="#555")
    _save(fig, "02_breakeven_distribution", lang)


# =============================================================================
# 차트 3 — 단변수 민감도 (tornado)
#   대응: Cisco판 4.4절
#   메시지: 결론을 가장 크게 흔드는 것은 소프트웨어 인상률이다
# =============================================================================

TORNADO_NAMES = {
    "ko": {
        "price_escalation_rate": "소프트웨어 연간 인상률",
        "build_effort_detection_rules": "탐지 규칙 개발 공수",
        "build_effort_initial": "초기 구축 공수",
        "build_effort_learning": "학습 기간 공수",
        "usd_krw": "환율",
        "smartstore_cache_days": "SmartStore 캐시 보존일",
        "splunk_ingest": "Splunk 수집 단가",
        "ops_effort_isms": "ISMS 대응 공수",
    },
    "en": {
        "price_escalation_rate": "SW annual price escalation",
        "build_effort_detection_rules": "Detection rule development",
        "build_effort_initial": "Initial build effort",
        "build_effort_learning": "Learning curve effort",
        "usd_krw": "Exchange rate",
        "smartstore_cache_days": "SmartStore cache days",
        "splunk_ingest": "Splunk ingest price",
        "ops_effort_isms": "ISMS compliance effort",
    },
}


def chart3_tornado(led, lang, rows=None):
    _setup(lang)
    rows = rows or sn.tornado(cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM, led)
    rows = [r for r in rows if r.swing > 0]
    rows = list(reversed(rows))  # 아래에서 위로 커지도록

    base = rows[0].base_result
    names = [TORNADO_NAMES[lang].get(r.key, r.key) for r in rows]
    lows = [r.low_result - base for r in rows]
    highs = [r.high_result - base for r in rows]

    fig, ax = plt.subplots(figsize=(9.5, 5))
    y = range(len(rows))
    # [주의] "낙관/비관"으로 표기하면 안 된다. 항목마다 방향이 반대이기 때문이다.
    #   인상률이 낮으면(low) 손익분기가 높아져 자체구축에 불리하고,
    #   공수가 낮으면(low) 손익분기가 낮아져 자체구축에 유리하다.
    # 따라서 값의 크기만 중립적으로 표기한다.
    ax.barh(y, lows, color="#5DADE2", edgecolor="white",
            label=("가정값을 하한(low)으로" if lang == "ko"
                   else "Assumption at low"))
    ax.barh(y, highs, color="#EC7063", edgecolor="white",
            label=("가정값을 상한(high)으로" if lang == "ko"
                   else "Assumption at high"))

    ax.axvline(0, color="black", linewidth=1.1)
    ax.set_yticks(list(y))
    ax.set_yticklabels(names, fontsize=9.5)

    for i, r in enumerate(rows):
        ax.text(max(lows[i], highs[i]) + 0.6, i, f"±{r.swing:.1f}",
                va="center", fontsize=8.5, color="#444")

    if lang == "ko":
        ax.set_title(f"결론을 흔드는 요인 순위 (기준 손익분기 {base:.1f} GB)",
                     fontsize=14, pad=12)
        ax.set_xlabel("손익분기점 변동 (GB/day)")
    else:
        ax.set_title(f"Sensitivity Ranking (base break-even {base:.1f} GB)",
                     fontsize=14, pad=12)
        ax.set_xlabel("Break-even Shift (GB/day)")

    ax.legend(fontsize=9, loc="lower right")
    ax.grid(axis="y", alpha=0)
    _save(fig, "03_tornado", lang)


# =============================================================================
# 차트 4 — 저장 계층 간 단가 격차
#   대응: Dell판 4.1절
#   메시지: 최고 계층과 최저 계층의 단가가 64배 차이난다
# =============================================================================

TIERS = [
    ("io2",              0.1278, "#8E44AD"),
    ("gp3",              0.0912, "#9B59B6"),
    ("S3 Standard",      0.025,  "#2E86C1"),
    ("sc1",              0.0174, "#5DADE2"),
    ("S3 Standard-IA",   0.0138, "#48C9B0"),
    ("Glacier Instant",  0.005,  "#7DCEA0"),
    ("Deep Archive",     0.002,  "#A9DFBF"),
]

TIER_DESC = {
    "ko": ["고성능 (고IOPS)", "고성능 (범용)", "오브젝트 (표준)", "일반 디스크",
           "오브젝트 (저빈도)", "아카이브 (즉시조회)", "아카이브 (최저가)"],
    "en": ["High perf (high IOPS)", "High perf (general)", "Object (standard)",
           "General disk", "Object (infrequent)", "Archive (instant)",
           "Archive (lowest cost)"],
}


def chart4_tier_price_gap(lang):
    _setup(lang)
    names = [f"{t[0]}\n{d}" for t, d in zip(TIERS, TIER_DESC[lang])]
    prices = [t[1] for t in TIERS]
    colors = [t[2] for t in TIERS]
    lowest = min(prices)

    fig, ax = plt.subplots(figsize=(10, 5.5))
    bars = ax.bar(names, prices, color=colors, edgecolor="white")

    for b, p in zip(bars, prices):
        ax.text(b.get_x() + b.get_width() / 2, p + 0.003,
                f"${p:.4f}\n({p/lowest:.0f}x)", ha="center",
                fontsize=8.5, color="#333")

    if lang == "ko":
        ax.set_title("저장 계층 간 단가 격차 — 최대 64배 (서울 리전)",
                     fontsize=14, pad=12)
        ax.set_ylabel("단가 (USD / GB / 월)")
    else:
        ax.set_title("Storage Tier Price Gap — Up to 64x (Seoul region)",
                     fontsize=14, pad=12)
        ax.set_ylabel("Unit Price (USD / GB / month)")

    ax.tick_params(axis="x", labelsize=8.5)
    ax.set_ylim(0, max(prices) * 1.25)
    ax.grid(axis="x", alpha=0)
    _save(fig, "04_tier_price_gap", lang)


# =============================================================================
# 차트 5 — 계층화 비율별 총비용 변화
#   대응: Dell판 4.2절
#   메시지: 계층화 비율을 높일수록 비용이 내려가며, 로그량이 클수록 효과가 크다
# =============================================================================

def chart5_tiering_effect(led, lang):
    _setup(lang)
    ratios = [0.0, 0.3, 0.5, 0.7, 0.9]
    volumes = [20, 30, 50, 100]
    palette = ["#AED6F1", "#5DADE2", "#2E86C1", "#1A5276"]

    fig, ax = plt.subplots(figsize=(9, 5.5))
    for vol, color in zip(volumes, palette):
        vals = []
        for r in ratios:
            sc = cm.Scenario(daily_gb=vol, years=5, which="base", tiering_ratio=r)
            vals.append(te.compute_tco(cm.SELF_HOSTED_TIERED, sc, led).total / 1e8)
        label = f"{vol} GB/day"
        ax.plot([r * 100 for r in ratios], vals, marker="o",
                color=color, linewidth=2, label=label)
        # 절감률 주석 (0% 대비 90%)
        drop = (vals[0] - vals[-1]) / vals[0] * 100
        ax.annotate(f"-{drop:.0f}%", xy=(90, vals[-1]),
                    xytext=(92, vals[-1]), fontsize=9, color=color,
                    fontweight="bold", va="center")

    if lang == "ko":
        ax.set_title("계층화 비율에 따른 5년 총소유비용 변화 (자체 구축)",
                     fontsize=14, pad=12)
        ax.set_xlabel("오브젝트 스토리지 계층화 비율 (%)")
        ax.set_ylabel("5년 총소유비용 (억원)")
        ax.legend(fontsize=9, title="일일 로그량")
    else:
        ax.set_title("5-Year TCO by Tiering Ratio (Self-hosted)",
                     fontsize=14, pad=12)
        ax.set_xlabel("Object Storage Tiering Ratio (%)")
        ax.set_ylabel("5-Year TCO (100M KRW)")
        ax.legend(fontsize=9, title="Daily volume")

    ax.set_xlim(-5, 102)
    _save(fig, "05_tiering_effect", lang)


# =============================================================================
# 차트 6 — 비용 구성 분해 (라이선스 지배)
#   대응: Dell판 5.1절
#   메시지: 상용 제품은 라이선스가 87%라 저장 최적화 효과가 총액에서 안 보인다
# =============================================================================

def chart6_cost_breakdown(led, lang):
    _setup(lang)
    sc = cm.Scenario(daily_gb=50, years=5, which="base")
    targets = [cm.SPLUNK, cm.SPLUNK_SMARTSTORE, cm.SELF_HOSTED_TIERED]

    data = {}
    growth = led.get("log_growth_rate", "base")
    for opt in targets:
        s = cm.Scenario(daily_gb=50, years=5, which="base",
                        tiering_ratio=0.7 if opt == cm.SELF_HOSTED_TIERED else 0.0)
        r = te.compute_tco(opt, s, led)

        # [주의] 저장·컴퓨트를 "1년치 x 연수"로 계산하면 안 된다.
        # 로그량이 매년 증가하므로 연차별로 각각 산출해 누적해야 한다.
        # (1년치 x 5로 계산하면 자체구축에서 약 3억원이 과소 산정된다)
        storage_only = 0.0
        compute_only = 0.0
        for year in range(1, s.years + 1):
            vol = te._volume_at_year(s.daily_gb, growth, year, True)
            ys = te._with_volume(s, vol)
            cap = cm.compute_capacity(opt, ys, led)
            storage_only += cm.storage_cost(opt, ys, led, cap)
            compute_only += cm.compute_cost(opt, ys, led, cap)

        data[opt] = {
            "sw": r.bucket_total("software") / 1e8,
            "storage": storage_only / 1e8,
            "compute": compute_only / 1e8,
            "build": r.bucket_total("build") / 1e8,
            "ops": r.bucket_total("ops") / 1e8,
            "total": r.total / 1e8,
        }
        # 덩어리 합이 총액과 일치하는지 검증한다. 어긋나면 그래프가 거짓말을 한다.
        parts = sum(data[opt][k] for k in ("sw", "storage", "compute", "build", "ops"))
        assert abs(parts - data[opt]["total"]) < 0.05, (
            f"{opt}: 덩어리 합({parts:.2f})과 총액({data[opt]['total']:.2f}) 불일치")

    if lang == "ko":
        keys = [("sw", "소프트웨어 라이선스", "#C0392B"),
                ("storage", "저장 비용", "#F39C12"),
                ("compute", "컴퓨트", "#2E86C1"),
                ("build", "구축 인건비", "#8E44AD"),
                ("ops", "운영 인건비", "#16A085")]
        names = [LABELS["ko"][o] for o in targets]
    else:
        keys = [("sw", "Software license", "#C0392B"),
                ("storage", "Storage", "#F39C12"),
                ("compute", "Compute", "#2E86C1"),
                ("build", "Build labor", "#8E44AD"),
                ("ops", "Ops labor", "#16A085")]
        names = [LABELS["en"][o] for o in targets]

    fig, ax = plt.subplots(figsize=(9.5, 5.5))
    bottoms = [0.0] * len(targets)
    for k, label, color in keys:
        vals = [data[o][k] for o in targets]
        ax.bar(names, vals, bottom=bottoms, label=label, color=color,
               edgecolor="white", width=0.55)
        bottoms = [b + v for b, v in zip(bottoms, vals)]

    # 라이선스 비중 주석
    for i, opt in enumerate(targets):
        share = data[opt]["sw"] / data[opt]["total"] * 100
        if share > 1:
            ax.text(i, data[opt]["sw"] / 2,
                    f"{share:.0f}%", ha="center", va="center",
                    fontsize=11, color="white", fontweight="bold")
        ax.text(i, data[opt]["total"] + 0.3,
                f"{data[opt]['total']:.1f}", ha="center",
                fontsize=9.5, color="#333")

    # 저장 비용 차이 강조
    diff = abs(data[cm.SPLUNK]["storage"] - data[cm.SPLUNK_SMARTSTORE]["storage"])
    note = (f"Splunk 계열의 저장 비용 차이는 {diff:.2f}억원으로 총액의 0.1% 미만입니다"
            if lang == "ko" else
            f"Storage cost difference in Splunk options: {diff:.2f} (under 0.1% of total)")

    if lang == "ko":
        ax.set_title("비용 구성 분해 — 라이선스가 총액을 지배합니다 (50GB/day, 5년)",
                     fontsize=13.5, pad=12)
        ax.set_ylabel("5년 총소유비용 (억원)")
    else:
        ax.set_title("Cost Breakdown — License Dominates Total (50GB/day, 5yr)",
                     fontsize=13.5, pad=12)
        ax.set_ylabel("5-Year TCO (100M KRW)")

    ax.legend(fontsize=9, loc="upper right", framealpha=0.95)
    ax.tick_params(axis="x", labelsize=9)
    ax.grid(axis="x", alpha=0)
    ax.set_ylim(0, max(d["total"] for d in data.values()) * 1.15)
    fig.text(0.5, -0.03, note, ha="center", fontsize=9, color="#555")
    _save(fig, "06_cost_breakdown", lang)


# =============================================================================

def main():
    led = load()
    print(f"출력 경로: {OUT}")

    # 비용이 큰 계산은 한 번만 수행해 두 언어가 공유한다
    print("\n[사전 계산]")
    mc = sn.monte_carlo(cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM, led, trials=1500)
    print(f"  몬테카를로 {mc.valid_trials}회 완료")
    rows = sn.tornado(cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM, led)
    print(f"  민감도 {len(rows)}개 항목 완료")

    for lang in ("ko", "en"):
        print(f"\n[{lang.upper()}]")
        chart1_tco_curves(led, lang)
        chart2_breakeven_distribution(led, lang, mc=mc)
        chart3_tornado(led, lang, rows=rows)
        chart4_tier_price_gap(lang)
        chart5_tiering_effect(led, lang)
        chart6_cost_breakdown(led, lang)

    print(f"\n완료: {len(list(OUT.glob('*.png')))}개 파일")


if __name__ == "__main__":
    main()
