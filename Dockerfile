# python:3.12-slim (Debian "bookworm" base as of this writing). Pinning to an exact
# digest is a recommended follow-up for a real deployment (`docker pull` then
# `docker inspect --format='{{index .RepoDigests 0}}'` to capture it) -- not done here
# since this environment cannot reach a registry to verify a specific digest still
# resolves, and fabricating one would be worse than the floating tag it replaces.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Non-root execution (P10 requirement 14). The review SQLite database is written to
# var/ at runtime (created lazily on first use) -- owning /app as this user covers it.
RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Exercises the same dependency checks as GET /health/ready (stage P9), not just
# process liveness -- a container reported "healthy" here has verified its dataset,
# review store, and auth config are all actually reachable.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/ready',timeout=2).status==200 else 1)"

CMD ["uvicorn","src.app:app","--host","0.0.0.0","--port","8000"]
