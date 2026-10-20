# Dated listing 전이 검증 · 2026-10-20

기준 소스는 `74d80bc`이며 별도 `factor/listing-transitions-20261020` 작업 트리에서 구현했다. 활성 계산 소스와 입력, 진행 중인 Daily는 변경하지 않았다.

- `test_integrated_listing.py`, `test_integrated_data.py`, `test_integrated_archive.py`, `test_integrated_automation.py`, `test_integrated_service.py`: 54개 통과, 0.71초.
- `test_integrated_validation.py`, `test_integrated_publication.py`: 40개 통과, 15.67초.
- `git diff --check`: 통과.

모든 검사에 OPENBLAS·OMP·MKL·VECLIB·NUMEXPR 스레드 1개를 적용했다. 외부 수집이나 전체 백테스트는 실행하지 않았다. 핵심 반례는 시행일 전후의 UUU/DCM 조회, 정상 해시를 가진 옛 UUU 캐시의 사용 차단, 공급자 DCM 원응답 보존과 UUU 계산 열 정규화, 불완전 신규 이력의 두 차례 재시도 후 차단, 상장 근거가 바뀐 불변 스냅샷 재해석 차단이다. 기존 2,960개 종목 집합과 정규화 ID는 그대로다.

이 검증은 소스·소규모 입력 회귀에 대한 증빙이다. 실제 Daily의 수집·검증·배포 성공은 이후 실행에서 별도로 확인한다.

실제 Daily annotation과 [runner-images 공지](https://github.com/actions/runner-images/issues/14748)의 Ubuntu 26 전환(2026-10-19~11-19)에 따라 계산·입력 진단 두 job을 `ubuntu-24.04`로 고정했다. 소스 SHA·Python·uv.lock 고정과 함께 사용하며, admission·배포 job과 일정은 바꾸지 않았다. `test_actions_outcome.py`, `test_actions_source_race.py`, `test_docs_contract.py` 28개가 통과했고(2.08초), daily의 14개 shell block은 `bash -n`, 변경 파일은 `git diff --check`를 통과했다.
