# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Set environment variables for Python
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Increase number of workers. Heroku standard dynos often handle 2-4 workers well.
# WEB_CONCURRENCY is often set by Heroku for buildpack apps, for Docker you can set it or hardcode.
# Let's try 2 workers.
CMD gunicorn -k gevent --workers ${WEB_CONCURRENCY:-2} --timeout 120 --access-logfile - --error-logfile - --log-level debug app:app --bind "0.0.0.0:$PORT"