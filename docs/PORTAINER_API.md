# Portainer Integration — Feature & API Reference

See [PORTAINER_SETUP.md](PORTAINER_SETUP.md) first if you just need to
connect dockwatch to a Portainer instance. This doc covers what the
integration actually supports and how to script against it directly.

## What's supported

- **Discovery & checking**: fully supported. Reads environments and containers via the Portainer API (`X-API-Key` header), then runs the normal comparison pipeline against them exactly as it would for local containers.
- **Restart**: supported — proxied through Portainer's Docker API (`POST .../docker/containers/{id}/restart`).
- **Delete**: supported — container deletion and (for local containers) image deletion, with confirmation and audit logging.
- **Full update (pull + recreate)**: supported for Portainer-managed compose stacks. When you click Update on a Portainer-sourced container, here's what happens:

  1. **Build update plan** — verifies the container is Portainer-managed, compose-backed, not pinned, and that the comparison result is valid (digest-backed for floating tags).
  2. **Find the stack** — queries Portainer `GET /api/stacks` filtered by the stack name (the compose project name from container labels).
  3. **Read the stack file** — fetches the current compose file via Portainer `GET /api/stacks/{id}/file`.
  4. **Rewrite the image tag** — finds the service's `image:` line and replaces the old tag with the new one (e.g. `nginx:1.25` → `nginx:1.27`).
  5. **Redeploy via Portainer** — `PUT /api/stacks/{id}` with the updated file, `pullImage: true`, and `prune: true`. Portainer pulls the new image and recreates only the changed service, leaving sibling services untouched.

  Non-compose Portainer containers are restart-only — the full update path requires compose stack metadata.

  **Timeout caveat**: step 5 (`create_stack`/`update_stack`) blocks on Portainer's synchronous pull-and-recreate, which can take well over a few seconds for a real image pull. These two calls use a dedicated `portainer.deploy_timeout` (default 120s, configurable in Settings or `config.toml`) separate from the short timeout used for restart/delete/list calls. If a redeploy still times out on very large images, Portainer generally finishes the deploy server-side anyway — check the container/stack state in Portainer before retrying, since a retry against an in-flight or already-completed deploy can produce duplicate or conflicting stack state.
- **Source detection**: containers deployed via Portainer stacks get `/data/compose/{id}/` labels. Dockwatch detects these automatically and tags them as `source=portainer`, even when discovered via the local Docker socket. The dashboard's Local / Portainer / All filter groups containers by their actual deployment source, not just whichever API happened to query them.

## Programmatic Stack Deployment

The `PortainerClient` class in `dockwatch.integrations.portainer` supports creating stacks from compose content:

```python
from dockwatch.integrations import PortainerClient

client = PortainerClient(base_url="http://portainer:9000", api_key="ptr_...")
stack = await client.create_stack(
    name="my-stack",
    stack_file_content="version: '3.8'\nservices:\n  web:\n    image: nginx:alpine\n",
    env=[{"name": "TAG", "value": "alpine"}],
    endpoint_id=1,
)
# stack["Id"] -> Portainer stack ID
# stack["ProjectPath"] -> /data/compose/{id}
```

**Real-world example** — deploy a compose file from disk, reading env vars from an adjacent `.env`:

```python
# deploy_to_portainer.py
import asyncio, json, os, sys
from dockwatch.integrations import PortainerClient

PORTAINER_URL = os.environ["PORTAINER_URL"]       # e.g. http://portainer:9000
PORTAINER_KEY = os.environ["PORTAINER_API_KEY"]   # e.g. ptr_...
ENDPOINT_ID   = int(os.environ.get("PORTAINER_ENDPOINT", "1"))
STACK_NAME    = sys.argv[1]                       # project name
COMPOSE_FILE  = sys.argv[2]                       # path to docker-compose.yml

compose = open(COMPOSE_FILE).read()

# Read .env from same directory, convert to Portainer's [{name, value}] format
env_file = os.path.join(os.path.dirname(COMPOSE_FILE), ".env")
env_vars = []
if os.path.isfile(env_file):
    for line in open(env_file):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env_vars.append({"name": k, "value": v})

async def main():
    client = PortainerClient(base_url=PORTAINER_URL, api_key=PORTAINER_KEY)
    stack = await client.create_stack(
        name=STACK_NAME,
        stack_file_content=compose,
        env=env_vars,
        endpoint_id=ENDPOINT_ID,
    )
    print(f"Stack created: ID={stack['Id']}, path={stack['ProjectPath']}")

asyncio.run(main())
```

Usage:

```bash
export PORTAINER_URL=http://portainer:9000
export PORTAINER_API_KEY=ptr_yourkeyhere
python deploy_to_portainer.py plausible ./stacks/plausible/compose.yml
# Stack created: ID=3, path=/data/compose/3
```

Other programmatic Portainer operations:

| Method | Description |
|--------|-------------|
| `list_environments()` | List all Portainer environments |
| `list_containers(endpoint_id)` | List containers on an endpoint |
| `list_images(endpoint_id)` | List images on an endpoint |
| `restart_container(endpoint_id, container_id)` | Restart a container via Docker API proxy |
| `delete_container(endpoint_id, container_id, force)` | Delete a container |
| `delete_image(endpoint_id, image_id, force)` | Delete an image |
| `find_stack_by_name(name)` | Look up a stack by its compose project name |
| `get_stack_file(stack_id)` | Read a stack's compose file content |
| `create_stack(name, stack_file_content, env, endpoint_id)` | Create a new stack from compose content (uses `deploy_timeout`) |
| `update_stack(stack_id, endpoint_id, stack_file_content, env)` | Redeploy a stack with updated compose content (uses `deploy_timeout`) |

`PortainerClient(base_url, api_key, timeout=15.0, deploy_timeout=120.0)` — `timeout` covers restart/delete/list calls; `deploy_timeout` covers `create_stack`/`update_stack` only, since those block on Portainer's image pull.

```bash
dockwatch environments                              # list Portainer environments
dockwatch check --source portainer --environment 2  # check one environment
dockwatch check --source all                        # local + Portainer together
```
