FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
COPY requirements-dashboard.txt /app/requirements-dashboard.txt
RUN pip install --no-cache-dir -r requirements-dashboard.txt
COPY jev_trader /app/jev_trader
COPY dashboard /app/dashboard
COPY config /app/config
RUN mkdir -p /app/data /app/reports
EXPOSE 8080
CMD ["python", "-m", "dashboard", "--with-bot", "--host", "0.0.0.0"]
