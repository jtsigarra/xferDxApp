FROM python:3.13-slim

# Install system dependencies required by WeasyPrint
RUN apt-get update && apt-get install -y \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libglib2.0-0 \
    libffi-dev \
    shared-mime-info \
    fonts-dejavu-core \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
ENV PORT=8080

RUN python manage.py collectstatic --noinput || true

CMD ["gunicorn", "xferDx.wsgi:application", "--bind", "0.0.0.0:8080"]
