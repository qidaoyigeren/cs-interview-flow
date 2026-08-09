FROM golang:1.24-bookworm@sha256:1a6d4452c65dea36aac2e2d606b01b4a029ec90cc1ae53890540ce6173ea77ac AS go-runtime

COPY prewarm.go /tmp/prewarm.go
RUN mkdir -p /go-cache-seed \
    && GOCACHE=/go-cache-seed GOMAXPROCS=2 /usr/local/go/bin/go build -p=1 -trimpath -o /tmp/prewarm /tmp/prewarm.go \
    && rm -f /tmp/prewarm /tmp/prewarm.go

FROM node:22-bookworm-slim@sha256:d649c27dae7ba0137b3cef5dd75baa422c08dc3d9e3fc0c23dfb172dc3cc6436

RUN apt-get update \
    && apt-get install --no-install-recommends -y bubblewrap python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 65532 runner \
    && useradd --uid 65532 --gid 65532 --no-create-home --home-dir /tmp runner

RUN mkdir -p /work \
    && chown 65532:65532 /work

COPY --from=go-runtime /usr/local/go /usr/local/go
COPY --from=go-runtime /go-cache-seed /opt/runner/go-cache-seed
COPY --chown=65532:65532 runner.py /opt/runner/runner.py
COPY --chown=65532:65532 limit_exec.py /opt/runner/limit_exec.py

USER 65532:65532
WORKDIR /opt/runner
EXPOSE 9390
ENTRYPOINT ["/usr/bin/python3", "/opt/runner/runner.py"]
