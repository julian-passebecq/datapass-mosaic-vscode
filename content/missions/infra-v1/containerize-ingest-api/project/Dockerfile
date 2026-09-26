FROM python:latest
COPY . /app
WORKDIR /app
RUN pip install -r requirements.txt
ENV DATABASE_PASSWORD=ingest
CMD uvicorn app.main:app --host 127.0.0.1 --port 8000
