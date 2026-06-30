FROM python:3.11-slim

# Install Tesseract OCR
RUN apt-get update && \
    apt-get install -y --no-install-recommends tesseract-ocr && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY *.py ./

# Create output directories
RUN mkdir -p reports measurements dicom_cache

# Default: watch mode
CMD ["python", "pipeline.py", "watch"]
