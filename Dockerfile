FROM docker.io/python:3-slim-trixie@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928
WORKDIR /usr/src/app
COPY pyproject.toml ./
COPY finance_exporter ./finance_exporter
# Nothing installs at run time, and pip's vendored urllib3 and msgpack would fail the scan
# gate.
RUN pip3 install --no-cache-dir . && pip3 uninstall -y pip
ENV CONFIG '/usr/src/app/finance-exporter.yaml'
ENV OPTS ''
CMD ["sh", "-c", "finance-exporter -f ${CONFIG} ${OPTS}"]
