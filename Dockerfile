FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
# falkordblite is only for local/dev; production talks to a FalkorDB server through FALKORDB_URL
RUN pip install --no-cache-dir $(grep -v falkordblite requirements.txt | grep -v pytest | tr -d "\r")
COPY backend backend
COPY bench bench
COPY mcp_server mcp_server
ENV PORT=8000
CMD ["sh", "-c", "uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT}"]
