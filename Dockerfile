# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY ./requirements.txt /app/requirements.txt

RUN apt-get update && apt-get install -y libdmtx-dev ssh iputils-ping
# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source (docker-compose overlays this with a live bind mount for dev)
COPY . /app

# Make port 8000 available to the world outside this container (optional, adjust if needed)
EXPOSE 8000

# Define environment variable for running the app
ENV PYTHONUNBUFFERED=1

# Version info for the footer indicator, baked in at build time since the
# .git directory itself is excluded via .dockerignore. VERSION is the git
# tag on a tagged release build (see release-image.yml); GIT_SHA is the
# commit, always set and used as a fallback when there's no release tag.
ARG GIT_SHA=unknown
ARG VERSION=
ENV GIT_SHA=$GIT_SHA
ENV VERSION=$VERSION

# Run the application
CMD ["uvicorn", "src.main:app", "--reload", "--host", "0.0.0.0"]
