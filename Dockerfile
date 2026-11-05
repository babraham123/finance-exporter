FROM docker.io/python:3-slim-trixie@sha256:8c13a3f37a6a5b71498228e902c4b9f51c1f7900d49fabf71f9a650c6120e0d0
WORKDIR /usr/src/app
COPY pyproject.toml ./
COPY finance_exporter ./finance_exporter
# Nothing installs at run time, and pip's vendored urllib3 and msgpack would fail the scan
# gate.
RUN pip3 install --no-cache-dir . && pip3 uninstall -y pip
ENV CONFIG '/usr/src/app/finance-exporter.yaml'
ENV OPTS ''
CMD ["sh", "-c", "finance-exporter -f ${CONFIG} ${OPTS}"]
