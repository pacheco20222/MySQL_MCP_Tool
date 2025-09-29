FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV MCP_TRANSPORT=sse PORT=8000 HOST=0.0.0.0
EXPOSE 8000
CMD ["python", "server.py"]