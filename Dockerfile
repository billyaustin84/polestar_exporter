FROM python:3.14-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY polestar_exporter ./polestar_exporter

RUN pip install --no-cache-dir .

# Non-root user; /data for the optional token cache
RUN useradd --create-home exporter && mkdir /data && chown exporter /data
USER exporter

ENV EXPORTER_PORT=9772
EXPOSE 9772

CMD ["polestar-exporter"]
