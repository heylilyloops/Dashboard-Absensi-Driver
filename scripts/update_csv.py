"""
Tarik data absensi Driver & Asst Driver dari Google Sheets -> CSV per site.

- Membaca SEMUA tab yang namanya ada di SHEETS (berdasarkan nama tab, bukan GID).
- Normalisasi supaya dashboard tidak perlu menebak format:
    * ABSEN_DATE -> YYYY-MM-DD (handle '2026-09-01', '9/19/2026', maupun serial number Sheets)
    * TIME ABSEN IN/OUT, FINGER_TIME -> HH:MM:SS
    * JOBDESK -> 'DRIVER' / 'ASST DRIVER'
    * Tambah kolom SITE (nama tab)
- Output: data/<FILE>.csv + data/meta.json (waktu update & jumlah baris)
"""
import datetime as dt
import json
import os
import re

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1YKyOA-J7HpnUVfUSmOyxcgFLAJqi-6TPXIWi8Q0-nG8"

# nama tab di Sheets -> nama file CSV
SHEETS = {
    "NDC Jababeka": "NDC_JABABEKA.csv",
    "NDC Cikupa": "NDC_CIKUPA.csv",
    "NDC Sidoarjo": "NDC_SIDOARJO.csv",
}

COLUMNS = [
    "NIK", "NAMA", "JOBDESK", "FACILITY", "ABSEN_DATE", "ROSTER", "FINGER_TIME",
    "ROSTER PEOPLEPRO", "TIME ABSEN IN", "TIME ABSEN OUT", "ABSEN IN", "ABSEN OUT",
    "DESCRIPTION",
]

SHEETS_EPOCH = dt.date(1899, 12, 30)


def norm_date(v):
    if v in (None, ""):
        return ""
    if isinstance(v, (int, float)):
        return (SHEETS_EPOCH + dt.timedelta(days=int(v))).isoformat()
    s = str(v).strip()
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        y, mo, d = map(int, m.groups())
        return dt.date(y, mo, d).isoformat()
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})", s)  # format sheet Cikupa: M/D/YYYY
    if m:
        mo, d, y = map(int, m.groups())
        if mo > 12:  # jaga-jaga kalau ternyata D/M/YYYY
            mo, d = d, mo
        return dt.date(y, mo, d).isoformat()
    return s


def norm_time(v):
    if v in (None, ""):
        return ""
    if isinstance(v, (int, float)):
        secs = round((float(v) % 1) * 86400)
        return f"{secs // 3600:02d}:{secs % 3600 // 60:02d}:{secs % 60:02d}"
    s = str(v).strip()
    m = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?", s)
    if m:
        h, mi, se = m.group(1), m.group(2), m.group(3) or "00"
        return f"{int(h):02d}:{mi}:{se}"
    return s


def norm_jobdesk(v):
    s = str(v).strip().upper()
    if "ASS" in s:  # 'ASST TO DRIVER', 'ASS DRIVER'
        return "ASST DRIVER"
    if "DRIVER" in s:
        return "DRIVER"
    return s


def main():
    creds = Credentials.from_service_account_info(
        json.loads(os.environ["GOOGLE_CREDENTIALS"]),
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ],
    )
    book = gspread.authorize(creds).open_by_key(SPREADSHEET_ID)
    meta = {"updated_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=7))).isoformat(timespec="minutes"), "files": {}}

    for title, fname in SHEETS.items():
        ws = book.worksheet(title)
        rows = ws.get_all_values(
            value_render_option="UNFORMATTED_VALUE",
            date_time_render_option="SERIAL_NUMBER",
        )
        header = [str(h).strip() for h in rows[0]]
        df = pd.DataFrame(rows[1:], columns=header)
        df = df[[c for c in COLUMNS if c in df.columns]].copy()
        df = df[df["NIK"].astype(str).str.strip() != ""]

        df["ABSEN_DATE"] = df["ABSEN_DATE"].map(norm_date)
        for c in ["FINGER_TIME", "TIME ABSEN IN", "TIME ABSEN OUT"]:
            df[c] = df[c].map(norm_time)
        df["JOBDESK"] = df["JOBDESK"].map(norm_jobdesk)
        df["NIK"] = df["NIK"].astype(str).str.strip()
        df.insert(0, "SITE", title)

        df.to_csv(f"data/{fname}", index=False)
        meta["files"][fname] = len(df)
        print(f"OK {fname}: {len(df)} baris")

    with open("data/meta.json", "w") as f:
        json.dump(meta, f, indent=2)
    print("Selesai.")


if __name__ == "__main__":
    main()
