FROM ghcr.io/astral-sh/uv:0.8.17 AS uv
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/crm/.venv

WORKDIR /opt/crm

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN useradd --create-home --uid 10001 crm \
    && chown -R crm:crm /opt/crm \
    && chmod 755 deploy/docker/entrypoint.sh

USER crm
EXPOSE 8000

ENTRYPOINT ["/opt/crm/deploy/docker/entrypoint.sh"]
