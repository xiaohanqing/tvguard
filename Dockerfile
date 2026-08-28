FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl unzip \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSLo /tmp/pt.zip https://dl.google.com/android/repository/platform-tools-latest-linux.zip \
    && unzip -q /tmp/pt.zip -d /opt && rm /tmp/pt.zip \
    && chmod +x /opt/platform-tools/adb /opt/platform-tools/fastboot \
    && /opt/platform-tools/adb version

ENV PATH="/opt/platform-tools:${PATH}"

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

VOLUME /app/data
EXPOSE 8787

CMD ["python", "run.py"]
