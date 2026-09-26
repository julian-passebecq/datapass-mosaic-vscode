# infralab: the Infra Lab's simulators

The Infra Lab teaches Terraform, Docker, VM monitoring and Kubernetes without a cloud account, a Docker daemon or a
cluster. Everything here is a **simulation**: nothing is provisioned, built, pulled, run or deployed, and no real
`terraform`, `docker`, `kubectl` or `az` is started, even when one is installed. The learner's files (HCL,
Dockerfile, compose YAML, Kubernetes YAML) are read by whitelisted readers and never executed.

## Truth

| Piece | Truth |
| --- | --- |
| The learner's work | Real files edited in VS Code, and commands typed in the Infra Lab shell (a VS Code Pseudoterminal owned by the extension: it spawns no process and sends each line to `POST /api/local/infra/command`). |
| Terraform (`terraform.py`, `hcl.py`, `tfexpr.py`, `azurerm.py`) | HCL parsed into a syntax tree and evaluated over plain values with a function whitelist. Plans and applies run against a simulated azurerm provider (a documented subset of real resource types and arguments, 4.x) and a simulated subscription. `terraform.tfstate` is written next to the files, in Terraform's v4 layout, marked `datapass_simulated`. |
| Docker (`docker.py`) | The Dockerfile is read line by line; `RUN` is text whose effect (size, duration) is estimated from what it names. COPY hashes the real context files after `.dockerignore`, so the layer cache behaves like BuildKit's. Containers, health checks, published ports and compose are records; the app's behaviour (port, required environment, health path) comes from the mission and the image's CMD. Lint ids `DL…` follow hadolint's; `DP…` are the lab's own. |
| VM and monitoring (`monitor.py`) | A subset of `az` on the simulated subscription. Metrics are a recorded scenario per resource (base level, deterministic noise, incidents at fixed times). Alert rules are stored in the subscription; `lab alerts replay` evaluates them as Azure Monitor evaluates static metric alerts (aggregation over the window, every evaluation frequency, resolved after three evaluations without the condition). |
| Kubernetes (`kube.py`) | Manifests read with `yaml.safe_load_all` and validated strictly (unknown fields refused) for Deployment, Service, ConfigMap and Namespace. A deterministic controller schedules pods on nodes by their requests, pulls images from the lab's registry (with the app's behaviour: port, health path, start time, crash), and rolls deployments out in five-second steps with maxSurge, maxUnavailable, readiness probes and the progress deadline. Each rollout records the fewest pods that really answered traffic. |
| The world (`world.py`) | `<folder>/.infralab/world.json`: plain JSON, deterministic (fixed ids, a simulated clock each command advances). `journal.jsonl` next to it records each command line, its exit code and a summary; the mission checker reads it. |

## The shell (`shell.py`)

One line at a time, split like a POSIX shell (quotes, no expansion). Routed to `terraform`, `docker`, `kubectl`, `az`,
`curl` (reaches a simulated container through its published port) and the lab's own `lab status` and
`lab alerts replay`, plus `ls`, `cat`, `pwd`, `help`. Pipes, redirections, `&&`, variables and command substitution
are refused; `bash`, `python`, `git` and other real programs are refused with a pointer to a normal terminal.
`terraform apply` and `destroy` without `-auto-approve` return a `prompt`; the terminal sends the answer back with
the same line.

## Supported subsets

- **Terraform**: `terraform` (required_providers, local backend only), `provider "azurerm"` (needs `features {}`),
  `variable` (type constraints, default, validation, sensitive, nullable), `locals`, `resource`, `data`
  (`azurerm_client_config`, `azurerm_resource_group`, `azurerm_storage_account`), `output`, `moved`, `import`;
  `count`, `for_each` (a map or a set of strings, as Terraform demands), `depends_on`, `lifecycle`; `.tfvars`,
  `*.auto.tfvars`, `-var`, `-var-file`. Commands: `init`, `validate`, `plan` (`-destroy`), `apply`, `destroy`,
  `import`, `state list|show|mv|rm`, `output` (`-raw`, `-json`), `show`, `version`. Refused: modules, remote backends,
  provisioners, saved plans, `-target`, `fmt` (it would rewrite files). Resource types: `azurerm_resource_group`,
  `azurerm_storage_account`, `azurerm_storage_container` (with `storage_account_id`), `azurerm_virtual_network`,
  `azurerm_subnet`, `azurerm_key_vault`, `azurerm_data_factory`. Apply errors follow azurerm's wording: a resource
  that already exists must be imported, storage and key vault names are unique across Azure, a resource group that
  still holds resources is not deleted, a subnet must fit in its network.
- **Docker**: `build` (`-t`, `-f`, `--build-arg`, `--no-cache`), `images`, `history`, `run` (`-d`, `--name`, `-p`,
  `-e`), `ps`, `logs`, `stop`, `rm`, `rmi`, `compose up|ps|logs|down` (services with `image` or `build`, `ports`,
  `environment`, `depends_on` with conditions, `healthcheck`, `command`). Base images come from a small simulated
  registry.
- **az**: `login`, `account show`, `group list|show`, `resource list`, `vm list|show|restart|start|stop|deallocate`,
  `monitor metrics list-definitions|list`, `monitor action-group list`, `monitor metrics alert
  create|update|list|show|delete`. Resources may be named instead of given by id (a lab convenience).
- **kubectl**: `apply -f`, `get` (pods, deploy, rs, svc, endpoints, nodes, configmaps, namespaces, events, all;
  `-o wide|json`, `--show-labels`), `describe pod|deployment|service`, `logs`, `rollout status|history|undo|restart`,
  `scale`, `set image`, `delete`, `-n`.

Missions (`content/missions/infra-v1`) use it through `runtime/missionlab/infra.py`; see `runtime/missionlab/README.md`.
