FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV PORT=8080

WORKDIR /app

# Install uv
RUN pip install uv

# Copy the dependencies
COPY pyproject.toml .

# Install dependencies using uv
RUN uv pip install --system -r pyproject.toml

# Copy the rest of the application
COPY . .

# Run the app
CMD ["python", "frontend/app.py"]
