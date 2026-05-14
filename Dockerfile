# ---- Build stage ----
FROM python:3.11-slim AS builder

WORKDIR /build
RUN pip install --no-cache-dir --upgrade pip

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ---- Runtime stage ----
FROM python:3.11-slim

RUN groupadd -r mcp && useradd -r -g mcp -d /app mcp

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /root/.local /home/mcp/.local
ENV PATH="/home/mcp/.local/bin:$PATH"
ENV PYTHONPATH="/home/mcp/.local/lib/python3.11/site-packages"

# Copy application code
COPY server.py vm_power.py vm_inventory.py host_inventory.py safety.py audit.py vsphere_client.py ./

# Create writable directories
RUN mkdir -p /app/logs && chown -R mcp:mcp /app

USER mcp

# MCP server communicates via stdio — keep stdin open with -i flag
CMD ["python", "server.py"]
