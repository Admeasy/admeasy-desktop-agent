# Deploy `live_state_block` fix to Lightsail (admeasy-ai-assistant)

Production today reports `git_sha` from `GET /health` (e.g. `45d191e`). The Reddit employee crash is in **`admeasy-ai-assistant`**, not `admeasy-desktop-agent`.

## 1. Clone and branch (on a machine with GitHub access to the private repo)

```bash
git clone git@github.com:Admeasy/admeasy-ai-assistant.git
cd admeasy-ai-assistant
git fetch origin main
git checkout main
git pull --rebase origin main
```

## 2. Apply the fix

**Minimum (one line in `_structured_plan`):**

```python
access_summary=getattr(session, "live_state_block", "") or "",
```

**Proper:** add to the `Session` dataclass (wherever it is defined — often `backend/app/session.py` or `backend/app/agent_impl.py`):

```python
live_state_block: str = ""
```

See also `docs/patches/admeasy-ai-assistant-live_state_block.patch` in **admeasy-desktop-agent** (reference).

## 3. Test locally (optional)

```bash
cd backend
pytest tests/ -q -k "session or structured"   # adjust to your tree
```

## 4. Commit and push `main`

```bash
git add -A
git commit -m "Fix Session.live_state_block for _structured_plan (Reddit employee runs)"
git push origin main
```

## 5. Deploy to Lightsail

Requires AWS CLI + Docker, region **ap-south-1**, service **admeasy-backend**:

```bash
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=ap-south-1
./scripts/deploy_lightsail_main.sh
```

The script builds `backend/Dockerfile` with `GIT_SHA=$(git rev-parse --short HEAD)`, pushes via `aws lightsail push-container-image`, merges env from the current deployment, and runs `create-container-service-deployment`.

## 6. Verify

```bash
curl -sS "https://admeasy-backend.6h5y8j39qxdcg.ap-south-1.cs.amazonlightsail.com/health" | jq '{ok, git_sha, image}'
```

Re-run the employee schedule or WhatsApp: **Run reddit ai employee work 2**. LangSmith should show no `live_state_block` traceback and write tools (`REDDIT_CREATE_REDDIT_POST` / `REDDIT_POST_REDDIT_COMMENT`) when instructions require them.

## What this cloud agent already did

- **admeasy-desktop-agent** `main` is pushed (`1b529f9`): reference `Session.live_state_block` + docs only.
- This agent **cannot** clone `admeasy-ai-assistant` (token: repository not found) or run Lightsail deploy (no AWS CLI/credentials on the VM).
