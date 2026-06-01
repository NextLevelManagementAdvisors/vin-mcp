FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml README.md ./
COPY src ./src
RUN uv pip install --system .
EXPOSE 3032
CMD ["python", "-m", "src.server", "--transport", "http", "--host", "0.0.0.0", "--port", "3032"]
