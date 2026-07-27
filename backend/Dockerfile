FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV MODEL_PATH=/models/qwen2.5-coder-7b-instruct-q4_k_m.gguf
ENV LLAMA_SERVER_HOST=llama-server
ENV LLAMA_SERVER_PORT=8080
ENV HOST=0.0.0.0
ENV PORT=8000

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
