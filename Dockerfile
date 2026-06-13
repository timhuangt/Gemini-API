# Use a slim Python 3.12 base image for a smaller footprint
FROM python:3.12-slim

# Set environment variables to optimize Python execution
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Set the working directory in the container
WORKDIR /app

# Install system dependencies (curl-cffi downloads precompiled wheels, but curl is useful for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy pyproject.toml to install package dependencies first (better Docker caching)
COPY pyproject.toml ./

# Create a dummy src folder structure so pip install . can resolve metadata
COPY src/ ./src/

# Install the package itself along with FastAPI and Uvicorn
RUN pip install --upgrade pip && \
    SETUPTOOLS_SCM_PRETEND_VERSION=1.0.0 pip install . fastapi uvicorn

# Copy the server script and documentation
COPY server.py ./

# Create an empty cookies.json if not already mounted, ensuring correct permissions
RUN echo '{"cookies": {}}' > cookies.json

# Expose the port FastAPI will run on
EXPOSE 8000

# Healthcheck to verify the server is running and reachable
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/api/status || exit 1

# Start the FastAPI server using Uvicorn
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
