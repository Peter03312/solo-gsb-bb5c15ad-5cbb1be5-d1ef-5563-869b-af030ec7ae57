# 矩形纸张裁切排样应用：零第三方依赖（仅 Python 标准库）
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/data \
    PORT=8000 \
    SOLVER_TIME_LIMIT=30

WORKDIR /app
COPY . .

# 初始化数据目录并做语法自检；SQLite 表结构在首次启动时自动创建
RUN mkdir -p /app/data && python -m compileall -q .

EXPOSE 8000
VOLUME ["/app/data"]

CMD ["python", "app.py"]
