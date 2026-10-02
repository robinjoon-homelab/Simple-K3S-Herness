# 공용 Traefik HTTPS 정책 적용과 확인

`infrastructure/traefik/resources.yaml`을 바꾼 뒤 정책이 실제 Traefik에 적용됐는지 확인하는 절차다. 정책의 의미와 워크로드 Ingress 계약은 [워크로드 HTTPS 계약](../contracts/workload.md#워크로드-https-계약)이 정한다. 지난 확인 결과는 [검증 기록](../records/traefik-https.md)에 있다.

## 정책 요약

`traefik-policy` Application이 `infrastructure/traefik/resources.yaml`을 자동 동기화한다. 이 Application은 자동 동기화와 self-heal을 쓰고 prune은 끈다. 파일은 `kube-system`의 `platform-https-headers` Middleware와 `traefik` HelmChartConfig를 선언한다. `web` 요청은 HTTPS 443으로 영구 리다이렉트하고, `websecure`에는 TLS와 `Strict-Transport-Security: max-age=31536000`을 적용한다. `includeSubDomains`와 `preload`는 쓰지 않는다. 일반 앱, Argo CD, 레지스트리를 포함한 Traefik 웹 접속 전체에 적용된다.

인증서 발급과 갱신은 cert-manager가 맡는다. 일반 앱 Chart는 HTTPS Ingress와 Certificate만 만들고 앱별 HTTP Ingress나 Middleware를 만들지 않는다. Argo CD의 기존 Ingress·서버 설정과 관리 주체는 그대로이며 Argo CD 서버를 재시작할 필요는 없다.

## 적용 확인

변경을 원격 `main`에 push하면 `root-apps`가 정책 Application을 동기화하고, k3s Helm Controller가 HelmChartConfig를 읽어 Traefik Deployment를 갱신한다. 정적 설정이 바뀌므로 자동 rollout 중에 접속이 잠깐 끊길 수 있다.

Application의 `Synced`는 HelmChartConfig가 동기화됐다는 뜻일 뿐 Helm 적용이 끝났다는 뜻이 아니다. 다음 순서로 확인한다.

1. 동기화 상태와 revision을 확인한다.
2. Traefik의 실제 실행 인자가 새 정책으로 바뀌었는지 확인한다. 아직 이전 값이면 Helm Controller의 적용을 기다린다.
3. rollout 완료를 확인한다.

```bash
kubectl --context homelab -n argocd get application traefik-policy \
  -o jsonpath='{.status.sync.status}{"\n"}{.status.sync.revision}{"\n"}'
kubectl --context homelab -n kube-system get deployment traefik \
  -o jsonpath='{.spec.template.spec.containers[*].args}{"\n"}'
kubectl --context homelab -n kube-system rollout status deployment/traefik --timeout=5m
```

실행 인자에는 `web`의 리다이렉트 대상 `:443`, scheme `https`, permanent `true`와 `websecure`의 TLS, `kube-system-platform-https-headers@kubernetescrd` Middleware가 있어야 한다.

## 외부 접속 확인

외부 클라이언트에서 상태 줄과 접속 정책 헤더만 확인한다. 일반 앱, Argo CD, 레지스트리 주소마다 반복한다.

```bash
curl --silent --show-error --output /dev/null --dump-header - \
  http://homelab.robinjoon.xyz/argocd/ \
  | awk '/^HTTP\// || tolower($0) ~ /^(location|strict-transport-security):/'
curl --silent --show-error --output /dev/null --dump-header - \
  https://homelab.robinjoon.xyz/argocd/ \
  | awk '/^HTTP\// || tolower($0) ~ /^(location|strict-transport-security):/'
```

HTTP는 301 또는 308로 같은 HTTPS 경로에 전환돼야 한다. HTTPS는 인증서 검증에 성공하고 HSTS 헤더를 포함해야 한다. UI와 레지스트리 인증이 기존대로 동작하는지도 확인한다. 로컬 선언·렌더링 검사는 실제 적용과 외부 접속 확인을 대신하지 않는다.
