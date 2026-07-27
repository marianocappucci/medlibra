# syntax=docker/dockerfile:1

# Stage separado para el frontend (React+Vite, ver DECISIONS.md ADR-021):
# node no hace falta en la imagen final, solo el resultado del build
# (frontend/dist). Mismo patron que Gestiolibra (ver su Dockerfile/ADR-019).
#
# frontend/package.json referencia libra-ui (paquete de frontend
# compartido con Gestiolibra/VentaLibra, extraido 2026-07-26 -- ver
# wiki/analyses/auditoria-duplicacion-familia-libra.md) via git+https,
# mismo motivo que libracore/libragenda en el stage de Python de mas
# abajo. Este stage node:20-slim es independiente, necesita su propia
# copia de git+openssh-client + deploy key de solo lectura
# (`id_ed25519_libra_ui` en el VPS). Mount SSH con id propio (no el
# "default" generico) -- mismo patron que Contalibra/Restolibra:
# docker_build_ssh_args() (libracore >= v0.23.0) le pasa a este id su
# propia key dedicada, sin ambiguedad de que identidad ofrece GitHub.
FROM node:20-slim AS frontend-build
WORKDIR /frontend
RUN apt-get update && apt-get install -y --no-install-recommends git openssh-client && rm -rf /var/lib/apt/lists/*
RUN mkdir -p -m 0700 /root/.ssh && ssh-keyscan github.com >> /root/.ssh/known_hosts 2>/dev/null
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=ssh,id=libra-ui,target=/tmp/ssh-libra-ui.sock \
    SSH_AUTH_SOCK=/tmp/ssh-libra-ui.sock \
    sh -c 'git config --global url."ssh://git@github.com/marianocappucci/libra-ui.git".insteadOf "https://github.com/marianocappucci/libra-ui.git" && \
           npm ci'
COPY frontend/ .
RUN npm run build

FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends openssl git openssh-client && rm -rf /var/lib/apt/lists/*

# pyproject.toml referencia LibraGenda/LibraCore via git+https (asi
# funciona tambien el dev local en WSL, que no tiene identidad SSH contra
# GitHub -- ver wiki/entities/libracore.md). El build en el VPS reescribe
# esas URLs a git+ssh (--mount=type=ssh, mismo ssh-agent multi-key
# persistente ya usado por Gestiolibra en este VPS, `agent-multi-libra.sock`,
# con las deploy keys de solo lectura de LibraCore/LibraGenda cargadas --
# no hace falta ninguna deploy key nueva para estas dos dependencias, las
# mismas sirven para cualquier consumidor del mismo VPS) y las descarta con
# la imagen: ninguna clave queda en ninguna capa.
#
# GitHub autentica la conexion SSH completa con la PRIMERA key del agente
# que acepte -- no reintenta con la otra si esa key no tiene acceso al
# repo pedido (mismo hallazgo que Gestiolibra, ver su DECISIONS.md
# ADR-014). Por eso cada dependencia usa su propio alias de Host con
# `IdentitiesOnly yes` + su public key especifica -- eso filtra que
# identidad del agente se ofrece por alias, aunque el agente tenga
# cargadas ambas. Las public keys no son secreto, se hornean en la imagen
# (mismas que ya usa Gestiolibra, mismos repos LibraCore/LibraGenda).
RUN mkdir -p -m 0700 /root/.ssh \
    && ssh-keyscan github.com >> /root/.ssh/known_hosts 2>/dev/null \
    && printf 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIG7oB3H2Rd+xsO/qCUk5aCA14/5GaQFMSh1U0ErJjG55 vps-donweb-libracore-deploy-key\n' > /root/.ssh/id_libracore.pub \
    && printf 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIG4hVY2CmSWj0Na3K8DeryjTDM6URpN8Wj4htLaiLK+L deploy-key-libragenda-readonly\n' > /root/.ssh/id_libragenda.pub \
    && printf 'Host github-libracore\n  HostName github.com\n  User git\n  HostKeyAlias github.com\n  IdentityFile /root/.ssh/id_libracore.pub\n  IdentitiesOnly yes\n\nHost github-libragenda\n  HostName github.com\n  User git\n  HostKeyAlias github.com\n  IdentityFile /root/.ssh/id_libragenda.pub\n  IdentitiesOnly yes\n' > /root/.ssh/config \
    && chmod 600 /root/.ssh/config /root/.ssh/id_libracore.pub /root/.ssh/id_libragenda.pub

COPY . .
# Horneado FUERA de /app a proposito (mismo criterio que Gestiolibra
# ADR-022): el docker-compose.yml de dev monta ./:/app entero para el
# --reload de Python, lo que taparia cualquier build copiado dentro de
# /app con el checkout del host (que no tiene frontend/dist, es un
# artefacto gitignoreado). Copiarlo fuera del arbol bind-monteado evita
# el problema de raiz, sin volumenes.
COPY --from=frontend-build /frontend/dist /opt/frontend-dist
RUN --mount=type=ssh \
    git config --global url."ssh://git@github-libracore/marianocappucci/libracore.git".insteadOf "https://github.com/marianocappucci/libracore.git" \
    && git config --global url."ssh://git@github-libragenda/marianocappucci/libragenda.git".insteadOf "https://github.com/marianocappucci/libragenda.git" \
    && pip install --no-cache-dir . \
    && git config --global --unset url."ssh://git@github-libracore/marianocappucci/libracore.git".insteadOf \
    && git config --global --unset url."ssh://git@github-libragenda/marianocappucci/libragenda.git".insteadOf

EXPOSE 8000

CMD ["uvicorn", "app.asgi:app", "--host", "0.0.0.0", "--port", "8000"]
