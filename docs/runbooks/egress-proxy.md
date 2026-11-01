# 중앙 egress TLS 검사 프록시

앱의 외부 HTTPS를 명시적 CONNECT 프록시 한 곳으로 모아 복호화하고, 외부 서버 인증서를 프록시의 CA 정책으로 검증한다. 이 문서는 배포부터 앱 온보딩, CA 교체, 긴급 차단, 롤백까지 다룬다. 선언은 `infrastructure/central-egress`와 `argocd/managed/apps/central-egress.yaml`에 있고, 공통 Chart와 `tools/platform.py` 워크로드가 아닌 공통 인프라다.

## 구성 계약

| 항목 | 값 | 위치 |
| --- | --- | --- |
| 프록시 주소 | `http://egress-proxy.central-egress.svc.cluster.local:3128` | ClusterIP Service, Ingress 없음 |
| 발급 CA 인증서·키 | Secret `egress-proxy-dynamic-ca`의 `issuer.crt`, `issuer.key` | `central-egress`, Git 밖 |
| 앱이 신뢰할 공개 루트 | Secret `egress-proxy-public-ca`의 `ca.crt` | `central-egress`에서 Reflector로 복제, Git 밖 |
| 외부 서버 검증용 CA 번들 | ConfigMap `egress-proxy-upstream-ca`의 `ca-bundle.pem` | Git, 생성 도구로만 변경 |
| 게이트웨이 설정 | ConfigMap `egress-proxy-config`의 `config.yaml` | Git |
| 접속 허용 네임스페이스 | `network-policy.yaml`의 `kubernetes.io/metadata.name` 목록 | Git, 초기값은 `egress-proxy-canary`뿐 |
| 이미지 | `registry.homelab.robinjoon.xyz/apps/agentgateway@sha256:...` | `deployment.yaml`, digest로 고정 |

목적지 허용 목록은 없고 포트도 제한하지 않는다. 모든 터널을 복호화하며 인증서 검증을 끄는 설정과 TLS passthrough는 두지 않는다. 클라이언트가 SNI를 보내지 않거나 IP 주소로 접속하면 CONNECT 대상 기준으로 인증서를 발급한다.

이미지는 [agentgateway 포크](https://github.com/robinjoon-homelab/agentgateway)의 `Dockerfile.headless`로 만든다. Rust 소스 리비전을 `GIT_REVISION`으로 넘기고, 프로파일은 LTO 없는 최적화 빌드인 `quick-release`를 쓴다. 이미지에는 CA 저장소가 없어서 기본 번들로 대체되지 않는다.

## 1. 검사 CA 발급과 가져오기

저장소와 클러스터 밖의 안전한 작업 환경에서 실행한다. 루트 키는 오프라인으로 보관하고 클러스터에 넣지 않는다. 프록시에는 발급 CA 키만 제공한다. 발급 CA 키가 침해되면 앱이 신뢰하는 모든 외부 상대를 위조할 수 있으므로 다른 용도의 CA와 나눈다.

```bash
umask 077
openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-384 -aes-256-cbc -out root.key
openssl req -x509 -new -key root.key -sha384 -days 3650 \
  -subj "/O=Homelab/CN=Homelab Egress Inspection Root" \
  -addext "basicConstraints=critical,CA:TRUE,pathlen:1" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" \
  -addext "subjectKeyIdentifier=hash" -out root.crt

openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out issuer.key
openssl req -new -key issuer.key -subj "/O=Homelab/CN=Homelab Egress Inspection Issuer" -out issuer.csr
cat > issuer.ext <<'EXT'
basicConstraints=critical,CA:TRUE,pathlen:0
keyUsage=critical,keyCertSign,cRLSign
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid:always
EXT
openssl x509 -req -in issuer.csr -CA root.crt -CAkey root.key -sha384 -days 365 \
  -extfile issuer.ext -out issuer.crt

openssl verify -CAfile root.crt issuer.crt
test "$(openssl x509 -in issuer.crt -noout -pubkey | openssl sha256)" = \
     "$(openssl pkey -in issuer.key -pubout | openssl sha256)" && echo key-match
```

`issuer.key`는 PKCS#8(`BEGIN PRIVATE KEY`) 형식이어야 한다. `issuer.crt`에는 발급 CA 인증서 하나만 넣는다. 프록시가 리프 인증서와 이 인증서를 함께 보내고, 앱은 루트로 체인을 검증한다.

Argo CD가 Pod를 만들기 전에 Secret을 넣는다. Secret이 없으면 Pod는 `ContainerCreating`에 머물고 시작하지 않는다.

```bash
kubectl create namespace central-egress
kubectl -n central-egress create secret generic egress-proxy-dynamic-ca \
  --from-file=issuer.crt --from-file=issuer.key
kubectl -n central-egress create secret generic egress-proxy-public-ca --from-file=ca.crt=root.crt
kubectl -n central-egress annotate secret egress-proxy-public-ca --overwrite \
  reflector.v1.k8s.emberstack.com/reflection-allowed="true" \
  reflector.v1.k8s.emberstack.com/reflection-allowed-namespaces-selector="simple-k3s-harness.dev/workload=true" \
  reflector.v1.k8s.emberstack.com/reflection-auto-enabled="true" \
  reflector.v1.k8s.emberstack.com/reflection-auto-namespaces-selector="simple-k3s-harness.dev/workload=true"
```

공개 루트는 비밀 값이 아니므로 모든 워크로드 네임스페이스에 복제해도 된다. 복제만으로 앱이 프록시를 신뢰하거나 사용하게 되지는 않는다. 작업 후 `issuer.key`를 작업 환경에서 지우고, `root.key`는 오프라인 매체로 옮긴다.

## 2. 배포

1. `deployment.yaml`의 `image` digest가 레지스트리에 발행되어 있는지 `docker buildx imagetools inspect`로 확인한다. 발행 상태는 [검증 기록](../records/egress-proxy.md)에 남기며, 발행 전에 병합하면 Pod가 `ImagePullBackOff`에 머문다.
2. 변경을 `main`에 병합한다. Root Application이 `central-egress` Application을 만들고, 이 Application이 프록시와 NetworkPolicy, `egress-proxy-canary` 네임스페이스를 동기화한다.
3. 다음 명령으로 Pod가 `Ready`인지 확인한다. `Ready`는 설정을 읽었다는 뜻이며 차단 정책이 동작한다는 증거는 아니다.

```bash
kubectl -n argocd get application central-egress
kubectl -n central-egress rollout status deployment/egress-proxy
```

## 3. 카나리 게이트

앱을 온보딩하기 전에 세 게이트를 모두 통과해야 한다. k3s를 올리거나 네트워크 구현을 바꾼 뒤에도 다시 실행한다. 아래 명령의 변수를 먼저 정한다.

```bash
CURL_IMAGE=docker.io/curlimages/curl@sha256:3fb7e13e5d179a845c97d78204f3f1064d1907037f26a3ebf91710571151fd93
NODE_IP=$(kubectl get node -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')
POD=$(kubectl -n central-egress get pod -l app.kubernetes.io/name=egress-proxy -o jsonpath='{.items[0].metadata.name}')
PROXY=http://egress-proxy.central-egress.svc.cluster.local:3128
```

### 게이트 A: 프록시가 노드와 내부 주소에 닿지 않는다

`ipBlock`의 제외 목록만으로 내부 차단을 보장할 수 없다. [Kubernetes 문서](https://kubernetes.io/docs/concepts/services-networking/network-policies/)는 Pod가 실행 중인 노드와의 트래픽이 IP와 관계없이 항상 허용된다고 밝힌다. 실제 집행은 설치한 네트워크 구현에 달려 있다. 이 클러스터는 단일 노드이므로 그 노드에 API 서버, kubelet, Traefik이 모두 있다. 게이트웨이 자체는 DNS 결과 주소 가운데 루프백, 링크 로컬, 미지정 주소만 거부하고 사설 대역은 거부하지 않는다. 그래서 실제 네트워크 구현의 동작을 프록시 Pod의 네트워크 네임스페이스에서 직접 확인한다.

```bash
kubectl -n central-egress debug "$POD" -it --image="$CURL_IMAGE" --target=gateway --profile=restricted -- sh -c "
for target in $NODE_IP:6443 $NODE_IP:10250 $NODE_IP:443 $NODE_IP:80 10.43.0.1:443 192.168.0.1:443 1.1.1.1:443; do
  connected=\$(curl -ks --connect-timeout 5 --max-time 8 -o /dev/null -w '%{time_connect}' https://\$target/)
  case \"\$connected\" in 0.000000) echo \"blocked \$target\" ;; *) echo \"REACHED \$target\" ;; esac
done"
```

`1.1.1.1:443`만 `REACHED`이고 나머지는 모두 `blocked`여야 통과다. `1.1.1.1:443`이 `blocked`이면 시험 자체가 무효이므로 외부 연결부터 고친다. 노드가 공인 IPv6 주소를 쓰면 그 주소도 대상에 넣는다. `2000::/3`은 공인 IPv6를 허용하므로 해당 프리픽스를 `except`에 추가해야 한다.

내부 주소 하나라도 `REACHED`이면 온보딩을 멈춘다. 이 저장소의 선언으로는 고칠 수 없으며, 노드 방화벽을 추가하거나 게이트웨이에 주소 필터를 구현해야 한다. DNS 이름으로 접속해도 최종 연결 주소가 같으므로 이 시험이 DNS가 내부 주소를 돌려주는 경우까지 포함한다.

### 게이트 B: 검사와 거부가 동작한다

```bash
kubectl -n egress-proxy-canary run curl --image="$CURL_IMAGE" --restart=Never --overrides='{
  "spec": {
    "securityContext": {"runAsNonRoot": true, "runAsUser": 100, "seccompProfile": {"type": "RuntimeDefault"}},
    "volumes": [{"name": "ca", "secret": {"secretName": "egress-proxy-public-ca"}}],
    "containers": [{
      "name": "curl", "image": "'"$CURL_IMAGE"'", "command": ["sleep", "3600"],
      "securityContext": {"allowPrivilegeEscalation": false, "capabilities": {"drop": ["ALL"]}},
      "volumeMounts": [{"name": "ca", "mountPath": "/ca", "readOnly": true}]
    }]
  }
}'
kubectl -n egress-proxy-canary wait pod/curl --for=condition=Ready --timeout=120s
kubectl -n egress-proxy-canary exec curl -- sh -c "
for url in \
  https://www.example.com/ https://1.1.1.1/ \
  https://wrong.host.badssl.com/ https://expired.badssl.com/ https://untrusted-root.badssl.com/ \
  https://dv-g3b-emudhra.we-have-a-problem.com/ https://dv-g3b-aaa-emudhra.we-have-a-problem.com/ \
  https://$NODE_IP:6443/ https://10.43.0.1/ https://kubernetes.default.svc/ \
  https://169.254.169.254/ https://127.0.0.1/; do
  code=\$(curl -sS --proxy $PROXY --cacert /ca/ca.crt --max-time 30 -o /dev/null -w '%{http_code}' \$url 2>/dev/null)
  echo \"\$code \$url\"
done
curl -sv --proxy $PROXY --cacert /ca/ca.crt -o /dev/null https://www.example.com/ 2>&1 | grep -i issuer:"
```

| 대상 | 기대 결과 |
| --- | --- |
| `www.example.com`, `1.1.1.1` | 2xx 또는 3xx. `1.1.1.1`이 SNI 없는 IP 접속을 확인한다 |
| `badssl.com`의 세 주소 | 5xx. 이름 불일치, 만료, 미신뢰 인증서를 거부한다 |
| `we-have-a-problem.com`의 두 주소 | 5xx. 침해된 eMudhra 체인을 거부한다 |
| 나머지 내부 주소 | 5xx 또는 시간 초과(`000`) |
| 마지막 `issuer:` 줄 | `Homelab Egress Inspection Issuer` |

결과가 하나라도 다르면 온보딩을 멈춘다.

### 게이트 C: 우회 경로가 막힌다

```bash
kubectl -n egress-proxy-canary exec curl -- sh -c \
  "curl -sS --noproxy '*' --connect-timeout 5 -o /dev/null -w '%{http_code}\n' https://1.1.1.1/; echo exit=\$?"
kubectl -n default run egress-proxy-denied --image="$CURL_IMAGE" --restart=Never --rm -i --command -- \
  curl -sS --connect-timeout 5 "$PROXY" -o /dev/null -w '%{http_code}\n'
kubectl -n egress-proxy-canary delete pod curl
```

첫 명령은 직접 외부 연결이 막혀 `000`과 0이 아닌 종료 코드를 보여야 한다. 둘째 명령은 목록에 없는 네임스페이스에서 프록시에 닿지 못해 `000`을 보여야 한다.

## 4. 앱 온보딩

세 게이트를 통과한 뒤 앱을 한 개씩 옮긴다. 기존 앱은 아래 절차를 거치기 전까지 영향을 받지 않는다.

1. `network-policy.yaml`의 `values`에 앱 네임스페이스를 추가해 병합한다.
2. `python3 tools/platform.py get <app>` 결과를 기준으로 patch JSON을 만든다. `containers`와 `volumes`는 배열 전체가 교체되므로 기존 항목을 모두 포함하고 아래 값을 더한다. 병합 후 앱이 재시작한다.

```json
{
  "env": [
    {"name": "HTTPS_PROXY", "value": "http://egress-proxy.central-egress.svc.cluster.local:3128"},
    {"name": "https_proxy", "value": "http://egress-proxy.central-egress.svc.cluster.local:3128"},
    {"name": "NO_PROXY", "value": "localhost,127.0.0.1,.svc,.svc.cluster.local,.cluster.local,10.42.0.0/16,10.43.0.0/16"},
    {"name": "no_proxy", "value": "localhost,127.0.0.1,.svc,.svc.cluster.local,.cluster.local,10.42.0.0/16,10.43.0.0/16"}
  ],
  "volumeMounts": [{"name": "egress-proxy-ca", "mountPath": "/etc/egress-proxy-ca", "readOnly": true}],
  "volumes": [{"name": "egress-proxy-ca", "secret": {"secretName": "egress-proxy-public-ca"}}]
}
```

3. 외부로 나가는 HTTP 클라이언트에 전용 TLS 설정을 만든다. 신뢰 저장소에는 `/etc/egress-proxy-ca/ca.crt` 하나만 넣고, 프록시도 코드에서 명시하거나 환경변수를 실제로 따르는지 확인한다. Python은 전용 `SSLContext`, Go는 전용 `RootCAs` 풀, Java는 전용 truststore를 쓴다. 내부 서비스용 클라이언트는 기존 신뢰 설정을 유지하도록 따로 둔다. `NODE_EXTRA_CA_CERTS`는 기존 공인 CA 신뢰에 더하는 방식이라 쓰지 않는다. 환경변수만으로는 라이브러리가 이 조건을 지키는지 보장하지 못한다.
4. 앱의 실제 기능을 시험한다. 프록시 로그의 `http.host`로 트래픽이 지나가는지 확인한다.
5. 우회를 막으려면 `infrastructure/central-egress/opt-in-<app>.yaml`에 `canary.yaml`의 `route-through-egress-proxy`와 같은 NetworkPolicy를 앱 네임스페이스로 추가한다. `policyTypes`는 `Egress`만 두어 Traefik 수신에 영향을 주지 않게 하고, 앱이 쓰는 DB 같은 내부 목적지를 함께 허용한다.

인증서를 고정한 클라이언트와 외부 서버에 클라이언트 인증서를 제시하는 연결은 검사 프록시를 지나면 실패한다. 이런 앱은 예외를 만들지 말고 온보딩을 보류한다. 평문 HTTP는 처리하지 않으므로 `HTTP_PROXY`는 설정하지 않는다.

## 5. 외부 CA 번들 갱신

번들은 `tools/egress_ca_policy.json`에 고정한 certifi 휠에서 `blockedRoots`의 지문을 뺀 결과다. 차단 목록은 [eMudhra 사고의 `roots.json`](https://emudhra.we-have-a-problem.com/roots.json)에 있는 네 인증서이며, `server/verify_trust.py`의 목록을 모두 포함한다. eMudhra가 운영하는 나머지 루트는 [Python 보안 안내](https://discuss.python.org/t/information-for-python-users-regarding-emudhra-emsign-ca-certificate-security-incident/109576)가 영향이 없다고 밝힌 세 개만 `reviewedOperatorRoots`로 유지한다. 원본에 검토하지 않은 eMudhra 루트가 나타나면 생성이 실패한다.

1. 정책을 바꾼다. 원본을 올릴 때는 `source`의 버전, URL, SHA-256을 [PyPI에 공개된 값](https://pypi.org/project/certifi/)으로 바꾸고, 인증서를 차단할 때는 `blockedRoots`에 지문과 근거를 더한다.
2. 번들을 생성한다. 도구는 원본 해시와 차단 목록을 확인하고, 결과를 X.509 CA로 읽을 수 있을 때만 파일을 쓴다. 출력의 `added`, `removed`, `filtered`를 검토한다.

```bash
python3 tools/generate_egress_ca_bundle.py
python3 -m unittest tests.test_egress_proxy
```

3. 변경을 검토해 `main`에 병합한다. 이 시점부터는 다음 절의 일반 전환이 적용된다.

## 6. 전환과 긴급 차단

변경은 `Git → Argo CD 동기화 → kubelet 볼륨 갱신 → 게이트웨이 재적재` 순서로 반영된다. ConfigMap과 Secret을 `subPath` 없이 마운트하므로 Pod를 다시 만들지 않고 파일이 바뀐다. kubelet 갱신에는 보통 1~2분이 걸린다.

| 구분 | 일반 전환 | 긴급 전환 |
| --- | --- | --- |
| 쓰는 경우 | CA 추가, 정기 갱신, 설정 변경 | 신뢰하던 CA의 침해, 발급 CA 키 유출 |
| 방법 | 병합 후 기다린다 | 병합 후 노드에서 컨테이너를 즉시 멈추고 Pod를 교체한다 |
| 새 연결 | 재적재 후 새 정책 | 새 Pod에서 새 정책 |
| 유지 중인 연결의 다음 요청 | 새 정책으로 다시 연결한다 | 연결이 끊겨 앱이 재접속한다 |
| 진행 중인 스트림 | 끝날 때까지 이전 검증 결과로 유지한다 | 프로세스 종료를 확인한 시점에 끊겨 있다 |
| 프로세스 | 같은 PID 유지 | 이전 컨테이너 종료 후 새 Pod |

재적재가 실패하면 게이트웨이는 **이전 설정을 그대로 유지한다.** 차단하려던 CA가 계속 신뢰될 수 있고 Pod는 `Ready`로 남는다. 일반 전환 뒤에는 항상 지표를 확인한다.

```bash
kubectl -n central-egress port-forward "$POD" 15020:15020 &
curl -s localhost:15020/metrics | grep config_synchronized
kill %1
kubectl -n central-egress logs "$POD" --since=10m | grep -i 'failed to reload\|loaded config'
```

`config_synchronized`가 1이고 `loaded config` 로그가 변경 시각 뒤에 있어야 한다. 0이면 로그의 오류를 고칠 때까지 정책이 적용되지 않은 상태다. 이미지 교체는 새 Pod가 준비된 뒤 이전 Pod에 SIGTERM을 보낸다. 이전 Pod는 최소 5초, 최대 55초 동안 연결을 정리하고 남은 연결을 끊는다.

일반 Pod 삭제, `rollout restart`, 복제본 0으로의 축소는 모두 SIGTERM으로 시작하므로 진행 중인 연결이 최대 55초 더 유지된다. 강제 삭제(`--force`)는 API 객체만 지우고 프로세스 종료를 증명하지 않으므로 차단 완료의 근거로 쓰지 않는다. 긴급 전환은 다음 순서로 진행한다.

1. 5절로 차단을 커밋해 병합하고 Argo CD에 즉시 반영을 요청한다.
2. 클러스터의 번들이 Git과 같은지 확인한다. 먼저 교체하면 새 Pod가 이전 번들로 시작한다.
3. 이전 컨테이너의 ID를 저장하고 Pod 삭제를 요청한다. 삭제 중인 Pod는 컨테이너를 다시 시작하지 않으며 Deployment가 새 Pod를 만든다.
4. 노드에서 저장한 컨테이너를 유예 없이 멈춘다. `state`가 `CONTAINER_EXITED`이거나, kubelet이 이미 정리해 `NotFound`이면 종료된 것이다.
5. 이전 스트림을 쓰던 클라이언트의 연결이 닫혔는지, 새 Pod의 컨테이너 ID가 다른지 확인한다. 게이트 B의 명령으로 차단한 CA 체인이 거부되는지 확인한다.

```bash
kubectl -n argocd annotate application central-egress argocd.argoproj.io/refresh=hard --overwrite
kubectl -n central-egress get configmap egress-proxy-upstream-ca \
  -o jsonpath='{.metadata.annotations.egress-proxy\.homelab\.robinjoon\.xyz/bundle-sha256}{"\n"}'
grep bundle-sha256 infrastructure/central-egress/upstream-ca-bundle.yaml

CONTAINER_ID=$(kubectl -n central-egress get pod "$POD" -o jsonpath='{.status.containerStatuses[0].containerID}' | sed 's|.*://||')
kubectl -n central-egress delete pod "$POD" --wait=false

# k3s 노드에서 실행한다.
sudo k3s crictl stop --timeout 0 "$CONTAINER_ID"
sudo k3s crictl inspect "$CONTAINER_ID" | grep '"state"'
```

노드에 접속할 수 없으면 이전 프로세스의 종료를 확인할 수 없으므로 차단 완료를 선언하지 않는다. 이 경우 노드나 그 외부 네트워크를 물리적으로 격리한다.

Git이나 Argo CD를 쓸 수 없으면 프록시를 멈춰 새 연결을 실패로 돌린다. `selfHeal`이 되돌리지 않도록 Root Application의 자동 동기화부터 끈다. 축소는 일반 종료이므로 기존 연결이 최대 55초 유지되고, 즉시 끊으려면 위의 컨테이너 중지를 함께 실행한다. 프록시를 쓰는 앱의 외부 연결은 복구할 때까지 실패한다.

```bash
kubectl -n argocd patch application root-apps --type merge -p '{"spec":{"syncPolicy":{"automated":null}}}'
kubectl -n argocd patch application central-egress --type merge -p '{"spec":{"syncPolicy":{"automated":null}}}'
kubectl -n central-egress scale deployment egress-proxy --replicas=0
```

Git을 고친 뒤 Root Application의 자동 동기화를 되살리면 나머지가 선언대로 복구된다.

```bash
kubectl -n argocd patch application root-apps --type merge \
  -p '{"spec":{"syncPolicy":{"automated":{"prune":true,"selfHeal":true}}}}'
```

## 7. 검사 CA 교체

발급 CA는 만료 전에 1절의 명령으로 같은 루트 아래 새로 발급해 Secret을 교체한다. 앱은 바꾸지 않는다. 파일 두 개가 한 번에 바뀌므로 인증서와 키가 어긋나지 않는다. 기존 연결은 이전 리프 인증서를 유지한다. 키 유출이면 Secret을 교체한 뒤 6절의 긴급 전환으로 이전 프로세스를 멈춘다.

```bash
kubectl -n central-egress create secret generic egress-proxy-dynamic-ca \
  --from-file=issuer.crt --from-file=issuer.key --dry-run=client -o yaml | kubectl apply -f -
```

교체 후 6절의 지표와 게이트 B의 `issuer:` 줄을 확인한다.

루트 교체는 이유에 따라 절차가 다르다.

| 구분 | 정기 교체 | 루트 키 침해 |
| --- | --- | --- |
| 공개 루트 | `ca.crt`에 이전 루트와 새 루트를 함께 넣는다 | `ca.crt`를 새 루트만으로 즉시 바꾼다 |
| 앱 | 재시작해 두 루트를 읽게 한다 | 재시작할 때까지 프록시 경유 연결이 실패한다 |
| 발급 CA | 앱 재시작 후 새 루트 아래 발급 CA로 교체한다 | 새 루트 아래 발급 CA로 먼저 교체하고 6절의 긴급 전환을 실행한다 |
| 마지막 단계 | 이전 루트를 빼고 앱을 다시 재시작한다 | 없음. 공존 기간을 두지 않는다 |
| 영향 | 중단 없음 | 모든 앱을 재시작할 때까지 중단을 받아들인다 |

침해된 루트를 앱이 신뢰하는 동안에는 누구나 앱을 속일 수 있으므로 공존 기간을 두면 안 된다.

## 8. 롤백

1. 앱 하나를 되돌릴 때는 `opt-in-<app>.yaml`을 먼저 지우고, 앱의 patch를 되돌린 뒤, `network-policy.yaml`에서 네임스페이스를 뺀다. 이 순서를 어기면 앱의 외부 연결이 끊긴다.
2. 이미지나 설정은 해당 커밋을 `git revert`로 되돌린다. 이전 이미지 digest가 레지스트리에 남아 있어야 한다.
3. 프록시를 없앨 때는 모든 앱을 되돌린 뒤 `argocd/managed/apps/central-egress.yaml`을 지운다. Application의 finalizer가 선언한 리소스를 지운다. Git 밖의 Secret은 남으므로 `kubectl delete namespace central-egress`로 정리한다.

CA 번들을 되돌릴 때 `blockedRoots`를 줄이거나 기본 번들로 바꾸지 않는다. `git revert`는 차단 목록을 줄이지 않는 커밋에만 쓴다.

## 제약

- 복제본이 하나이고 노드가 하나여서 고가용성이 없다. 긴급 전환 중에는 프록시를 쓰는 앱의 외부 연결이 끊긴다.
- 게이트 A는 내부 주소만 확인한다. 홈 네트워크의 공인 IP로 나갔다 돌아오는 경로는 차단 목록에 없으며, Traefik이 공개하는 서비스의 인증에 의존한다.
- `simple-k3s-harness.dev/workload` 라벨 때문에 `shared-db-app`도 두 네임스페이스에 복제된다. 프록시 Pod는 이 Secret을 마운트하지 않고 ServiceAccount 토큰도 받지 않는다.
- 접근 로그에서 `http.path`를 지웠지만 접속 호스트는 남는다. 복호화한 본문과 헤더는 기본 로그에 기록하지 않는다.
- 클러스터가 단일 스택이면 IPv6 목적지는 연결에 실패한다. DNS는 IPv4를 먼저 쓰고 A 레코드가 없을 때만 AAAA를 쓴다.
