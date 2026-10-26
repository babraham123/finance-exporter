FROM docker.io/python:3-slim-trixie@sha256:533b0b2f9b5d46fd097091cf826f27902f1d6c3bca714b6dc74551356aa97a51
WORKDIR /usr/src/app
COPY pyproject.toml ./
COPY finance_exporter ./finance_exporter
# Nothing installs at run time, and pip's vendored urllib3 and msgpack would fail the scan
# gate.
RUN pip3 install --no-cache-dir . && pip3 uninstall -y pip
ENV CONFIG '/usr/src/app/finance-exporter.yaml'
ENV OPTS ''
CMD ["sh", "-c", "finance-exporter -f ${CONFIG} ${OPTS}"]
