FROM python:3.10-slim
WORKDIR /app

COPY requirements.txt ./
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY data_seeder.py ./data_seeder.py
COPY docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh
EXPOSE 8000
CMD ["/app/docker-entrypoint.sh"]
