FROM python:3.12-slim
WORKDIR /app
COPY jev_trader /app/jev_trader
COPY config /app/config
RUN mkdir -p /app/data /app/reports
CMD ["python", "-m", "jev_trader", "run"]
