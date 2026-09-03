"""
pricing_loader.py — 가격 원장(pricing.yaml) 로더 (Phase 4)

역할
    data/pricing.yaml을 읽어 계산 코드가 쓸 수 있는 형태로 제공한다.
    코드에 숫자를 직접 적지 않기 위한 계층이며, 값이 바뀌면 yaml만 고치면 된다.

설계 원칙
    1. 값을 꺼낼 때 status를 함께 확인한다.
       pending/blank 항목을 모르고 쓰면 None이 계산에 섞여 조용히 틀린 결과가 나온다.
       그래서 값이 없으면 명시적으로 예외를 던진다.
    2. low/base/high 중 어느 것을 쓸지 호출자가 명시한다.
       기본은 base이나, base가 없는 항목(범위만 있는 항목)은 low/high를 직접 지정해야 한다.
    3. USD 항목은 환율을 곱해 KRW로 환산한다. 환산 여부를 호출자가 알 수 있게 단위를 함께 반환한다.
"""

from dataclasses import dataclass
from pathlib import Path
import yaml


# 계산에 사용해도 되는 상태
#   confirmed  : 1차 출처로 검증됨
#   partial    : 일부만 확인됨
#   unverified : 값은 있으나 출처 미확보
#   assumed    : 근거 없는 범위 가정 (민감도 분석 필수)
USABLE_STATUS = {"confirmed", "partial", "unverified", "assumed"}
# 계산에 사용하면 안 되는 상태
BLOCKED_STATUS = {"pending", "blank", "deprecated"}
# 근거가 약해 민감도 분석이 반드시 필요한 상태
NEEDS_SENSITIVITY = {"assumed", "unverified"}


class PricingError(Exception):
    """원장에서 값을 꺼낼 수 없을 때 발생."""


@dataclass
class PriceItem:
    """원장 한 항목."""
    key: str
    name: str
    low: float
    base: float
    high: float
    unit: str
    status: str
    confidence: str
    source_url: str
    note: str

    def value(self, which="base"):
        """값을 꺼낸다. which는 'low'/'base'/'high'."""
        v = getattr(self, which)
        if v is None:
            raise PricingError(
                f"[{self.key}] '{which}' 값이 비어 있습니다 "
                f"(status={self.status}). 원장을 채우거나 다른 which를 지정하십시오."
            )
        return v

    @property
    def is_usd(self):
        return "USD" in (self.unit or "")


class PricingLedger:
    """가격 원장 전체."""

    def __init__(self, path):
        self.path = Path(path)
        with open(self.path, encoding="utf-8") as f:
            self._raw = yaml.safe_load(f)
        self._items = {}
        self._index()

    def _index(self):
        """중첩된 yaml을 평평한 키-항목 사전으로 만든다."""
        for section, body in self._raw.items():
            if not isinstance(body, dict):
                continue
            for key, node in body.items():
                if isinstance(node, dict) and "name" in node:
                    self._items[key] = PriceItem(
                        key=key,
                        name=node.get("name", ""),
                        low=node.get("low"),
                        base=node.get("base"),
                        high=node.get("high"),
                        unit=node.get("unit", ""),
                        status=node.get("status", "unknown"),
                        confidence=node.get("confidence", ""),
                        source_url=node.get("source_url", ""),
                        note=node.get("note", ""),
                    )

    def item(self, key):
        if key not in self._items:
            raise PricingError(f"원장에 '{key}' 항목이 없습니다.")
        return self._items[key]

    def get(self, key, which="base", allow_blocked=False):
        """값을 꺼낸다. 사용 불가 상태면 예외를 던진다."""
        it = self.item(key)
        if it.status in BLOCKED_STATUS and not allow_blocked:
            raise PricingError(
                f"[{key}] status='{it.status}'이므로 계산에 사용할 수 없습니다. "
                f"({it.name}) 원장을 먼저 채우십시오."
            )
        return it.value(which)

    def get_krw(self, key, which="base", fx_which="base"):
        """USD 항목이면 환율을 곱해 KRW로 환산해 반환한다."""
        it = self.item(key)
        v = self.get(key, which)
        if it.is_usd:
            fx = self.get("usd_krw", fx_which)
            return v * fx
        return v

    # --- 진단용 -------------------------------------------------------------

    def status_summary(self):
        from collections import Counter
        return dict(Counter(i.status for i in self._items.values()))

    def blocked_items(self):
        """계산에 쓸 수 없는 항목 목록. 무엇이 비어 있는지 확인용."""
        return [(k, i.name, i.status) for k, i in self._items.items()
                if i.status in BLOCKED_STATUS]

    def missing_source(self):
        """confirmed/partial인데 출처 URL이 없는 항목."""
        return [(k, i.name) for k, i in self._items.items()
                if i.status in ("confirmed", "partial") and not i.source_url]

    def sensitivity_targets(self):
        """근거가 약해 민감도 분석이 반드시 필요한 항목.

        Phase 6에서 이 목록을 그대로 분석 대상으로 삼는다.
        가정값이 결론을 좌우하는지 확인하지 않으면 분석 전체가 무의미해진다.
        """
        return [(k, i.name, i.status) for k, i in self._items.items()
                if i.status in NEEDS_SENSITIVITY]

    def keys(self):
        return sorted(self._items.keys())


def load(path=None):
    """기본 경로에서 원장을 읽는다."""
    if path is None:
        here = Path(__file__).resolve().parent
        path = here.parent / "data" / "pricing.yaml"
    return PricingLedger(path)


if __name__ == "__main__":
    led = load()
    print(f"원장 로드: {led.path}")
    print(f"항목 수: {len(led.keys())}")
    print(f"상태 집계: {led.status_summary()}")

    print("\n[계산 불가 항목 — 아직 비어 있음]")
    for k, name, st in led.blocked_items():
        print(f"  - {k:38s} {st:10s} {name}")

    print("\n[출처 URL 누락(confirmed/partial)]")
    ms = led.missing_source()
    for k, name in ms:
        print(f"  - {k}: {name}")
    if not ms:
        print("  없음")

    print("\n[민감도 분석 필수 대상 — 근거 약함]")
    for k, name, st in led.sensitivity_targets():
        print(f"  - {k:38s} {st:10s} {name}")

    print("\n[샘플 조회]")
    print("  환율(base):", led.get("usd_krw"))
    print("  SSD 단가 USD:", led.get("ssd_price"))
    print("  SSD 단가 KRW 환산:", round(led.get_krw("ssd_price"), 2))
    print("  인건비 KRW:", led.get_krw("security_consultant_annual"))
