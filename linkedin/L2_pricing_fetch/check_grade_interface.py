# -*- coding: utf-8 -*-
"""상표 배율 3.4배가 등급·연결방식 차이로 설명되는지 점검한다.

입력: out/ref_하드디스크드라이브_items.json (조달청 2026 상반기 참고 표본, API 호출 없음)

판별 근거
- 제조사 상표: 모델 번호 명명 규칙. 각 규칙은 제조사 데이터시트·판매처 표기로 확인한 쌍을 근거로 한다.
- 서버·스토리지 상표: 부품번호를 개별 조회. '확인'은 판매처·제조사 문서에 연결방식이 명시된 것,
  '추정'은 같은 장비 계열 문서로 미루어 본 것, '미확인'은 정보를 찾지 못한 것.
"""
import json
import pathlib
import re
import statistics as st
from collections import Counter, defaultdict

HERE = pathlib.Path(__file__).resolve().parent
ITEMS = json.loads((HERE / "out/ref_하드디스크드라이브_items.json").read_text(encoding="utf-8"))
BARE = ("seagate", "segate", "western", "toshiba")

# ---------------------------------------------------------------------------
# 제조사 상표 — 등급
# ---------------------------------------------------------------------------
GRADE_RULES = [
    ("데이터센터용", r"ST\d+NM|EXOS|HUH7|HUS7|WUH7|HC5\d\d|HC6\d\d|ULTRASTAR|FRYZ|\bMG\d{2}"),
    ("NAS용", r"ST\d+(VN|NE|NT)|IRONWOLF|EF[RZABP]X|KF[BG]X|HDWG|N300"),
    ("감시용", r"ST\d+(VX|VE)|SKYHAWK|PUR[PZX]|HDWT|S300"),
    ("PC용", r"ST\d+DM|BARRACUDA|EZ[AE][ZX]|HDWR|X300|DT01"),
]

# ---------------------------------------------------------------------------
# 제조사 상표 데이터센터용 — 연결방식
#   WD/HGST : AL5·AL4 = SAS, ALE = SATA  (HUH721212AL5204 SAS / HUH721212ALE600 SATA)
#   Toshiba : MGxxS = SAS, MGxxA = SATA   (MG07SCA12TE SAS / MG07ACA12TE SATA)
#   Seagate : 세대마다 달라 번호 끝부분을 개별 확인
# ---------------------------------------------------------------------------
SEAGATE_SAS = {"NM004J", "NM002G", "NM002D", "NM007H", "NM0075", "NM0038", "NM0048", "NM0096", "NM018B"}
SEAGATE_SATA = {"NM000J", "NM001G", "NM007D", "NM0055", "NM000A", "NM0008", "NM017B"}
SEAGATE_SATA_BY_PATTERN = {"NM002H"}   # X24 24TB에서 확인(ST24000NM002H), 같은 접미사를 12·16·20TB에 적용


def bare_interface(spec):
    s = (spec or "").upper()
    if re.search(r"AL[45]\d", s):
        return "SAS", "확인"
    if re.search(r"ALE", s):
        return "SATA", "확인"
    m = re.search(r"\bMG\d{2}([AS])", s)
    if m:
        return ("SAS" if m.group(1) == "S" else "SATA"), "확인"
    m = re.search(r"ST\d+(NM\w{3,4})", s)
    if m:
        suf = m.group(1)
        if suf in SEAGATE_SAS:
            return "SAS", "확인"
        if suf in SEAGATE_SATA:
            return "SATA", "확인"
        if suf in SEAGATE_SATA_BY_PATTERN:
            return "SATA", "추정"
    return None, "미확인"


# ---------------------------------------------------------------------------
# 서버·스토리지 상표 — 부품번호별 연결방식·등급
# ---------------------------------------------------------------------------
OEM = [
    # (정규식, 연결방식, 근거수준, 메모)
    (r"HEL[HWT]72S3", "SAS", "확인", "Infortrend — S3 = SAS 12Gb, 7200rpm"),
    (r"01EJ990", "SAS", "확인", "IBM Storwize V7000 Gen2 10TB NL-SAS 12Gb"),
    (r"4XB7A14104", "SAS", "확인", "Lenovo ThinkSystem DE 12TB NL-SAS 12Gb"),
    (r"400-BQJS", "SAS", "확인", "Dell 16TB NL-SAS 12Gb"),
    (r"161-BBUT", "SAS", "확인", "Dell 20TB NL-SAS 12Gb"),
    (r"E-X4131A", "SAS", "확인", "NetApp E-Series 12TB NL-SAS 12Gb"),
    (r"ETRN", "SAS", "확인", "Fujitsu ETERNUS — 전 드라이브 SAS 12Gb 듀얼포트, ETRNCG=16TB NL-SAS"),
    (r"DP60P-SPN", "SAS", "확인", "Nexsan E-Series 60P 예비 드라이브, SPN=SAS 니어라인"),
    (r"\bA(L[34]|HD|H7)[0-9A-Z]\b", "SAS", "추정", "IBM FlashSystem 드라이브 기능코드 — 해당 계열 NL-SAS 12Gb"),
    (r"01LJ|01YM|02PX", "SAS", "추정", "IBM Storwize/FlashSystem FRU — 같은 계열 NL-SAS"),
    (r"DKC-F810I-\d+RH", "SAS", "추정", "Hitachi VSP 드라이브 — VSP 백엔드 SAS"),
    (r"E-X4074A", "SAS", "추정", "NetApp E-Series"),
    (r"4XB7A14102", "SAS", "추정", "Lenovo ThinkSystem DE 계열"),
    (r"D4-VS07", "SAS", "추정", "Dell EMC Unity 계열 NL-SAS"),
]


def oem_interface(spec):
    s = (spec or "").upper()
    for rx, iface, lvl, memo in OEM:
        if re.search(rx, s):
            return iface, lvl, memo
    return None, "미확인", ""


def is_bare(item):
    return any(b in (item["vendor_raw"] or "").lower() for b in BARE)


def grade(spec):
    s = (spec or "").upper()
    for g, rx in GRADE_RULES:
        if re.search(rx, s):
            return g
    return "판별 불가"


def med(v):
    return st.median(v) if v else None


def fmt(v):
    return "-" if v is None else f"{v:,.0f}"


def main():
    big = [i for i in ITEMS if i["capacity_tb"] >= 8]

    # 제조사 상표 데이터센터용 × 연결방식
    bare_dc = [i for i in big if is_bare(i) and grade(i["spec"]) == "데이터센터용"]
    by_if = defaultdict(list)
    lvl_count = Counter()
    for i in bare_dc:
        iface, lvl = bare_interface(i["spec"])
        by_if[iface or "미확인"].append(i["krw_per_tb"])
        lvl_count[lvl] += 1

    print("[1] 제조사 상표 · 데이터센터용 · 8TB 이상 — 연결방식별")
    for k in ("SATA", "SAS", "미확인"):
        v = sorted(by_if.get(k, []))
        if v:
            print(f"    {k:<5} {len(v):>3}개  중앙 {fmt(med(v)):>9}  (최저 {fmt(v[0])} / 최고 {fmt(v[-1])})")
    print(f"    판별 근거: {dict(lvl_count)}")
    sata, sas = med(by_if.get("SATA")), med(by_if.get("SAS"))
    if sata and sas:
        print(f"    → 같은 제조사·같은 등급에서 SAS/SATA = {sas / sata:.2f}배")

    # 서버·스토리지 상표 × 연결방식·근거수준
    oem = [i for i in big if not is_bare(i)]
    oem_lvl = defaultdict(list)
    unknown = Counter()
    for i in oem:
        iface, lvl, _ = oem_interface(i["spec"])
        oem_lvl[lvl].append(i["krw_per_tb"])
        if lvl == "미확인":
            unknown[i["vendor"]] += 1
    print("\n[2] 서버·스토리지 상표 · 8TB 이상 — 연결방식 판별 수준")
    for lvl in ("확인", "추정", "미확인"):
        v = oem_lvl.get(lvl, [])
        print(f"    {lvl:<4} {len(v):>3}개  중앙 {fmt(med(v)):>9}")
    print(f"    확인·추정분은 전부 SAS. 미확인 상표: {dict(unknown)}")

    # 배율 비교
    oem_all = med([i["krw_per_tb"] for i in oem])
    oem_sas_conf = med(oem_lvl.get("확인", []))
    oem_sas_any = med(oem_lvl.get("확인", []) + oem_lvl.get("추정", []))
    bare_dc_all = med([i["krw_per_tb"] for i in bare_dc])

    print("\n[3] 상표 배율 — 무엇을 맞추느냐에 따라")
    rows = [
        ("등급 혼합 (초안)", med([i["krw_per_tb"] for i in big if is_bare(i)]), oem_all),
        ("등급 맞춤 (4판 보정)", bare_dc_all, oem_all),
        ("등급+연결방식 맞춤: SAS끼리, 서버 쪽 확인·추정", sas, oem_sas_any),
        ("등급+연결방식 맞춤: SAS끼리, 서버 쪽 확인만", sas, oem_sas_conf),
    ]
    for label, a, b in rows:
        print(f"    {label:<34} 제조사 {fmt(a):>9}  서버 {fmt(b):>9}  → {b / a:.2f}배")

    # 서버·스토리지 상표를 장비 종류로 나눈다
    #   스토리지 장비용: 해당 상표가 디스크어레이·HCI 장비 부품으로 파는 드라이브
    #   서버용: 서버(PowerEdge·ThinkSystem 서버) 부품으로 파는 드라이브
    STORAGE_VENDORS = {"IBM", "Hitachi", "Fujitsu", "NetApp", "Infortrend", "Nexsan", "Pivot3"}
    STORAGE_PARTS = r"4XB7A1410|D4-VS07|00YG663"      # Lenovo ThinkSystem DE, Dell EMC Unity, Lenovo Storage
    kind = defaultdict(list)
    kind_vendor = defaultdict(Counter)
    for i in oem:
        s = (i["spec"] or "").upper()
        if i["vendor"] in STORAGE_VENDORS or re.search(STORAGE_PARTS, s):
            k = "스토리지 장비용"
        elif i["vendor"] in ("Dell", "Lenovo"):
            k = "서버용"
        else:
            k = "미상"
        kind[k].append(i["krw_per_tb"])
        kind_vendor[k][i["vendor"]] += 1
    print("\n[4] 서버·스토리지 상표를 장비 종류로 나누면")
    for k in ("스토리지 장비용", "서버용", "미상"):
        v = kind.get(k, [])
        print(f"    {k:<8} {len(v):>3}개  중앙 {fmt(med(v)):>9}  {dict(kind_vendor[k])}")
    srv = med(kind.get("서버용", []))
    if srv:
        print(f"    → 서버용만 보면 제조사 상표 SAS 대비 {srv / sas:.2f}배, SATA 대비 {srv / sata:.2f}배")

    out = {
        "oem_by_equipment": {k: {"n": len(v), "median": med(v), "vendors": dict(kind_vendor[k])}
                             for k, v in kind.items()},
        "bare_dc_by_interface": {k: {"n": len(v), "median": med(v)} for k, v in by_if.items()},
        "bare_dc_interface_evidence": dict(lvl_count),
        "oem_by_evidence": {k: {"n": len(v), "median": med(v)} for k, v in oem_lvl.items()},
        "oem_unknown_vendors": dict(unknown),
        "ratios": [{"label": l, "bare": a, "oem": b, "ratio": b / a} for l, a, b in rows],
    }
    (HERE / "out/grade_interface_check.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
