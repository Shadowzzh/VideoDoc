# VideoDoc 容器镜像（多阶段）
#
# 目的：把「装 Python / Node / pnpm / ffmpeg」这道前置门槛整个抹掉 —— 使用者只要有 Docker，
# 一条 docker run 就能跑，并在设置页填 BaseURL + Key 即可启用云端图像识别（不依赖 macOS）。
#
# 阶段 1：构建前端（需要 Node + pnpm，与 frontend/package.json 里钉的版本一致）
# 阶段 2：装 Python 依赖 + ffmpeg，仅复制构建产物，运行镜像里不含 Node/pnpm

# ---------------------------------------------------------------- 阶段 1：前端
FROM node:24-slim AS frontend

WORKDIR /src

# 仓库在 frontend/package.json 钉了 pnpm@9.15.9；较新的 corepack 会因版本校验拒绝执行，
# 所以先关掉 corepack 的 shim，再用 npm 装同一版本（等价于 README 里给的手工步骤）。
RUN corepack disable >/dev/null 2>&1 || true \
    && npm install -g pnpm@9.15.9 >/dev/null 2>&1

COPY frontend/package.json frontend/pnpm-lock.yaml* /src/frontend/
RUN cd frontend && (pnpm install --frozen-lockfile --prefer-offline || pnpm install)

COPY frontend/ /src/frontend/
RUN cd frontend && pnpm build

# ---------------------------------------------------------------- 阶段 2：Python 依赖
FROM python:3.12-slim AS backend

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

# pywhispercpp 等依赖在部分架构上没有预编译 wheel，这里备好编译链（只留在本阶段）
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential cmake git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN python -m venv /app/.venv
COPY pyproject.toml README.md LICENSE /app/
COPY videodoc/ /app/videodoc/
RUN /app/.venv/bin/pip install --upgrade pip \
    && /app/.venv/bin/pip install .

# ---------------------------------------------------------------- 阶段 3：运行
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # 运行数据与缓存（含自动下载的 whisper 模型）都落在挂载卷里
    HOME=/data \
    VIDEODOC_RUNTIME_DIR=/data/videodoc \
    VIDEODOC_FRONTEND_DIST=/app/frontend/dist \
    PATH=/app/.venv/bin:$PATH

# 运行期只留 ffmpeg（抽帧/音频）；没有 Node、没有 pnpm、没有编译器等构建期工具
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=backend /app/.venv /app/.venv
COPY videodoc/ /app/videodoc/
COPY pyproject.toml README.md LICENSE /app/
COPY --from=frontend /src/frontend/dist /app/frontend/dist

RUN mkdir -p /data && chmod 777 /data
VOLUME ["/data"]
EXPOSE 8765

# 健康检查：设置接口 200 即说明服务与前端资源都就绪
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8765/api/settings >/dev/null || exit 1

# 单用户本地工具：直接跑开发服务器即可（与本地安装一致的运行形态）
CMD ["videodoc", "--host", "0.0.0.0", "--port", "8765"]
