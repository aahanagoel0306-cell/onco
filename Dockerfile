FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt
ENV PROD=1
# Set SEED=1 only for a throwaway demo database (creates users with a known password)
CMD ["sh","-c","if [ \"$SEED\" = \"1\" ]; then python seed.py; fi; uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
