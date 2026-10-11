# Kubernetes

Cheatsheet for the Learning path *Infrastructure and DevOps for data*. The Infra Lab validates manifests strictly and
applies them to a simulated cluster (scheduling, readiness, rollouts); no real cluster or kubectl is used.

## Objects

| Object | Role |
|---|---|
| Pod | one or more containers scheduled together |
| Deployment | desired state for stateless pods; manages ReplicaSets and rollouts |
| ReplicaSet | keeps N pods of one template running |
| StatefulSet | stable names and storage per pod (databases, brokers) |
| Job / CronJob | run to completion / on a schedule |
| Service | stable virtual IP and DNS for a set of pods; default type **ClusterIP** |
| Ingress | HTTP routing from outside to Services |
| ConfigMap / Secret | configuration / sensitive values (base64, not encrypted by default) |

## Probes and resources

- **Readiness** failing: pod removed from Service endpoints, not restarted. Rollouts wait for readiness.
- **Liveness** failing: kubelet restarts the container. Keep it cheap and independent of dependencies.
- **Startup** probe: delays the other probes for slow starters.
- `requests`: what the scheduler reserves. `limits`: memory over limit = **OOMKilled**; CPU over limit = throttled.

## Rollouts

`strategy.rollingUpdate.maxSurge` (extra pods allowed) and `maxUnavailable` (pods that may be missing).
`kubectl rollout status deploy/x` · `kubectl rollout undo deploy/x` · `kubectl rollout history deploy/x`.

## Pod states to recognise

| State | Look at |
|---|---|
| `Pending` | no node fits the requests, or a volume cannot bind: `kubectl describe pod` events |
| `ImagePullBackOff` | wrong image name or tag, or registry credentials |
| `CrashLoopBackOff` | the container exits after starting: `kubectl logs --previous` and the exit code |
| `OOMKilled` | memory limit too low or a leak |
| Running but not Ready | readiness probe failing |

`kubectl get pods -o wide` · `kubectl describe pod <p>` · `kubectl logs <p> -c <container>` · `kubectl apply -f <file>`
