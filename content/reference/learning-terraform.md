# Terraform

Cheatsheet for the Learning path *Infrastructure and DevOps for data*. The Infra Lab evaluates HCL with a whitelisted
reader against a simulated azurerm provider and subscription; its `terraform.tfstate` is marked as simulated and
nothing is provisioned.

## Workflow

| Command | Does |
|---|---|
| `terraform init` | downloads providers and modules, configures the backend |
| `terraform fmt` / `validate` | formats / checks the configuration |
| `terraform plan -out=tfplan` | compares configuration with refreshed state, proposes changes |
| `terraform apply tfplan` | applies exactly the reviewed plan |
| `terraform destroy` | removes everything in the state |
| `terraform state list` / `show` | inspects the state |

## Reading a plan

| Symbol | Meaning |
|---|---|
| `+` | create |
| `~` | update in place |
| `-/+` | destroy, then create a replacement (an argument forces a new resource) |
| `+/-` | create the replacement first (`create_before_destroy`) |
| `-` | destroy |

Replacing a storage account or database starts it empty: read every `-/+` line.

## State

- Maps each resource address to a real object. Keep it in a **remote backend with locking** (azurerm: a storage
  account container) so the team shares it and concurrent applies are blocked.
- Contains attribute values in plain text, including those marked `sensitive = true` (which only hides output).
  Restrict access to the backend.
- Never edit it by hand; use `terraform import`, `moved` blocks or `terraform state mv`.

## Language

- `variable`, `locals`, `output`, `module`, `data` sources.
- `for_each` keys instances by name (`zones["raw"]`); `count` by index (removing one renumbers the rest).
- `depends_on` only for dependencies Terraform cannot see from references.
- Pin provider versions: `required_providers { azurerm = { source = "hashicorp/azurerm", version = "~> 4.0" } }`.
