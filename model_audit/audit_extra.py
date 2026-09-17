# -*- coding: utf-8 -*-
"""
audit_extra.py — V5 보조 수치

1) 검증값 A에서 Splunk 라이선스를 몇 % 할인받아야 오픈소스(티어링)와 같아지는가
2) 참고: Splunk Cloud(인프라 포함 구독) 경로의 5년 라이선스 — 조합 3(AWS에 설치)과 다른 경로
3) 링크드인 L2가 쓰는 "AWS 디스크 5년 비용"과 "5년차 필요 용량"의 원 모델값 대 검증값

실행: python model_audit/audit_extra.py → out/extra.json
"""
import json
from dataclasses import replace

import audit_calc as ac
import audit_combo as co
import audit_impact as ai
import cost_model as cm
from config import DAYS_PER_YEAR


def discount_threshold(led, a, gb, years=5):
    """Splunk(A) 총액 = 티어링(A) 총액이 되는 라이선스 할인율(이분탐색)."""
    target = ac.tco(cm.SELF_HOSTED_TIERED, gb, led, "base", years, a)[1]
    lo, hi = 0.0, 1.0
    if ac.tco(cm.SPLUNK, gb, led, "base", years, a)[1] <= target:
        return 0.0
    if ac.tco(cm.SPLUNK, gb, led, "base", years, replace(a, sp_license_factor=0.0))[1] > target:
        return None  # 라이선스가 0원이어도 Splunk가 비쌈
    for _ in range(40):
        mid = (lo + hi) / 2
        s = ac.tco(cm.SPLUNK, gb, led, "base", years, replace(a, sp_license_factor=1 - mid))[1]
        if s > target:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2 * 100, 1)


def cloud_reference(led, gb, years=5, archive_basis="uncompressed"):
    """Splunk Cloud 목록가(수집 + ES) + 640일 아카이브(DDAA). 인프라·플랫폼 운영 포함 구독."""
    cld = ai.splunk_tiers("SE-S-CLD-ST", "ES-S-CLD-ST")
    fx = led.get("usd_krw", "base")
    gp = led.get("log_growth_rate", "base")
    esc_rate = led.get("price_escalation_rate", "base") / 100
    per_500gb = 276.0  # SE-S-ARC, 500GB 단위/년
    total = 0.0
    for y in range(1, years + 1):
        vol = ac.volume(gb, gp, y, True)
        plat = es = None
        for lo, p, e in cld:
            if vol >= lo:
                plat, es = p, e
        if plat is None:
            plat, es = cld[0][1], cld[0][2]
        factor = 1.0 if archive_basis == "uncompressed" else 0.15
        archive_gb = vol * (730 - 90) * factor
        blocks = -(-archive_gb // 500)
        total += (vol * (plat + es) + blocks * per_500gb) * fx * (1 + esc_rate) ** (y - 1)
    return round(total / 1e6, 1)


def l2_numbers(led, a, ov):
    lx = led.with_values(ov) if ov else led
    rows, _ = ac.tco(cm.SELF_HOSTED_TIERED, 50, lx, "base", 5, a)
    disk5 = sum(r.disk for r in rows) / 1e6
    y5 = rows[-1]
    # 사내 장비 경로(조합 2)는 S3가 없으므로 티어링 없는 경로의 5년차 로컬 용량을 본다
    rows_l, _ = ac.tco(cm.SELF_HOSTED, 50, lx, "base", 5, a)
    return {"aws_disk_5y_tiered_50gb": round(disk5, 1),
            "tiered_y5_local_tb": round(y5.local_tb, 1),
            "tiered_y5_object_tb": round(y5.object_tb, 1),
            "local_y5_tb_no_tiering": round(rows_l[-1].local_tb, 1),
            "local_y5_tb_with_free_space": round(rows_l[-1].local_tb / (1 - a.ebs_free_ratio), 1)}


if __name__ == "__main__":
    led = ac.load()
    la = led.with_values(co.WAGE_2026)
    out = {
        "discount_threshold_A": {gb: discount_threshold(la, co.A, gb) for gb in (20, 50, 100, 150)},
        "discount_threshold_B_unfav": {gb: discount_threshold(la, co.B_UNF, gb) for gb in (20, 50, 100, 150)},
        "cloud_reference_5y": {gb: {"uncompressed": cloud_reference(led, gb),
                                    "compressed": cloud_reference(led, gb, archive_basis="compressed")}
                               for gb in (50, 100)},
        "l2": {name: l2_numbers(led, a, ov) for name, a, ov in co.CASES[:4]},
    }
    (ai.HERE / "out" / "extra.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                                encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))
