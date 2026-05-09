# 🧬 Fitness-RS API: Hybrid AI and Cloud Infrastructure

[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?style=for-the-badge&logo=fastapi&logoColor=white)]()
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)]()
[![PyGAD](https://img.shields.io/badge/PyGAD-Genetic_Algorithm-FF6F00?style=for-the-badge)]()
[![Experta](https://img.shields.io/badge/Experta-Rule_Based-4CAF50?style=for-the-badge)]()

> Repositori ini adalah implementasi *Backend Service* untuk Sistem Rekomendasi Kebugaran. Proyek ini mendemonstrasikan dua pilar utama yaitu (1) Riset Kecerdasan Buatan gabungan dari Sistem Pakar + Algoritma Genetika, dan (2) Infrastruktur *Cloud-Native* berbasis Python yang siap dioperasikan dalam skala production.

🔗 **Live API Endpoint:** [https://fitness-rs-api.onrender.com](https://fitness-rs-api.onrender.com)  
📖 **Interactive API Docs (Swagger):** [https://fitness-rs-api.onrender.com/docs](https://fitness-rs-api.onrender.com/docs)

---

## 🧠 Pilar 1: Bagaimana Proses dalam Algoritma

Sistem rekomendasi berbasis data (*Data-Driven*) sering kali menjadi "Black Box" yang berbahaya jika diterapkan pada domain kesehatan tanpa pengawasan. Untuk mencegah pengguna mendapatkan jadwal latihan yang berisiko cedera, kecerdasan buatan di API ini dirancang menggunakan pendekatan yang dikombinasikan.

![Flowchart Hibrida](https://pub-602fa6026a04465d944bea72bc0f7d73.r2.dev/Screenshot%202026-05-09%20135132.png)

*(Catatan: Diagram alur reduksi ruang pencarian dari Sistem Pakar ke Algoritma Genetika)*


### A. Sistem Pakar dengan Experta
Bertindak sebagai "Pelatih Fisik" virtual yang memegang aturan mutlak (*absolute constraints*). Menggunakan metode logika *Forward Chaining*, sistem ini menerjemahkan kondisi biologis pengguna menjadi batasan komputasi.
* **Logika Keamanan:** Jika BMI pengguna > 25, sistem memaksa injeksi kardio. Jika ketersediaan waktu maksimal 5 hari, sistem melarang pembuatan jadwal 6 hari untuk mencegah *overtraining*.
* **Search Space Reduction:** Output dari sistem pakar ini digunakan untuk membuang ratusan kombinasi latihan yang tidak masuk akal di dalam *dataset*, sehingga mempercepat komputasi tahap selanjutnya.

### B. Global Optimization Algoritma Genetika dengan PyGAD
Bertindak sebagai "Kalkulator Optimasi" yang mencari jadwal terbaik dari sisa *dataset* yang sudah disaring.

![Siklus Algoritma Genetika](https://pub-602fa6026a04465d944bea72bc0f7d73.r2.dev/Screenshot%202026-05-09%20135435.png)

*(Catatan: Siklus komputasi evolusioner pada Algoritma Genetika)*

* **Fitness Function Terkontrol:** Algoritma mengevaluasi ribuan kromosom berdasarkan sistem *Reward & Penalty* matematis.
* **Zero-Injury Tolerance:** Jika algoritma secara acak memilih area otot yang sedang cedera, fungsi *fitness* akan langsung menembakkan penalti ekstrem (-100), membunuh kromosom tersebut dari populasi agar tidak berevolusi menjadi hasil akhir.

---

## 🫁 Pilar 2: Bagaimana Infrastruktur Backend Bekerja

Sebuah algoritma secerdas apa pun tidak akan berguna jika tidak bisa diakses dengan cepat dan aman. Infrastruktur Python ini dirancang untuk "bernapas" secara efisien di lingkungan *cloud*.

```mermaid
graph TD
    %% Styling Node
    classDef client fill:#f8fafc,stroke:#0f172a,stroke-width:2px,color:#0f172a,font-family:monospace;
    classDef server fill:#f0fdf4,stroke:#166534,stroke-width:2px,color:#166534,font-family:monospace;
    classDef core fill:#eff6ff,stroke:#1e3a8a,stroke-width:2px,color:#1e3a8a,font-family:monospace;

    subgraph CDN ["🌐 Edge Network"]
        UI["Vue 3 SPA (Client)"]:::client
    end

    subgraph Cloud ["☁️ Cloud Infrastructure (Render Web Service)"]
        ASGI["Uvicorn (ASGI Server)"]:::server
        API["FastAPI (REST Controller)"]:::server
        
        subgraph Engine ["⚙️ AI Compute Engine"]
            Rules["Rule-Based Memory"]:::core
            GA["Genetic Optimizer"]:::core
            
            Rules -- "Filtered Search Space" --> GA
        end
        
        ASGI --> API
        API <--> |"Pydantic JSON Validation"| Engine
    end

    %% Network Flow
    UI -- "1. HTTP POST Payload" --> ASGI
    API -- "2. HTTP 201 (Schedule + X-Process-Time)" --> UI