FROM python:3.11-slim

# Evita gravar bytecode e define buffer para logs em tempo real
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Instala dependências básicas do sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copia dependências do python e instala
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Instala o navegador Chromium e todas as dependências de sistema necessárias do Playwright
RUN playwright install --with-deps chromium

# Copia os arquivos do projeto
COPY . .

# Expõe a porta padrão do Railway (que injeta a variável PORT)
EXPOSE 8000

CMD ["python", "server.py"]
