# phase03b 저장 계층 — 검증 기록

> 대상 원 프로젝트 문서: `docs/phase03b_storage_layer.md` · 구현 `src/storage_model.py`
> 작성 2026-09-16 · 상태 **V4 기록 완료, 승인 대기** · 승인란은 [`../AUDIT_REPORT.md`](../AUDIT_REPORT.md)

영향 수치 읽는 법은 [`phase02_cost_structure.md`](phase02_cost_structure.md) 머리말과 같습니다. 원 모델 BE는 44.2 / 22.3 / 123.3이며, 순서는 티어링 대 관리형 5년 / 티어링 대 Splunk 5년 / 티어링 대 관리형 3년입니다.

---

## D4 · 오류 — S3로 내린 데이터에도 복제본을 곱함

| 칸 | 내용 |
|---|---|
| 원 프로젝트 위치 | `src/storage_model.py` `compute_storage_elastic` — 총량 = 일일량 × 보존일 × **(1 + 복제본)** × 1.15, 그중 70%를 S3로 |
| 현재 계산 | S3에 원본 + 복제본 **2벌**을 저장 |
| 근거 (확인 2026-09-16) | Elastic — 스냅샷은 **주(primary) 샤드의 세그먼트만** 복사하며 증분·중복 제거 방식입니다. 검색 가능한 스냅샷 인덱스는 기본적으로 복제본이 없고, 통째로 올린 인덱스는 복제본이 필요 없어 디스크가 약 50% 준다고 적습니다 — [Snapshot and restore](https://www.elastic.co/docs/deploy-manage/tools/snapshot-and-restore), [Data tiers](https://www.elastic.co/docs/manage-data/lifecycle/data-tiers) |
| | OpenSearch 스냅샷도 주 샤드를 담습니다 — [OpenSearch 스냅샷](https://docs.opensearch.org/latest/tuning-your-cluster/availability-and-recovery/snapshots/snapshot-restore/). AWS UltraWarm(S3 기반)도 **한 벌이면 되고 주 샤드 크기만 과금** — [AWS 운영 모범사례](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/bp.html) |
| 영향 | 티어링 20GB −9.8% · 50GB **−16.0%** · 100GB **−19.4%** · BE **29.5 / 17.7 / 66.4** |
| | 50GB 1년차 기준 S3 58.8TB → 29.4TB |
| 수정안 | `compute_storage_elastic`에서 오브젝트 계층은 `(1 + 복제본)`을 빼고 원본 1벌로 계산 |
| 수정 시 함께 바뀌는 것 | `storage_model.py`, `tests/test_storage_model.py::test_elastic_tiering_splits_but_preserves_total`(티어링이 총량을 보존한다고 고정 — S3분 사본을 빼면 총량이 줄어 수정 필요), phase03b·phase04의 티어링 서술, phase04~06 수치, README |
| 승인 | 대기 |

---

## D6 · 오류 — Splunk 사본 없음(rf=1, sf=1)이 기본값

| 칸 | 내용 |
|---|---|
| 원 프로젝트 위치 | `src/cost_model.py:62-63`(`rf=1`, `sf=1`) · `src/storage_model.py` `ReplicationPolicy`(기본 1벌, "흔히 RF=3, SF=2로 알려져 있으나 미검증") · `docs/phase03b_storage_layer.md` §4(미확정 사항 — RF·SF 기본값) · `docs/phase10_verification.md` 171행(기본값 미확정을 한계로 기록) · `data/pricing.yaml` `replication_factor`·`search_factor`(pending) |
| 현재 계산 | 서버는 HA 최소 3대인데 데이터 사본은 1벌. frozen 아카이브도 1벌 |
| 근거 (확인 2026-09-16) | Splunk 공식 — `replication_factor` **기본 3**, `search_factor` **기본 2** — [Replication factor](https://help.splunk.com/en/splunk-enterprise/administer/manage-indexers-and-indexer-clusters/10.4/how-indexer-clusters-work/replication-factor), [Search factor](https://help.splunk.com/en/splunk-enterprise/administer/manage-indexers-and-indexer-clusters/10.4/how-indexer-clusters-work/search-factor) |
| | Splunk Validated Architectures — **보안 감사·위협 탐지 용도는 인덱서 클러스터에 복제 계수 2 이상, 3 권장(기본값)** — [SVA C1/C11](https://help.splunk.com/en/data-management/splunk-validated-architectures/splunk-platform-indexing-and-search/distributed-clustered-deployment---single-site-c1--c11) |
| | 클러스터에서 frozen으로 넘길 때 **각 피어가 자기 사본을 아카이브**하므로 아카이브 사본 수 = 복제 계수 — [Archive indexed data](https://help.splunk.com/en/splunk-enterprise/administer/manage-indexers-and-indexer-clusters/10.4/back-up-and-archive-your-indexes/archive-indexed-data) |
| 판정 | phase10이 "공식 문서로 확인하지 못함"이라고 남긴 한계가 **이제 공식 문서로 확인됩니다.** 보안 용도에서 사본 없음은 권장 구성과 어긋나고, HA 3대 전제와도 맞지 않습니다 |
| 영향 | D6a rf=2·sf=2·아카이브 2벌: Splunk 50GB **+2.0%** · BE(2) 22.3 → **20.8** |
| | D6b rf=3·sf=2·아카이브 3벌(기본값): Splunk 50GB **+3.4%** · BE(2) → **20.5** |
| 수정안 | 기본값을 rf=3·sf=2로(최소 2·2를 민감도 하한으로), `ReplicationPolicy.frozen_copies`를 rf와 연동. 원장 `replication_factor`·`search_factor`를 pending에서 confirmed로 |
| 수정 시 함께 바뀌는 것 | `cost_model.Scenario`, `storage_model.ReplicationPolicy`, 원장, `tests/test_storage_model.py::test_verified_example_single_copy`(검증 예시 자체는 사본 1벌 예시라 유지 가능), phase03b·04·05·10, README |
| 승인 | 대기 |

---

## D11 · 오류(누락) — EBS 여유 공간

| 칸 | 내용 |
|---|---|
| 원 프로젝트 위치 | `src/storage_model.py` `compute_storage_elastic` · `src/cost_model.py:197-214` |
| 현재 계산 | 데이터 크기와 **똑같은 크기**의 EBS를 할당 |
| 근거 (확인 2026-09-16) | EBS는 **할당한 용량**에 과금합니다(AWS Price List 설명 "provisioned storage") |
| | Elastic 공식 블로그 사이징은 데이터 크기에 **디스크 워터마크 여유 +15%**(2020년 글은 +10% 여유를 추가)를 더합니다 — [Elastic Blog 2018](https://www.elastic.co/blog/sizing-hot-warm-architectures-for-logging-and-metrics-in-the-elasticsearch-service-on-elastic-cloud), [2020](https://www.elastic.co/blog/benchmarking-and-sizing-your-elasticsearch-cluster-for-logs-and-metrics) |
| | AWS OpenSearch Service 산식은 원본 × (1 + 복제본) × 1.1 **÷ 0.95 ÷ 0.8**(약 ×1.45) — [Calculating storage requirements](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/bp-storage.html) |
| | 원장 `sizing_tb_per_node_selfhosted`의 "×0.75 사용률 상한"은 **서버 대수 계산에만** 들어가고 디스크 요금에는 반영되지 않습니다 |
| 영향 | D11a Elastic 기준(+15%): 티어링 50GB **+4.0%** · 로컬 **+9.3%** · BE **49.8 / 24.5 / 157.7** |
| | D11b AWS 산식: 티어링 **+8.5%** · 로컬 **+19.5%** · BE **61.1 / 27.7 / 없음(관리형)** |
| 수정안 | 원장에 "디스크 여유율" 항목(예: 0 / 13 / 24%)을 두고 EBS 할당량에 반영. Splunk 로컬 계층에도 같은 규칙 적용(영향 +0.1~0.3%) |
| 수정 시 함께 바뀌는 것 | 원장, `storage_model`·`cost_model`, 테스트, phase03b·04~06, README |
| 승인 | 대기 |

---

## D3 · 맞음(값) + 오류(설명, 경미) + 가정 선택(압축) — 오픈소스 용량 계수 1.15

| 칸 | 내용 |
|---|---|
| 원 프로젝트 위치 | `src/storage_model.py` `ELASTIC_OVERHEAD = 1.15`(주석: Lucene 1.1~1.2 + translog 1.05) · 원장 `elastic_overhead` |
| 근거 (확인 2026-09-16) | 원본 대비 인덱스 크기 — Elastic 블로그 약 1.1(2018)·관측 평균 1.2(2020), AWS "흔히 약 110%" → **1.15는 공식 범위 안** |
| | translog 크기는 샤드당 **flush 임계값으로 상한**(Elasticsearch 기본 10GB, OpenSearch 512MB)이라 보존 기간에 비례해 커지지 않습니다 — [Elastic translog 설정](https://www.elastic.co/docs/reference/elasticsearch/index-settings/translog) → 주석의 "translog 1.05"는 **설명이 틀림** |
| | 압축 — `best_compression`(무료판 가능)은 15~25% 절감(2015년 블로그, Elastic이 오래된 글로 표시), OpenSearch zstd·best_compression은 비로그 벤치마크에서 30~35% 절감. logsdb는 최대 65% 절감이라 발표됐으나 핵심 기능(synthetic _source)이 **Enterprise 전용** — [OpenSearch codecs](https://docs.opensearch.org/latest/im-plugin/index-codecs/), [Elastic 8.17](https://www.elastic.co/blog/whats-new-elastic-8-17-0) |
| | 보안 로그 전용 공식 비율은 찾지 못함 |
| 판정 | 값은 **맞음**. 주석 설명은 **경미한 오류**. 압축 설정을 쓰면 줄어드는 폭은 **가정 선택** |
| 영향 (압축 20% 절감, 계수 0.92) | 티어링 50GB **−13.3%** · 로컬 −15.4% · BE **30.8 / 18.0 / 73.3** (검증값 B-유리에만 반영) |
| 수정안 | 주석·원장 source에서 translog 근거를 빼고 "인덱스 구조 오버헤드 1.1~1.2"로 정리. 압축 설정 시나리오를 민감도에 추가 |
| 승인 | 대기 |

---

## D10 · 가정 선택(서비스 수준) — 바로 검색 가능한 기간이 두 경로에서 다름

| 칸 | 내용 |
|---|---|
| 원 프로젝트 위치 | `src/storage_model.py`(Splunk 경로 hot/warm 30 + cold 60일만 검색 가능, frozen 640일 검색 불가) · `compute_storage_elastic`(티어링해도 730일 전부 검색 가능으로 취급) · `docs/phase05_breakeven.md`(SmartStore 전 기간 검색 옵션에서만 "기능이 달라지므로 총액만으로 비교하면 안 된다"고 명시) |
| 근거 (확인 2026-09-16) | Splunk frozen 버킷은 **검색 불가**, 되살리려면 thaw·재구축 필요 — [How the indexer stores indexes](https://help.splunk.com/en/data-management/manage-splunk-enterprise-indexers/10.0/manage-index-storage/how-the-indexer-stores-indexes) |
| 현재 상태 | 오픈소스(티어링)는 **2년 전부 바로 검색**(단, phase02 S4 조건이 충족될 때만), Splunk는 **90일만 바로 검색**. 원 프로젝트는 SmartStore 옵션에서만 이 차이를 경고하고, 주 비교(오픈소스 대 Splunk·관리형)에서는 언급하지 않습니다 |
| 판정 | 틀린 계산은 아니지만 **서비스 수준이 다른 두 구성을 총액으로 비교**합니다. 어느 수준으로 맞출지는 조직의 요구(ISMS 조회 요구 등)가 정하므로 **가정 선택** |
| 영향 — 원 모델 위에서 오픈소스를 Splunk 수준(90일 검색, 나머지 S3 원본 1벌 검색 불가)으로 맞추면 | 티어링 50GB **−44.1%** · BE **20.5 / 13.6 / 39.2** |
| 영향 — 검증값 A 위에서 같은 조정 | BE(1) 62 → **27.7** · BE(3) 157 → **54.5** (`audit_combo.py` "참고: A + 검색 90일 대칭") |
| 수정안 | 비교표에 "바로 검색 가능한 기간"을 명시하고, 같은 서비스 수준으로 맞춘 비교를 병기 |
| 승인 | 대기 |

---

## 맞음

| ID | 항목 | 근거 |
|---|---|---|
| D7 | Splunk 원본 15%·색인 35%(합 50%), frozen 15% | Splunk 공식 "Estimate your storage requirements"(10.4) — 압축 원본 약 15%, 색인 파일 약 35%, 계획 시 50% 가정 권장, 아카이브는 원본만 남김 — [링크](https://help.splunk.com/en/splunk-enterprise/get-started/deployment-capacity-manual/10.4/hardware-capacity-planning/estimate-your-storage-requirements) |
| — | Splunk frozen 640일 검색 불가 | 위 D10 근거와 같음 |
