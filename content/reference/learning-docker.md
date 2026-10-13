# Docker

Cheatsheet for the Learning path *Infrastructure and DevOps for data*. The Infra Lab reads Dockerfiles and compose
files and simulates builds, the layer cache and containers: nothing is built, pulled or run.

## Images and containers

- **Image**: read-only stack of layers, one per instruction (`FROM`, `RUN`, `COPY`...). Tagged `name:tag`; pin tags.
- **Container**: an instance of an image plus its own writable layer. Removing it removes that layer.
- **Volume**: storage that outlives containers (named volume or bind mount).

## Dockerfile

```dockerfile
FROM python:3.12-slim                 # small, pinned base
WORKDIR /app
COPY requirements.txt .               # changes rarely: cached
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/                      # changes often: last
USER 1000                             # not root
ENTRYPOINT ["python", "-m", "src.ingest"]
CMD ["--day", "today"]                # default arguments
```

- A changed layer rebuilds every later layer: order from least to most frequently changed.
- `docker run image --day 2026-10-01` replaces `CMD`; exec-form `ENTRYPOINT` receives the arguments.
- `.dockerignore` keeps `.git`, `.env`, data and caches out of the build context.
- Never bake secrets into an image; pass them at run time.

## Compose

| Key | Remember |
|---|---|
| `depends_on` | orders start only |
| `condition: service_healthy` | waits for the dependency's `healthcheck` to pass |
| `volumes:` | named volumes keep data across `down`/`up` (not across `down -v`) |
| `env_file:` | keep the file out of Git |
| `ports: "8080:80"` | host:container |

## Commands

`docker build -t ingest:1.0 .` · `docker run --rm ingest:1.0` · `docker ps -a` · `docker logs <c>` ·
`docker exec -it <c> sh` · `docker compose up -d` · `docker compose down` · `docker image ls`
