FROM python:3.12-slim

# Evita prompts y reduce tamaño.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencias primero para aprovechar caché de capas.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Código.
COPY . .

# Usuario sin privilegios.
RUN useradd --create-home --uid 1001 bot && chown -R bot:bot /app
USER bot

CMD ["python", "bot.py"]
