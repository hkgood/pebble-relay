FROM python:3.11-slim

WORKDIR /app

# 安装依赖（只需要 Flask）
RUN pip install --no-cache-dir flask

# 复制代码
COPY server.py .

# 创建数据目录
RUN mkdir -p /data

# 暴露端口
EXPOSE 8977

# 环境变量
ENV PORT=8977
ENV DB_PATH=/data/relay.db
ENV WEBHOOK_TOKEN=change-me-in-production

CMD ["python", "server.py"]
