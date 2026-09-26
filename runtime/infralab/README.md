# infralab: the Infra Lab's simulators

The Infra Lab teaches Terraform, Docker, VM monitoring and Kubernetes without a cloud account, a Docker daemon or a
cluster. Everything here is a **simulation**: nothing is provisioned, built, pulled, run or deployed, and no real
`terraform`, `docker`, `kubectl` or `az` is started, even when one is installed. The learner's files (HCL,
Dockerfile, compose YAML, Kubernetes YAML) are read by whitelisted readers and never executed.

## Truth

| Piece | Truth |
| --- | --- |
| The learner's work | Real files edited in VS Code, and commands typed in the Infra Lab shell (a VS Code Pseudoterminal owned by the extension: it spawns no process and sends each line to `POST /api/local/infra/command`). |
| Terraform (`terraform.py`, `hcl.py`, `tfexpr.py`, `azurerm.py`) | HCL parsed into a syntax tree and evaluated over plain values with a function whitelist. Plans and applies run against a simulated azurerm provider (a documented subset of real resource types and arguments, 4.x) and a simulated subscription. `terraform.tfstate` is written next to the files, in Terraform's v4 layout, marked `datapass_simulated`. Local modules are read from their folders and flattened into one graph (addresses `module.<call>.<type>.<name>`, each module evaluated in its own scope). `terraform fmt -check` compares each file with the layout `tffmt.py` computes (hclwrite's rules for a documented subset); the lab never rewrites a file. |
| Docker (`docker.py`) | The Dockerfile is read line by line; `RUN` is text whose effect (size, duration) is estimated from what it names. COPY hashes the real context files after `.dockerignore`, so the layer cache behaves like BuildKit's. Containers, health checks, published ports and compose (networks, named volumes) are records; the app's behaviour (port, required environment, health path, the rows it writes to its database) comes from the mission and the image's CMD. Names resolve only between services that share a network; a container only on `internal: true` networks publishes no port. A database keeps its rows in the named volume or bind mount on its data directory, else in the image's anonymous volume, which `docker compose down` throws away with the container. Lint ids `DL…` follow hadolint's; `DP…` are the lab's own. |
| VM and monitoring (`monitor.py`) | A subset of `az` on the simulated subscription. Metrics are a recorded scenario per resource (base level, deterministic noise, incidents at fixed times). Alert rules are stored in the subscription; `lab alerts replay` evaluates them as Azure Monitor evaluates static metric alerts (aggregation over the window, every evaluation frequency, resolved after three evaluations without the condition). |
| Kubernetes (`kube.py`, `ingress.py`, `autoscale.py`) | Manifests read with `yaml.safe_load_all` and validated strictly (unknown fields refused) for Deployment, Service, ConfigMap, Namespace, Ingress (`networking.k8s.io/v1`) and HorizontalPodAutoscaler (`autoscaling/v2`); `kubectl apply` reports an invalid object and applies the others. A deterministic controller schedules pods on nodes by their requests, pulls images from the lab's registry (with the app's behaviour: port, health path, start time, crash), and rolls deployments out in five-second steps with maxSurge, maxUnavailable, readiness probes and the progress deadline. Each rollout records the fewest pods that really answered traffic. The ingress controller is a record of the mission (its classes and public address): `curl http://<host>/<path>` is routed as ingress-nginx routes it (class, host, `Exact`/`Prefix` paths, longest match, the Service port by number or name) and answered from the simulated pods. The HPA reacts only to a recorded CPU demand curve that `lab load replay` plays in 15-second syncs (utilization over the pod's CPU request, 10 % tolerance, the default scale-up and scale-down behaviour or the HPA's own, min/max, scheduling by requests); a pod above its CPU limit counts as overloaded. |
| The world (`world.py`) | `<folder>/.infralab/world.json`: plain JSON, deterministic (fixed ids, a simulated clock each command advances). `journal.jsonl` next to it records each command line, its exit code and a summary; the mission checker reads it. |

## The shell (`shell.py`)

One line at a time, split like a POSIX shell (quotes, no expansion). Routed to `terraform`, `docker`, `kubectl`, `az`,
`curl` (reaches a simulated container through its published port, or the cluster through its ingress controller
when the host is not localhost) and the lab's own `lab status`, `lab alerts replay` and `lab load replay`, plus `ls`,
`cat`, `pwd`, `help`. Pipes, redirections, `&&`, variables and command substitution
are refused; `bash`, `python`, `git` and other real programs are refused with a pointer to a normal terminal.
`terraform apply` and `destroy` without `-auto-approve` return a `prompt`; the terminal sends the answer back with
the same line.

## Supported subsets

- **Terraform**: `terraform` (required_providers, local backend only), `provider "azurerm"` (needs `features {}`),
  `variable` (type constraints, default, validation, sensitive, nullable), `locals`, `resource`, `data`
  (`azurerm_client_config`, `azurerm_resource_group`, `azurerm_storage_account`), `output`, `moved`, `import`;
  `count`, `for_each` (a map or a set of strings, as Terraform demands), `depends_on`, `lifecycle`; `.tfvars`,
  `*.auto.tfvars`, `-var`, `-var-file`; local `module` blocks (`source` starting with `./` or `../` inside the
  folder, inputs checked against the child's variables, `module.<call>.<output>`, `depends_on`, nesting up to three
  levels; `init` installs them and a new or moved call needs `init` again; `moved` and `import` blocks stay in the
  root module with full addresses). Commands: `init`, `validate`, `plan` (`-destroy`), `apply`, `destroy`, `import`,
  `state list|show|mv|rm`, `output` (`-raw`, `-json`), `show`, `version`, `fmt -check|-diff|-recursive|-list=false`
  (exit 3 when a file would change; plain `fmt` lists the files and changes nothing). `fmt` covers indentation, `=`
  and trailing-comment alignment, spacing around `=`, `=>`, commas, brackets and single-line braces, block headers
  and trailing whitespace; spacing around other operators, heredoc bodies and `/* */` comments are left as written.
  Refused: registry and Git modules, `count`/`for_each`/`providers`/`version` on a module, remote backends,
  provisioners, saved plans, `-target`. Resource types: `azurerm_resource_group`,
  `azurerm_storage_account`, `azurerm_storage_container` (with `storage_account_id`), `azurerm_virtual_network`,
  `azurerm_subnet`, `azurerm_key_vault`, `azurerm_data_factory`. Apply errors follow azurerm's wording: a resource
  that already exists must be imported, storage and key vault names are unique across Azure, a resource group that
  still holds resources is not deleted, a subnet must fit in its network.
- **Docker**: `build` (`-t`, `-f`, `--build-arg`, `--no-cache`), `images`, `history`, `run` (`-d`, `--name`, `-p`,
  `-e`), `ps`, `logs`, `stop`, `rm`, `rmi`, `volume ls|rm|inspect`, `network ls|inspect`, `compose up|ps|logs|down
  [-v]` (services with `image` or `build`, `ports`, `environment`, `depends_on` with conditions, `healthcheck`,
  `command`, `networks` as a list or a map, `volumes` in short or long syntax; top-level `networks` with `internal`
  and top-level `volumes`; an undeclared network or volume is refused as compose refuses it). Base images come from
  a small simulated registry.
- **az**: `login`, `account show`, `group list|show`, `resource list`, `vm list|show|restart|start|stop|deallocate`,
  `monitor metrics list-definitions|list`, `monitor action-group list`, `monitor metrics alert
  create|update|list|show|delete`. Resources may be named instead of given by id (a lab convenience).
- **kubectl**: `apply -f`, `get` (pods, deploy, rs, svc, endpoints, ingress, hpa, ingressclass, nodes, configmaps,
  namespaces, events, all; `-o wide|json`, `--show-labels`, `-A`), `describe pod|deployment|service|ingress|hpa`,
  `logs`, `rollout status|history|undo|restart`, `scale`, `set image`, `create namespace`, `delete` (a namespace
  takes its objects with it), `-n`. Ingress: rules with `host`, `http.paths` (`path`, `pathType`, a `service`
  backend by port number or name), `defaultBackend`, `ingressClassName`, `tls` (accepted, not terminated). HPA:
  `scaleTargetRef` a Deployment, `minReplicas`, `maxReplicas`, `Resource` metrics with a `Utilization` target,
  `behavior` (stabilization windows, `Pods`/`Percent` policies, `selectPolicy`). A CPU limit without a request sets
  the request, as the API server does.

Missions (`content/missions/infra-v1`) use it through `runtime/missionlab/infra.py`; see `runtime/missionlab/README.md`.
