# Enabling Portainer Integration in dockwatch

Connects dockwatch to a Portainer instance so it can discover, check,
restart, update, and delete containers on hosts managed through Portainer
— not just containers on the same Docker socket dockwatch runs on.

## Prerequisites

- A running Portainer CE/BE instance dockwatch's container can reach over HTTP(S)
- A Portainer user with API access (admin, or a user with access to the
  target environment(s))
- The Docker/Swarm environment(s) you want watched already added in Portainer

## Step 1 — Generate a Portainer API key

1. Log into Portainer.
2. Click your user icon (top right) → **My account**.
3. Scroll to **Access tokens** → **Add access token**.
4. Give it a description (e.g. `dockwatch`), confirm your password when prompted.
5. Copy the raw key immediately — Portainer only shows it once. It looks like:
   `ptr_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX=`

## Step 2 — Network reachability

dockwatch's container needs a route to Portainer's API port (default HTTPS
`9443`, or HTTP if you run Portainer with `--http-enabled`).

- **Same Docker host, different compose stacks**: put both on a shared
  Docker network so dockwatch can reach Portainer by container name:
  ```
  docker network connect <dockwatch-network> portainer
  ```
- **Separate hosts**: use Portainer's reachable LAN/VPN address instead of a container name.
- **Self-signed cert**: dockwatch verifies TLS by default. Either give
  Portainer a real cert, or run Portainer with `--http-enabled` and use
  `http://` for local/trusted-network setups only — do not expose that
  port to the internet.

## Step 3 — Configure dockwatch

In the dockwatch dashboard: **Settings → Advanced → Portainer**.

| Field | Value |
|---|---|
| Enabled | on |
| URL | `https://portainer.example.com:9443` (or `http://portainer:9000` for local HTTP) |
| API Key | the `ptr_...` key from Step 1 |

Click **Test Connection** — a successful test lists the Portainer
environments dockwatch can see. Save.

## Step 4 — Verify

1. Dashboard toolbar → switch source to **Portainer**.
2. Click **Check now**. Containers from every environment Portainer manages
   should appear, tagged with a `portainer` badge and their environment name.
3. Confirm actions work per container:
   - **Restart** — always available for Portainer-sourced containers.
   - **Update** — only shown for containers deployed as a Portainer **stack**
     (i.e. via compose, not a bare `docker run`); rewrites the stack's image
     tag and redeploys through Portainer.
   - **Delete container** — works for any Portainer-sourced container.
   - **Delete image** — local-only by design; not available on Portainer rows.

## Restricting to specific environments

If Portainer manages environments you don't want dockwatch touching, list
the ones to include under **Settings → Advanced → Portainer → Environments**
(by ID). Leave empty to watch every environment the API key can see.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `certificate verify failed: self-signed certificate` | Portainer's TLS cert isn't trusted. Use a real cert, or switch to HTTP on a trusted network. |
| `portainer environments request failed` on Test Connection | URL unreachable from inside dockwatch's container — check the network/DNS name, not just from your host machine. |
| Container shows up but Update button is missing | Container wasn't deployed as a Portainer stack (no compose labels) — only restart/delete are supported for it. |
| Container shows `registry: unknown` and never goes outdated | Fixed as of the version that resolves image digests via Portainer's image list; upgrade if you're on an older build. |
