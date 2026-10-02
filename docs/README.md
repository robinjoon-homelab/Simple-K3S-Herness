# 문서 색인

하네스 문서를 종류별로 모은 목록이다. 에이전트는 먼저 [AGENTS.md](../AGENTS.md)를 읽고 작업에 맞는 문서로 간다.

## 구조와 계약

현재 시스템이 어떻게 나뉘어 있고 각 부분이 무엇을 보장하는지 설명한다.

| 문서 | 다루는 내용 |
| --- | --- |
| [전체 설계](architecture/system.md) | 서비스·저장소의 책임, 신뢰 경계, 주요 흐름, 장애 영향 |
| [대표 관계도](diagrams/README.md) | 유일한 시스템 그림과 범례 |
| [워크로드 계약](contracts/workload.md) | 워크로드 JSON 계약, 공유 DB·레지스트리 모델, CLI·릴리스 인터페이스, Argo CD 정책 |
| [배포 요청 API 계약](contracts/deploy-api.md) | API 엔드포인트, 요청·오류, 인증과 권한 |
| [SMS 외부 계약](contracts/sms.md) | CI 조회 API, OIDC 조건, 배포 입력과 저장 책임 |
| [`load-ci-secrets` Action 계약](contracts/load-ci-secrets.md) | `load-ci-secrets` Action의 입력·전달·실패 규칙과 검증 기준 |

## 운영 절차

한 문서만 열고 한 작업을 끝낼 수 있게 썼다.

| 문서 | 작업 |
| --- | --- |
| [초기 연동](runbooks/bootstrap.md) | 빈 클러스터 연결, Root Application 등록, Reflector 복제 범위 |
| [레지스트리](runbooks/registry.md) | zot 계정·Secret, 이미지 발행, 비밀번호 교체, 백업·복구, 점검 |
| [CI 자격증명 연동](runbooks/load-ci-secrets.md) | SMS 허용 정책, 앱 CI 연결, 릴리스 요청, 하네스 토큰 교체 |
| [배포 요청 API](runbooks/deploy-api.md) | 서버 빌드·배포와 동작 점검 |
| [공용 Traefik HTTPS 정책](runbooks/traefik-https.md) | 정책 적용과 외부 접속 확인 |
| [홈 LAN VPN](runbooks/vpn.md) | Tailscale 인증, 배포, 외부 접속 확인 |

## 검증 기록

주제별로 날짜 절을 아래로 쌓는다. 각 기록은 그날의 관찰이며 현재 상태를 보장하지 않는다.

- [SMS와 `load-ci-secrets` Action 연동](records/ci-secrets.md)
- [배포 요청 API](records/deploy-api.md)
- [공용 Traefik HTTPS 정책](records/traefik-https.md)
- [홈 LAN VPN](records/vpn.md)

## 개발

- [테스트](development/testing.md): 로컬 테스트와 CI
- [문서 작성 규칙](development/documentation.md): 문서 배치, 문체, 용어, 확인 목록

## 지난 설계

구현을 마치고 보관한 설계다. 현재 계약이 아니다.

- [배포 요청 API 설계](design/archive/2026-09-26-deploy-request-api.md) (2026-09-26)
