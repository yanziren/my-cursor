# Day 12 · 沙箱镜像：python + node + git + rg，容器内能跑 pytest / 搜索。
FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        nodejs \
        npm \
        ripgrep \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir pytest

WORKDIR /workspace
