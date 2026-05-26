# llm-gateway — LiteLLM proxy (host 7020 → container 4000)
# Build context: repository root (see docker-compose.yml).

FROM ghcr.io/berriai/litellm:main-stable

LABEL org.opencontainers.image.title="theeyebeta-llm-gateway"

WORKDIR /app

COPY services/llm_gateway/config.yaml /app/config.yaml

EXPOSE 4000

HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=5 \
    CMD wget -qO- http://127.0.0.1:4000/health/liveliness || wget -qO- http://127.0.0.1:4000/health

CMD ["--config", "/app/config.yaml", "--port", "4000", "--host", "0.0.0.0"]
