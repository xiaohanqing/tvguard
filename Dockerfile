FROM python:3.12-slim

# pip 走国内镜像，避免服务器直连 PyPI 失败；构建时可覆盖：
#   docker compose build --build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

RUN apt-get update && apt-get install -y --no-install-recommends curl unzip \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -i ${PIP_INDEX_URL} -r requirements.txt

COPY . .

# platform-tools：优先用项目目录里预下载的 zip，其次 Google 官方源，再试华为镜像源。
# 解压后显式加执行位并自验 adb 可运行。
RUN set -e; \
    if [ -f platform-tools-latest-linux.zip ]; then ZIP=platform-tools-latest-linux.zip; \
    elif [ -f pt.zip ]; then ZIP=pt.zip; \
    elif curl -fsSLo pt.zip https://dl.google.com/android/repository/platform-tools-latest-linux.zip; then ZIP=pt.zip; \
    elif curl -fsSLo pt.zip https://mirrors.huaweicloud.com/android/repository/platform-tools-latest-linux.zip; then ZIP=pt.zip; \
    else echo "!! 无法下载 platform-tools：请手动下载 platform-tools-latest-linux.zip 放到项目目录后重新构建"; exit 1; fi; \
    unzip -q "$ZIP" -d /opt && rm -f "$ZIP"; \
    chmod +x /opt/platform-tools/adb; \
    /opt/platform-tools/adb version

ENV PATH="/opt/platform-tools:${PATH}"

WORKDIR /app

VOLUME /app/data
EXPOSE 8787

CMD ["python", "run.py"]
