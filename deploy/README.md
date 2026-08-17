# Deployment

**Live:** the app runs on the project's own VPS, alongside two unrelated
services, behind Caddy. That is the only deployment that exists.

| File | Status |
|---|---|
| `shade-route.service` | **Live.** systemd unit on the VPS: uvicorn on `127.0.0.1:8010`, unprivileged `shaderoute` user, `MemoryMax=2G`, `CPUWeight=20`. |
| `../Dockerfile` | **Supported.** Not how the live site runs, but it is the "clone and run on a clean machine" path the brief requires, and it works on any container host. |
| `SPACE_README.md`, `deploy_hf_space.sh` | **Unused fallback.** A Hugging Face Space was prepared before the VPS was chosen. Kept only as a same-day escape hatch if the VPS is unavailable during judging. |

`render.yaml` and a `keep-warm` GitHub Action were deleted: both existed purely
to work around free-tier cold starts on a host that is not being used, and dead
infrastructure config that looks live is worse than no config.

## Why the VPS rather than a free tier

Free tiers sleep. Render's free web service spins down after 15 minutes idle and
takes about a minute to wake — a judge clicking the link and waiting a minute has
already formed an opinion. The VPS is always on, and the custom domain is free.

## Adding the site to Caddy safely

Caddy already serves a live site from this box, so the new block goes in without
any possibility of taking that down:

```bash
cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak.$(date +%s)   # 1. back up
#    2. append the new block as its own top-level block; do not edit the existing one
caddy validate --config /etc/caddy/Caddyfile                   # 3. must pass first
systemctl reload caddy                                         # 4. reload, never restart
curl -I https://ghostbus.tech                                  # 5. neighbour still up?
```

`reload` parses the new config in a new process and only swaps traffic if it
succeeds, so a bad edit leaves the running config serving. Roll back by copying
the backup over and reloading again.
