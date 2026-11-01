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
