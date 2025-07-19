# Gunakan Python 3.9.11 sebagai base
FROM python:3.9.11-slim

# Set working directory
WORKDIR /app

# Salin file requirements dan install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Salin semua file proyek
COPY . .

# Expose port dan jalankan app (ganti kalau pakai modul berbeda)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
