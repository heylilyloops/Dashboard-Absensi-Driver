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
    "RDC Tallo": "RDC_TALLO.csv",
}

# Kode ROSTER -> DESCRIPTION, dipakai kalau kolom DESCRIPTION kosong (mis. tab RDC Tallo)
ROSTER_STATUS = {
    "O": "OFF", "OFF": "OFF", "SHOFF": "OFF",
    "AL": "Cuti Tahunan", "CT": "Cuti Tahunan", "CM": "Cuti Menikah", "CB": "Cuti Bersalin",
    "SD": "Sakit dengan Surat Dokter", "S": "Sakit tanpa Surat Dokter", "SK": "Sakit tanpa Surat Dokter",
    "I": "Ijin 1 Hari (Pribadi)", "IJ": "Ijin 1 Hari (Pribadi)", "IZ": "Ijin 1 Hari (Pribadi)",
    "M": "Mangkir", "MK": "Mangkir", "A": "Mangkir", "ALPA": "Mangkir",
    "LK": "Dinas/Tgs Luar Kota (Perdin)", "DL": "Dinas/Tgs Luar Kota (Perdin)", "DK": "Dinas/Tgs Dalam Kota",
}
# Tab yang datanya lebih lengkap di file sumber site sendiri: dibaca langsung dari sana
# (Keterangan + status radius). Kalau file sumber tidak bisa dibuka, pakai tab di sheet master.
SOURCES = {
    "RDC Tallo": {
        "id": "161VFS8gaLSB9Ja48fgHczxTkgFFqwGIEVls4yJVtLj8",
        "tab": "Data Kehadiran",
        "cols": {"Date": "ABSEN_DATE", "Emp ID": "NIK", "Emp Name": "NAMA", "Job Ttl Name": "JOBDESK",
                 "BU": "FACILITY", "Check In": "TIME ABSEN IN", "Check Out": "TIME ABSEN OUT",
                 "Schedule": "ROSTER", "Keterangan": "DESCRIPTION"},
        "radius_tab": "MSSCicoList",
    },
}
SHIFT_RE = re.compile(r"^\s*(\S+)\s+(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})")

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
    for fmt in ("%d %b %Y", "%d %B %Y", "%d-%b-%Y"):  # format tab Tallo: '01 Oct 2026'
        try:
            return dt.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return s


def norm_time(v):
    if v in (None, ""):
        return ""
    if isinstance(v, (int, float)):
        secs = round((float(v) % 1) * 86400)
        return f"{secs // 3600:02d}:{secs % 3600 // 60:02d}:{secs % 60:02d}"
    s = str(v).strip()
    m = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AaPp][Mm])?", s)
    if m:
        h, mi, se, ap = int(m.group(1)), m.group(2), m.group(3) or "00", (m.group(4) or "").upper()
        if ap == "PM" and h < 12:
            h += 12
        elif ap == "AM" and h == 12:
            h = 0
        return f"{h:02d}:{mi}:{se}"
    return s


def fix_layout(df, title):
    """Samakan tab yang formatnya beda (mis. RDC Tallo) dengan format NDC."""
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = ""
    df[COLUMNS] = df[COLUMNS].fillna("").astype(str).replace({"nan": "", "None": ""})
    # ROSTER berisi 'M0047 08:50 - 16:30' & ROSTER PEOPLEPRO kosong -> pecah jadi kode + teks PeoplePro
    m = df["ROSTER"].str.extract(SHIFT_RE)
    split = m[0].notna() & (df["ROSTER PEOPLEPRO"].str.strip() == "")
    df.loc[split, "ROSTER PEOPLEPRO"] = df.loc[split, "ROSTER"].str.strip()
    df.loc[split, "ROSTER"] = m.loc[split, 0]
    # hari berstatus Mutasi = orang sudah pindah site -> bukan hari kerja di site ini
    mut = df["ROSTER"].str.strip().str.upper().eq("MUTASI") | df["DESCRIPTION"].str.strip().str.upper().eq("MUTASI")
    if mut.any():
        print(f"  {title}: {int(mut.sum())} baris Mutasi dikeluarkan")
        df = df[~mut].copy()
    # FACILITY hanya BU ('HCI') -> tambah lokasi dari nama tab ('HCI TALLO')
    city = title.split()[-1].upper()
    one = df["FACILITY"].str.strip().str.match(r"^\S+$")
    df.loc[one, "FACILITY"] = df.loc[one, "FACILITY"].str.strip().str.upper() + " " + city
    # DESCRIPTION kosong -> dari kode roster, atau 'Hadir' kalau ada jam absen
    empty = df["DESCRIPTION"].str.strip() == ""
    code = df["ROSTER"].str.strip().str.upper()
    has_time = (df["TIME ABSEN IN"].str.strip() != "") | (df["TIME ABSEN OUT"].str.strip() != "")
    from_code = code.map(ROSTER_STATUS)
    desc = from_code.where(from_code.notna(), "")
    desc = desc.where(~((desc == "") & has_time), "Hadir")
    df.loc[empty, "DESCRIPTION"] = desc[empty]
    left = df.loc[empty & (df["DESCRIPTION"] == ""), "ROSTER"].value_counts().head(15)
    if len(left):
        print(f"  {title}: kode roster tanpa status & tanpa jam (jadi 'tanpa keterangan'): {left.to_dict()}")
    return df


def norm_jobdesk(v):
    s = str(v).strip().upper()
    if "ASS" in s:  # 'ASST TO DRIVER', 'ASS DRIVER'
        return "ASST DRIVER"
    if "DRIVER" in s:
        return "DRIVER"
    return s


def read_source(gc, title):
    """Baca data site dari file sumbernya (lebih lengkap). None kalau gagal."""
    src = SOURCES[title]
    try:
        sh = gc.open_by_key(src["id"])
        rows = sh.worksheet(src["tab"]).get_all_values(
            value_render_option="UNFORMATTED_VALUE", date_time_render_option="SERIAL_NUMBER")
        hi = next(i for i, r in enumerate(rows) if "Emp ID" in [str(x).strip() for x in r])
        header = [str(h).strip() for h in rows[hi]]
        df = pd.DataFrame(rows[hi + 1:], columns=header)
        df = df[[c for c in src["cols"] if c in df.columns]].rename(columns=src["cols"])
        df = df[df["NIK"].astype(str).str.strip() != ""].copy()
        df["ABSEN_DATE"] = df["ABSEN_DATE"].map(norm_date)
        df["NIK"] = df["NIK"].astype(str).str.strip()
        # status radius dari log absen (MSSCicoList): InRadius In / Out = T/F
        if src.get("radius_tab"):
            try:
                rr = sh.worksheet(src["radius_tab"]).get_all_values(
                    value_render_option="UNFORMATTED_VALUE", date_time_render_option="SERIAL_NUMBER")
                rad = pd.DataFrame(rr[1:], columns=[str(h).strip() for h in rr[0]])
                rad = rad[["Emp ID", "Date", "InRadius In", "InRadius Out"]].copy()
                rad["NIK"] = rad["Emp ID"].astype(str).str.strip()
                rad["ABSEN_DATE"] = rad["Date"].map(norm_date)
                rad = rad.drop_duplicates(["NIK", "ABSEN_DATE"])
                lab = lambda v, kind: "" if str(v).strip() == "" else (
                    f"{kind} (In Radius)" if str(v).strip().upper() in ("T", "TRUE") else f"{kind} (Out Radius)")
                rad["ABSEN IN"] = rad["InRadius In"].map(lambda v: lab(v, "Hadir"))
                rad["ABSEN OUT"] = rad["InRadius Out"].map(lambda v: lab(v, "Out"))
                df = df.merge(rad[["NIK", "ABSEN_DATE", "ABSEN IN", "ABSEN OUT"]], on=["NIK", "ABSEN_DATE"], how="left")
            except Exception as e:  # noqa: BLE001
                print(f"  {title}: status radius tidak terbaca ({e})")
        ket = (df["DESCRIPTION"].astype(str).str.strip() != "").sum()
        print(f"  {title}: dibaca dari file sumber ({len(df)} baris, {ket} dengan Keterangan)")
        return df
    except Exception as e:  # noqa: BLE001
        print(f"  {title}: file sumber tidak bisa dibuka ({e}) -> pakai tab di sheet master")
        return None


def main():
    creds = Credentials.from_service_account_info(
        json.loads(os.environ["GOOGLE_CREDENTIALS"]),
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ],
    )
    book = gspread.authorize(creds).open_by_key(SPREADSHEET_ID)
    all_niks, min_date = set(), "9999"
    meta = {"updated_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=7))).isoformat(timespec="minutes"), "files": {}}

    gc = gspread.authorize(creds)
    for title, fname in SHEETS.items():
        df = read_source(gc, title) if title in SOURCES else None
        if df is None:
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
        df = fix_layout(df, title)
        df["NIK"] = df["NIK"].astype(str).str.strip()
        df.insert(0, "SITE", title)

        all_niks |= set(df["NIK"].map(norm_nik))
        min_date = min(min_date, df["ABSEN_DATE"].min())
        df.to_csv(f"data/{fname}", index=False)
        meta["files"][fname] = len(df)
        print(f"OK {fname}: {len(df)} baris")

    meta["variable_income"] = sync_variable_income(all_niks, min_date)

    with open("data/meta.json", "w") as f:
        json.dump(meta, f, indent=2)
    print("Selesai.")


# ── Data OT approved & insentif dari dashboard Variable Income (repo partner) ──
VI_URL = "https://raw.githubusercontent.com/rahmatpambudi-dot/variable-income/main/dashboard_variable_income.html"


def norm_nik(n):
    """Sama dengan normalize_nik() di repo Variable Income."""
    n = str(n).strip()
    try:
        return str(int(n))
    except ValueError:
        return n.upper()


def sync_variable_income(niks=None, min_date=""):
    """Ambil DRIVERS dari dashboard Variable Income -> data/VI_DAILY.csv.
    Hanya jam OT approved & tanda insentif (tanpa rupiah). Kalau gagal, file lama dipertahankan."""
    import urllib.request
    try:
        with urllib.request.urlopen(VI_URL, timeout=60) as r:
            html = r.read().decode("utf-8")
        drivers = json.loads(re.search(r"const DRIVERS=(\[.*?\]);", html, re.S).group(1))
        upd = re.search(r"Update: ([^<\"]+)", html)
    except Exception as e:  # noqa: BLE001
        print(f"WARN Variable Income tidak bisa diambil: {e}")
        return {"status": "gagal", "error": str(e)[:200]}

    rows = {}
    for d in drivers:
        nik = norm_nik(d.get("nik", ""))
        for date, v in (d.get("dates") or {}).items():
            k = (nik, date)
            rows.setdefault(k, [0.0, 0])[0] += float(v.get("hours") or 0)
        for date, v in (d.get("ins_dates") or {}).items():
            if (v or 0) > 0:
                rows.setdefault((nik, date), [0.0, 0])[1] = 1
    site = {norm_nik(d["nik"]): (d.get("site", ""), d.get("bu", "")) for d in drivers}
    out = pd.DataFrame(
        [(n, dt_, round(h, 2), i, *site.get(n, ("", ""))) for (n, dt_), (h, i) in rows.items()],
        columns=["NIK_N", "DATE", "OT_HOURS", "INSENTIF", "VI_SITE", "VI_BU"],
    ).sort_values(["DATE", "NIK_N"])
    if niks:  # cukup NIK & periode yang ada di data absensi
        out = out[out.NIK_N.isin(niks) & (out.DATE >= min_date)]
        site = {n: v for n, v in site.items() if n in niks}
    # daftar site per NIK (dipakai untuk override site, mis. JAKARTA (KLS))
    pd.DataFrame([(n, s, b) for n, (s, b) in site.items()], columns=["NIK_N", "VI_SITE", "VI_BU"]).to_csv(
        "data/VI_PERSONEL.csv", index=False)
    out.to_csv("data/VI_DAILY.csv", index=False)
    ot_dates = out.loc[out.OT_HOURS > 0, "DATE"]
    ins_dates = out.loc[out.INSENTIF > 0, "DATE"]
    info = {
        "status": "ok",
        "update_label": upd.group(1).strip() if upd else "",
        "ot_until": ot_dates.max() if len(ot_dates) else "",
        "insentif_until": ins_dates.max() if len(ins_dates) else "",
        "rows": len(out),
    }
    print(f"OK VI_DAILY.csv: {len(out)} baris, OT s/d {info['ot_until']}, insentif s/d {info['insentif_until']}")
    return info


if __name__ == "__main__":
    main()
