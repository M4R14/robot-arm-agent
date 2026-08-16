FROM node:22-slim

RUN npm install -g @earendil-works/pi-coding-agent@0.84.2

WORKDIR /app

COPY package.json ./
RUN npm install --omit=dev

COPY extensions ./extensions
COPY orchestrator.js ./
COPY orchestrator ./orchestrator
COPY PLANNER.md ./

# Global settings (defaultProvider/defaultModel) and workflow
# instructions — placed under the global config dir so they apply
# without a project-trust prompt, which would otherwise block
# non-interactive container startup.
COPY settings.json /root/.pi/agent/settings.json
COPY AGENTS.md /root/.pi/agent/AGENTS.md

ENV SIM_URL=http://sim:8000

# --no-extensions + explicit -e ensures only the whitelisted robot-arm
# extension loads: no auto-discovered global/project extension can add
# tools outside the fixed set. --no-builtin-tools strips read/write/edit/
# bash/grep/find/ls entirely (see ../SPEC.md sections 5.2 and 5.4).
# --session-dir points this interactive session's history at /data (the
# agent_logs volume, already mounted — see docker-compose.yml), not the
# default ~/.pi/agent/sessions inside the container's writable layer, so
# `pi --continue`/`--resume` survive a container restart instead of
# silently losing history every time. orchestrator.js's own pi calls are
# unaffected — those pass --no-session (pi-runner.js) since each is a
# single-shot process already tracked by run_history.jsonl.
CMD ["pi", "--no-builtin-tools", "--no-extensions", "--session-dir", "/data/pi-sessions", "-e", "./extensions/robot-arm-extension/index.ts"]
