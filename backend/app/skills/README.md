# Device skills (playbooks)

Skills are **not** intent routing. They are markdown playbooks the model may retrieve when using `device_*` tools (e.g. “LinkedIn export”, “Instagram research”, “WhatsApp desktop read”).

Planned: `registry.py` loads `*.md` from this folder or Supabase `device_skills`, ranks by goal text, injects into tool context. Until wired, keep procedures in tool descriptions honest and use `WORKFLOW_DIAGNOSIS.md`.
