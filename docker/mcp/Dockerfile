FROM python:3.12-slim

WORKDIR /app

COPY mcp-server/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY mcp-server/src/ ./src/

EXPOSE 27183

CMD ["python", "src/server.py"]
