FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATABASE_PATH=/data/state.db
WORKDIR /app
COPY certs/russian_trusted_root_ca.crt /usr/local/share/ca-certificates/russian_trusted_root_ca.crt
RUN update-ca-certificates
COPY maxnotify /app/maxnotify
RUN useradd --uid 10001 --create-home bot && mkdir /data && chown bot:bot /data
USER bot
CMD ["python", "-m", "maxnotify.runner"]
