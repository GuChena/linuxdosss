FROM python:3.11-slim

# 安装 Chrome 和中文字体
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg2 fonts-wqy-zenhei fonts-noto-cjk \
    && wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y --no-install-recommends google-chrome-stable \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

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
