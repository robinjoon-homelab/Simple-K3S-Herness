# 중앙 egress TLS 검사 프록시 검증 기록

각 절은 그날의 관찰이며 현재 상태를 보장하지 않는다. 절차는 [운영 절차](../runbooks/egress-proxy.md)를 따른다.

## 2026-11-02 이미지 패키징

| 항목 | 값 |
| --- | --- |
| Rust 소스 리비전 | `fda826ba39b1a343189eff6777eb056ade9781d7` |
| 버전 | `1.7.0-homelab-fda826ba` |
| 프로파일·기능 | `quick-release`, `crypto-aws-lc,jemalloc,mimalloc` |
| OCI 인덱스 digest | `sha256:5992d2dab8276d0d3f298654f5b5b257fb79e23a9f88607f055748db4a5e9365` |
| OCI amd64 매니페스트 digest | `sha256:bbca89c350b7fb920fa5fa74e829a921c7787cf836acd8148847b6c97c3f351a` |
| OCI arm64 매니페스트 digest | `sha256:6c83da07e7c84ca90adde3548e675af6decbe5a594051742c0575c3f33b04bfc` |
| 태그 기준 | `registry.homelab.robinjoon.xyz/apps/agentgateway:git-fda826ba39b1-20261102-0346` |

확인한 것은 다음과 같다.

- 독립 검증에서 amd64와 arm64 이미지를 현재 설정으로 실행해 각각 18개, 모두 36개 시험을 통과했다. amd64는 QEMU로 실행했다. UID 65532, 읽기 전용 루트 파일 시스템, capability 전부 제거, 메모리 1Gi, CPU 1 조건이었다.
- 시험은 DNS·IPv4·IPv6의 SNI 없는 접속과 HTTP/2, 잘못된 이름·미신뢰·만료 인증서의 503, 오프라인 루트와 발급 CA 체인, `..data` 교체 다섯 번을 포함했다. 빈 번들로 바꾸면 모든 요청이 503이었고 복원 후 정상이었으며, 프로세스는 같은 PID를 유지했다.
- 로그에 쿼리 문자열이 남지 않았고, 내보낸 루트 파일 시스템에 인증서 파일과 `/etc/ssl`, `/etc/pki`가 없었다.
- OCI 형식으로 내보내면 매니페스트의 미디어 타입이 바뀌어 digest가 달라진다. 설정 digest와 rootfs `diff_ids`가 시험한 36개 실행의 이미지와 일치함을 확인했다. OCI 인덱스를 Docker에 적재해 digest로 실행한 `--version`이 두 아키텍처에서 통과했다.
- 자격증명 없이 실제 공개 대상을 최종 번들로 시험했다. GitHub와 PyPI는 200, `1.1.1.1`은 301, badssl의 이름 불일치·만료·미신뢰 주소는 503이었다.
- 번들은 엄격한 OpenSSL에서 CA 루트 120개로 읽혔고 차단 지문 네 개가 없었다. 번들 SHA-256은 `2b1dc20af8e91942e6cd37d358e687320d094d42cfaa34d85aeae7791c986629`였다.

확인하지 않은 범위는 다음과 같다.

- 이 digest는 로컬에서 내보낸 OCI 아카이브의 값이며 **레지스트리 발행은 끝나지 않았다.** 레지스트리 인증을 기다리고 있었다.
- 클러스터에 접속할 수 없어 배포와 운영 절차의 게이트 A·B·C를 실행하지 않았다. NetworkPolicy 집행과 노드 차단은 확인하지 않았다.

## 2026-11-02 CI 경로 준비

앞 절의 digest는 CI가 아니라 로컬에서 만든 이미지의 값이다. 사용자가 로컬 레지스트리 로그인 대신 기존 CI 경로를 쓰도록 바로잡았으므로 이 아카이브는 발행하지 않는다. 하네스의 `deployment.yaml`에 남은 값은 [최초 활성화 순서](../runbooks/egress-proxy.md#최초-활성화-순서)에서 CI가 발행한 digest로 바꿔야 한다.

포크의 `homelab-image.yml`, 하네스의 `release-central-egress-image.yml`과 `tools/release_central_egress.py`를 로컬에서 작성했다. 사용자가 로컬 준비까지만 요청했으므로 원격 저장소에 push하지 않았고, Actions 실행, SMS 정책 등록, 이미지 발행, 배포를 하지 않았다.

확인한 것은 다음과 같다.

- 하네스 테스트는 188개 가운데 187개가 통과하고, 선택 사항인 Traefik 픽스처 시험 1개를 건너뛰었다. 포크의 워크플로 정책 시험과 문서 검사도 통과했다.
- actionlint 1.7.12는 `homelab-image.yml`에서 문제를 찾지 못했다. `release-central-egress-image.yml`은 `queue` 키 경고만 제외하면 통과한다. 이 도구가 아직 모르는 키이며, 기존 `release-workload-image.yml`에도 같은 경고가 나오고 GitHub 문서에 있는 문법임을 따로 확인했다.
- 독립 검증에서 `tools/verify_headless_image.sh`를 기존 arm64 이미지에 실행해 메타데이터, UID, CA 저장소 부재, 설정 검증, 읽기 전용 실행, SNI 없는 IP 접속, 공개 TLS, 사고 체인과 루프백 거부, 로그 검사가 통과했다.
- BuildKit 0.30에서 `type=oci`와 `type=docker`를 함께 내보낸 결과의 rootfs `diff_ids`와 실행 설정이 일치했다.

확인하지 않은 범위는 다음과 같다.

- 두 워크플로를 GitHub에서 실행한 적이 없다. GitHub runner의 회귀 테스트, zot에 대한 `skopeo`와 `imagetools` 발행, SMS 조회, 하네스 릴리스 요청이 여기에 해당한다.
- `Dockerfile.headless`의 컴파일 경로를 끝까지 실행한 적이 없다. 지금까지의 이미지는 미리 빌드한 바이너리를 패키징했다.
- 빌드는 `CARGO_BUILD_JOBS=1`로 실행하도록 정했으며, 이 설정으로 GitHub runner의 시간 제한 안에 끝나는지는 확인하지 않았다.
