# Dashboard Absensi & Kehadiran Driver

Sumber data: Google Sheets "Monitoring Absensi Driver & Asst Driver 2026" (tab NDC Jababeka, NDC Cikupa, NDC Sidoarjo).
Alur: Sheets → GitHub Actions (setiap hari 07.00 WIB) → `data/*.csv` → `index.html` (GitHub Pages).

## Isi repo
| File | Fungsi |
|---|---|
| `.github/workflows/update-csv.yml` | Jadwal harian + tombol manual |
| `scripts/update_csv.py` | Tarik 3 tab, rapikan format tanggal/jam/jobdesk, simpan CSV per site |
| `index.html` | Dashboard |
| `data/` | Diisi otomatis oleh workflow (jangan diedit manual) |

## Setup (sekali saja)
1. Buat repo baru **public** bernama `Dashboard-Absensi-Driver` di akun `heylilyloops`, upload semua file ini.
2. **Service account**: pakai yang sama dengan repo Dashboard-Cost-Delivery-Internal-.
   - Share Sheets absensi ke email service account tersebut (Viewer).
   - Repo baru → Settings → Secrets and variables → Actions → New secret `GOOGLE_CREDENTIALS` → paste isi file JSON key.
3. Settings → Actions → General → Workflow permissions → **Read and write** → Save.
4. Tab Actions → "Update CSV Absensi dari Google Sheets" → **Run workflow**. Cek folder `data/` terisi.
5. Settings → Pages → Source: branch `main`, folder `/ (root)` → Save. Dashboard aktif di
   `https://heylilyloops.github.io/Dashboard-Absensi-Driver/`

Kalau nama repo berbeda, ubah `BASE_URL` di bagian CONFIG `index.html`.

## Menambah site baru
Tambahkan baris di `SHEETS` pada `scripts/update_csv.py` dan nama file di `CONFIG.FILES` pada `index.html`.
