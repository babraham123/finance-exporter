FROM docker.io/python:3-slim-trixie
WORKDIR /usr/src/app
COPY pyproject.toml ./
COPY finance_exporter ./finance_exporter
RUN pip3 install --no-cache-dir .
ENV CONFIG '/usr/src/app/finance-exporter.yaml'
ENV OPTS ''
CMD ["sh", "-c", "finance-exporter -f ${CONFIG} ${OPTS}"]
