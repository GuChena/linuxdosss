FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive

# 安装 Chrome 和中文字体
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates wget gnupg fonts-wqy-zenhei fonts-noto-cjk \
    && install -d -m 0755 /etc/apt/keyrings \
    && wget -qO- https://dl.google.com/linux/linux_signing_key.pub \
        | gpg --dearmor -o /etc/apt/keyrings/google-linux-signing-key.gpg \
    && chmod a+r /etc/apt/keyrings/google-linux-signing-key.gpg \
    && printf '%s\n' \
        'deb [arch=amd64 signed-by=/etc/apt/keyrings/google-linux-signing-key.gpg] https://dl.google.com/linux/chrome/deb/ stable main' \
        > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends google-chrome-stable \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 安装 Python 依赖
RUN pip install --no-cache-dir DrissionPage schedule

# 复制脚本
COPY linux_do_docker.py .

# 持久化浏览器数据（保持登录状态）
VOLUME /app/chrome-data

ENV CHROME_USER_DATA=/app/chrome-data
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "linux_do_docker.py"]
