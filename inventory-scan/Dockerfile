FROM python:3.14-slim

ARG TARGETARCH

# kubectl と helm をインストール
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && KUBECTL_VERSION=$(curl -sL https://dl.k8s.io/release/stable.txt) \
    && curl -sLO "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${TARGETARCH}/kubectl" \
    && chmod +x kubectl && mv kubectl /usr/local/bin/ \
    && curl -sL https://get.helm.sh/helm-v3.17.3-linux-${TARGETARCH}.tar.gz | tar xz \
    && mv linux-${TARGETARCH}/helm /usr/local/bin/ && rm -rf linux-${TARGETARCH} \
    && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pymysql==1.2.0 requests==2.34.2

USER 1000

CMD ["python"]
