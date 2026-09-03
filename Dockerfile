FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# main_orchestrator.py volgt nog -- dit is het startpunt zodra die klaar is.
CMD ["python3", "-u", "main_orchestrator.py"]
