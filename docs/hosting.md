# Hosting backend: free tier / pay-as-you-go tanpa cold start

**Status:** rekomendasi, riset pasar November 2026. Harga dan kuota free tier
bisa berubah kapan saja; verifikasi di halaman resmi sebelum commit.

## Jawaban singkat

**Bisa full cloud tanpa laptop.** Stack FastAPI + Postgres + Docker bisa
berjalan sepenuhnya di cloud. Yang tidak cocok adalah **Render free** dan
**Koyeb free** karena service tidur dan cold start.

Rekomendasi berdasarkan tujuan:

| Tujuan | Pilihan | Kenapa |
|---|---|---|
| **Gratis, always-on, paling cepat** | **Northflank Free Sandbox** | 2 service always-on + 1 database, tanpa sleep |
| **Murah, lebih matang** | **Fly.io 512 MB + Neon Free** | ~US$3.69/bulan, tidak sleep jika `min_machines_running=1` |
| **Sudah di GCP** | **Cloud Run min-instance=1** | ~US$6.65/bulan setelah free allowance, tanpa cold start |
| **Gratis jangka panjang, siap ops** | **Oracle Cloud Always Free** | 2 OCPU/12 GB ARM + 200 GB storage, tanpa cold start |

**Rekomendasi saya:** mulai dari **Northflank Free Sandbox**. Kalau kuota atau
kartu kreditnya bermasalah, pindah ke **Fly.io 512 MB + Neon Free**. Jangan
kembali ke Render free.

---

## Perbandingan opsi

| Opsi | Always-on? | Free tier? | Estimasi biaya | Cold start | Catatan |
|---|---|---|---:|---|---|
| **Northflank Free Sandbox** | Ya | Ya | $0 | Tidak | 2 service always-on + 1 database; resource kecil; cocok portfolio/staging |
| **Fly.io shared-cpu-1x 512 MB** | Ya, jika min=1 | Tidak untuk org baru | ~$3.69/bulan | Tidak | Tidak ada free allowance baru; wajib set `min_machines_running=1` |
| **Google Cloud Run** | Ya, jika min=1 | Ya (allowance bulanan) | ~$6.65/bulan setelah allowance | Tidak jika min=1 | Bayar CPU saat instance min menganggur |
| **Oracle Cloud Always Free** | Ya | Ya | $0 | Tidak | 2 OCPU/12 GB ARM, 200 GB; perlu Docker, Caddy, backup, patching |
| **Koyeb Free** | Tidak | Ya | $0 | Ya, setelah 1 jam idle | Scale-to-zero tidak bisa dimatikan di free |
| **Render Free** | Tidak | Ya | $0 | Ya, setelah ~15 menit | Tidak sesuai kebutuhan |
| **Railway Hobby** | Ya | Minimum $5/bulan | ~$5+ | Tidak | Free plan terbatas; Hobby lebih realistis |
| **Heroku Eco** | Tidak | Tidak | ~$5/bulan | Ya | Dyno tidur |

### Database

| Opsi | Free tier | Catatan |
|---|---|---|
| **Neon Free** | 0.5 GB, autosuspend | Cocok untuk P0.1; cold start DB ~ratusan ms; connection pooling |
| **Northflank free Postgres** | Termasuk paket free | Paling praktis jika web juga di Northflank |
| **Supabase Free** | Ya | Project bisa pause setelah idle lama; kurang cocok untuk API produksi |
| **Fly Managed Postgres** | Tidak | Mulai ~$38/bulan; terlalu mahal untuk tahap ini |
| **Oracle self-hosted Postgres** | Termasuk VM | Murah, tapi backup/patching jadi tanggung jawab sendiri |

**Untuk P0.1**, Neon Free sudah cukup: tabel identity/profile kecil, trafik
rendah, dan koneksi bisa dipool. Jangan taruh file PDF/gambar di Postgres;
gunakan object storage (Cloudflare R2 free 10 GB) saat P0.2.

P0.2 saat ini membuat PDF/ICS secara synchronous di proses API. Itu cukup untuk
plan kecil; pindahkan ke worker + object storage saat volume atau ukuran plan
meningkat (P2.3).

---

## Kenapa Render free tidak cocok

Render free menidurkan service setelah tidak ada trafik. Request berikutnya
membangunkan proses, memuat dataset, membuat koneksi database, lalu menjalankan
GA. Itu menyebabkan latency awal puluhan detik dan pengalaman "stuck" di
halaman Process. Kebutuhan Anda adalah **always-on**, jadi plan free Render
tidak memenuhi syarat.

Koyeb free juga scale-to-zero setelah 1 jam idle. Sama-sama tidak cocok.

---

## Rekomendasi 1 — Northflank Free Sandbox ($0)

Cocok untuk portfolio dan demo publik.

1. Buat akun Northflank, pilih Free Sandbox.
2. Buat Postgres free (satu database).
3. Buat web service dari repository GitHub atau Docker image.
4. Build command: Dockerfile repo ini.
5. Port: `8080`.
6. Health check: `/ready`.
7. Environment:
   ```text
   ENVIRONMENT=production
   DATABASE_URL=postgresql://...   # dari Northflank/Neon
   AUTH_ENABLED=false
   AUTH_PROFILES_ENABLED=false
   CORS_ORIGINS=https://jymz.pages.dev
   TRUST_PROXY_HEADERS=true
   RATE_LIMIT=120/minute
   ```
8. Jalankan migration sekali:
   ```bash
   alembic upgrade head
   ```
   Di platform yang mendukung release command/job, jadikan ini langkah deploy.
9. Buka `/ready`; harus `200` dan `database: ok`.

**Catatan:** free tier biasanya tanpa SLA, resource kecil, dan bisa berubah.
Untuk produk yang mulai dipakai orang, pindah ke Fly.io.

---

## Rekomendasi 2 — Fly.io 512 MB + Neon Free (~$4/bulan)

Ini pilihan paling seimbang antara harga, kontrol, dan keandalan.

### fly.toml contoh

```toml
app = "jymz-api"
primary_region = "sin"

[build]
  dockerfile = "Dockerfile"

[deploy]
  release_command = "alembic upgrade head"

[http_service]
  internal_port = 8080
  force_https = true
  auto_stop_machines = false
  auto_start_machines = true
  min_machines_running = 1

[[http_service.checks]]
  grace_period = "20s"
  interval = "30s"
  method = "GET"
  timeout = "5s"
  path = "/ready"

[[vm]]
  size = "shared-cpu-1x"
  memory = "512mb"
```

`min_machines_running = 1` dan `auto_stop_machines = false` adalah kunci agar
tidak ada cold start. Tanpa itu, Fly bisa menghentikan machine idle.

### Langkah

```bash
fly launch --no-deploy
fly secrets set DATABASE_URL="postgresql://..." \
  AUTH_ENABLED=false AUTH_PROFILES_ENABLED=false \
  CORS_ORIGINS="https://jymz.pages.dev" \
  TRUST_PROXY_HEADERS=true
fly deploy
fly logs
```

Jika `release_command` tidak diinginkan, jalankan migration dari mesin lokal
dengan `DATABASE_URL` produksi:

```bash
DATABASE_URL="postgresql://..." alembic upgrade head
```

**Biaya:** shared-cpu-1x 512 MB sekitar US$3.69/bulan; volume dan egress
tambahan. Fly tidak punya free allowance untuk organisasi baru dan secara
default tidak punya spending cap; set billing alert.

---

## Rekomendasi 3 — Cloud Run min-instance=1 (~$6.65/bulan)

Cocok jika Anda sudah memakai GCP.

```bash
gcloud run deploy jymz-api \
  --image asia-southeast1-docker.pkg.dev/PROJECT/REPO/jymz-api:latest \
  --region asia-southeast1 \
  --min-instances=1 \
  --max-instances=2 \
  --cpu=1 \
  --memory=512Mi \
  --port=8080 \
  --allow-unauthenticated
```

- `--min-instances=1` menghilangkan cold start, tetapi CPU instance min tetap
  ditagih.
- Free tier Cloud Run berupa allowance bulanan; setelah itu biaya berjalan.
- Database: Neon Free atau Cloud SQL (Cloud SQL mahal untuk tahap ini).
- Jalankan migration lewat Cloud Build job atau dari lokal dengan `DATABASE_URL`.

---

## Rekomendasi 4 — Oracle Cloud Always Free ($0, perlu ops)

Paling murah jangka panjang, tetapi bukan "deploy lalu lupa".

- Ampere A1: 2 OCPU / 12 GB RAM (kuota 2026; sebelumnya 4/24).
- 200 GB block/boot storage.
- 2 VM AMD micro 1/8 OCPU / 1 GB.
- Always-on, tanpa cold start.

Pola deployment:

```text
VM Oracle
  ├── Docker: jymz-api (port 8080)
  ├── Caddy/Nginx: HTTPS + reverse proxy
  └── Postgres: container atau Neon Free
```

Yang harus Anda urus: patching OS, firewall, TLS renewal, backup, monitoring,
dan restore test. Jika tidak ingin ops, jangan pilih ini.

---

## Yang tidak saya rekomendasikan

- **Render free** — sleep dan cold start.
- **Koyeb free** — scale-to-zero setelah 1 jam.
- **Supabase free untuk API produksi** — project bisa pause.
- **Serverless dengan batas durasi** untuk seluruh API — GA dan PDF/worker
  lebih aman di container always-on. Serverless bisa dipakai untuk job
  terpisah nanti.
- **Microservices/Kubernetes** — belum ada beban yang membenarkan.

---

## Rencana pindah dari Render

1. **Siapkan database**: Neon Free atau Northflank Postgres.
2. **Set `DATABASE_URL`** di platform baru.
3. **Jalankan `alembic upgrade head`**.
4. **Deploy image** dengan `ENVIRONMENT=production`, `CORS_ORIGINS` eksplisit.
5. **Cek `/health` dan `/ready`**; `/ready` harus `database: ok`.
6. **Uji endpoint rekomendasi** tanpa auth.
7. **Aktifkan auth** setelah OIDC provider siap:
   ```text
   AUTH_ENABLED=true
   AUTH_PROFILES_ENABLED=true
   AUTH_ISSUER=https://...
   AUTH_AUDIENCE=...
   AUTH_JWKS_URL=https://.../.well-known/jwks.json
   ```
8. **Update frontend** ke base URL baru dan test CORS.
9. **Matikan Render** setelah 24–48 jam stabil.

Jangan mengaktifkan `AUTH_PROFILES_ENABLED=true` sebelum provider OIDC dan
`DATABASE_URL` siap. Endpoint lama tetap publik dan tidak terpengaruh.

---

## Checklist "tanpa cold start"

- [ ] Platform always-on, bukan free tier yang sleep.
- [ ] `min_machines_running=1` (Fly) atau `--min-instances=1` (Cloud Run).
- [ ] `auto_stop_machines=false` (Fly).
- [ ] Health check `/ready`, grace period cukup.
- [ ] Database aktif; connection pool dan `pool_pre_ping` sudah ada.
- [ ] Dataset dimuat saat startup, bukan per request.
- [ ] Tidak ada worker berat di request path; PDF/email nanti ke worker.
- [ ] Billing alert aktif.
- [ ] Migration dijalankan sebelum traffic dialihkan.

---

## Keputusan yang saya sarankan

1. **Sekarang:** Northflank Free Sandbox + Postgres free. Biaya $0, tanpa
   cold start. Cocok untuk portfolio dan demo.
2. **Jika Northflank tidak cocok:** Fly.io 512 MB + Neon Free, ~$4/bulan.
   Ini pilihan produksi kecil yang paling masuk akal.
3. **Jika ingin $0 jangka panjang dan siap ops:** Oracle Always Free.
4. **Jika sudah di GCP:** Cloud Run min-instance=1.

Yang penting: **jangan pakai free tier yang sleep**. Itu akar masalah Render
yang Anda keluhkan.
