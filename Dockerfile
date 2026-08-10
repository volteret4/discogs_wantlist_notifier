FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Sin servidor: este contenedor solo existe para que Ofelia le haga
# "docker exec" periódicamente (ofelia.job-exec.*), como el resto de jobs
# puramente batch de tumtumpa (lastfm-scrobbles, bot-orpheus, etc.).
CMD ["sleep", "infinity"]
