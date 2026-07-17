FROM python:3.11-slim

WORKDIR /app

# Install Python dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright's Chromium + all OS-level deps it needs
RUN playwright install chromium && playwright install-deps chromium

# Copy application source
COPY . .

# Runtime directories (ephemeral on HF Spaces — that's fine, tracker uses Google Sheets)
RUN mkdir -p data logs screenshots

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 7860

ENTRYPOINT ["/entrypoint.sh"]
