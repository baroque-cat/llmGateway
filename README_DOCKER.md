# Docker/Podman Deployment Guide

This guide explains how to run `llmGateway` as a service using Docker Compose or Podman Compose.

## Prerequisites

- **Docker** (v20.10+) or **Podman** (v4.0+ with `podman-compose` plugin)
- `git` and `make` (optional, for convenience)

## Quick Start

1.  **Clone the repository and navigate to the project directory:**
    ```bash
    git clone https://github.com/your-username/llmGateway.git
    cd llmGateway
    ```

2.  **Create your configuration files:**
    - Create a `.env` file in the project root based on `.env.example`. This file must contain your `DB_PASSWORD`.
    - Create a `config/` directory with your YAML configuration files.
    - Create a `keys/` directory where the application will store and manage your API keys.

3.  **Start the services:**
    ```bash
    # Using Docker
    docker compose up -d

    # Using Podman (Rootless mode is fully supported)
    podman compose up -d
    ```

4.  **The API Gateway will be available at `http://localhost:55300`.**

## Configuration

### Port and Workers

By default, the Gateway runs on port `55300` with `1` worker process to ensure compatibility with low-resource systems.

**To change this, edit the `command` field for the `gateway` service in `docker-compose.yaml`:**
```yaml
services:
  gateway:
    # ...
    command: ["main.py", "gateway", "--host", "0.0.0.0", "--port", "YOUR_PORT", "--workers", "YOUR_WORKER_COUNT"]
```

### Database Connection

The application inside the containers is configured to connect to the database at host `database` (the service name) on the standard PostgreSQL port `5432`.

Ensure your `.env` file contains the correct credentials:
```ini
DB_USER=llm_gateway
DB_PASSWORD=your_strong_password_here
# DB_HOST is overridden by docker-compose to 'database'
# DB_PORT is the standard 5432 inside the container network
```

### Volumes

- **`./config`**: Mounted as read-only (`ro`) into the container. Place your application's YAML configuration here.
- **`./keys`**: Mounted as read-write (`rw`) into the container. The application will create and manage key files in this directory.

### Rootless Podman Compatibility

The setup is designed for rootless Podman:
- The application runs as a non-root user (`UID 1000`) inside the container.
- Volumes use the `:Z` suffix for SELinux compatibility on Fedora/RHEL/CentOS.
- The `security_opt: no-new-privileges:true` flag is set for enhanced security.

If you encounter permission issues with the `keys/` directory, you can add `userns_mode: "keep-id"` to the `gateway` and `worker` services in `docker-compose.yaml`.

## Stopping the Services

```bash
# Using Docker
docker compose down

# Using Podman
podman compose down
```