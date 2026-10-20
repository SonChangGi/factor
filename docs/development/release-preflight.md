# 배포 전 검사

로컬·PR·Pages는 `scripts/check_release.sh`로 같은 결과를 검사하고 같은 게시 아티팩트를 만듭니다. 시장자료를 수집하거나 전체 백테스트를 다시 실행하지 않습니다.

```sh
uv sync --locked --extra dev --extra live
uv run --no-sync bash scripts/check_release.sh outputs/release-check-새이름/public
```

출력 폴더는 새 경로를 사용합니다. 이 명령은 commit·push·배포를 실행하지 않습니다. 공개 게시자는 기존 Pages workflow 하나이며, 계산 source SHA 확인·금융 불변식·비밀정보 검사·공개 파일 전체 바이트 대조를 유지합니다.

## 화면만 수정한 경우

검토를 마친 뒤 다음 명령으로 화면 파일의 해시를 준비합니다.

```sh
uv run --no-sync python scripts/prepare_presentation_release.py --write
```

허용 대상은 기존 `index.html`, `integrated.js`, `integrated_charts.js`, `integrated.css`, `styles.css`, `shared-nav.css`입니다. 새 파일·삭제 파일·금융 JSON 변경은 승인하지 않습니다. 금융 검증과 보안 검사를 임시 사본에서 통과한 경우에만 원래 manifest를 교체합니다. 계산 출처·입력 identity·성과·보유·검증 기록은 유지합니다. 준비 중 다른 작업이 파일을 수정하면 교체하지 않습니다. `--write`가 없으면 읽기 전용 검사입니다.

## 계산·의존성을 수정한 경우

일별 계산은 수집·캐시 복원 전에 정의 카탈로그·유니버스·금융 설정·dependency lock과 현재 검증 결과의 호환성을 확인합니다. 정의 변경 등으로 새 기준 결과의 검토가 필요하면 수집을 시작하지 않습니다. 기존 정상 결과를 유지하며, 과거 결과의 정의나 identity를 새 소스에 맞춰 덮어쓰지 않습니다.

최근 NumPy 정수 직렬화 실패를 재현하는 검사도 수집 전에 실행합니다. 종료 NAV 결측이나 과거 경로 변경은 기존 계산 후 금융 검증에서 계속 차단합니다.

## 자동 실행 범위

- PR·main 이외 branch push: 읽기 전용 Release Preflight. 게시 권한 없음.
- main Pages: 같은 전체 검사 후 게시, 정확한 source 확인 및 전체 파일 readback.
- 일별 수집: 빠른 파일·호환성·직렬화 검사 후 기존 파이프라인 실행.
- Python 배포 환경: Ubuntu 24.04·Python 3.11·uv 0.11.17·committed lock.
- 기존 일별·watchdog cron과 한 계산당 한 코어 제한 유지.

검사가 실패하면 실패 상태를 유지합니다. 이전 웹페이지가 열린다는 이유로 새 배포 성공으로 바꾸거나 알림을 숨기지 않습니다.
