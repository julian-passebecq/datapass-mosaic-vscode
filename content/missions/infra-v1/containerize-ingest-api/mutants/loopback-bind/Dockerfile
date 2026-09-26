FROM python:3.12-slim
WORKDIR /app
# Dependencies first: this layer stays cached while only the code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --create-home --uid 10001 app
COPY app ./app
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
CMD ["uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"]
