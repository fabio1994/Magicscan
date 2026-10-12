FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir opencv-python-headless numpy requests pillow sentence-transformers flask gunicorn
COPY magicscan.py app.py ./
COPY static static
CMD ["gunicorn", "-b", "0.0.0.0:8086", "-w", "1", "--threads", "2", "--timeout", "180", "app:app"]
