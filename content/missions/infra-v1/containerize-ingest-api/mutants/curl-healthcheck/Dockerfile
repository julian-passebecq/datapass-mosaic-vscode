FROM python:3.12-slim
WORKDIR /app
# Dependencies first: this layer stays cached while only the code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --create-home --uid 10001 app
COPY app ./app
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s CMD curl -f http://localhost:8000/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
