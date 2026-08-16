FROM node:22-slim

RUN npm install -g @earendil-works/pi-coding-agent@0.84.2

WORKDIR /app

COPY package.json ./
RUN npm install --omit=dev

COPY extensions ./extensions

# Global settings (defaultProvider/defaultModel) — placed under the
# global config dir so it applies without a project-trust prompt, which
# would otherwise block non-interactive container startup.
COPY settings.json /root/.pi/agent/settings.json

ENV SIM_URL=http://sim:8000

# --no-extensions + explicit -e ensures only the whitelisted robot-arm
# extension loads: no auto-discovered global/project extension can add
# tools outside the fixed set. --no-builtin-tools strips read/write/edit/
# bash/grep/find/ls entirely (see ../SPEC.md sections 5.2 and 5.4).
CMD ["pi", "--no-builtin-tools", "--no-extensions", "-e", "./extensions/robot-arm-extension.ts"]
