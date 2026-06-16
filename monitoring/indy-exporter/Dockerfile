FROM python:3.10-slim

# indy-vdr e aries-askar distribuem wheels pré-compiladas para linux/amd64
# Nenhum compilador Rust necessário — imagem final é pequena
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY exporter.py .

EXPOSE 9309

CMD ["python", "exporter.py"]
