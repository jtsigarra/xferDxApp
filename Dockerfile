# Use official Python slim image
FROM python:3.12-slim

# Install system dependencies for PDF, image libraries, fonts, etc.
RUN apt-get update && apt-get install -y \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-xlib-2.0-0 \
    libglib2.0-0 \
    libffi-dev \
    shared-mime-info \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project code
COPY . .

# Ensure Python output is unbuffered
ENV PYTHONUNBUFFERED=1

# Run migrations and collect static files
RUN python manage.py migrate --noinput || true
RUN python manage.py collectstatic --noinput || true

# Start Gunicorn with Railway's dynamic port
CMD gunicorn xferDx.wsgi:application --bind 0.0.0.0:$PORT
