import os
import uuid
from datetime import datetime, timedelta, date, time
import pandas as pd
import shutil

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
PATIENT_CSV = os.path.join(DATA_DIR, "patients_sample_50.csv")
DOCTOR_XLSX = os.path.join(DATA_DIR, "doctor_schedules_sample.xlsx")
BOOKINGS_XLSX = os.path.join(os.path.dirname(__file__), "bookings.xlsx")
COMM_LOG_CSV = os.path.join(os.path.dirname(__file__), "communications_log.csv")
TEMPLATE_DIR = os.path.join(DATA_DIR, "appointment_templates")

def load_patients(path: str = PATIENT_CSV) -> pd.DataFrame:
    return pd.read_csv(path)

def load_doctors_and_availability(path: str = DOCTOR_XLSX):
    # open the Excel file once and return three dataframes
    xls = pd.ExcelFile(path, engine='openpyxl')
    doctors = pd.read_excel(xls, "doctors")
    availability = pd.read_excel(xls, "availability")
    holidays = pd.read_excel(xls, "holidays")
    # ensure dtypes
    availability["booked"] = availability["booked"].astype(int)
    return doctors, availability, holidays

def search_patient(patients_df: pd.DataFrame, name: str, dob: str):
    name = name.strip().lower()
    parts = name.split()
    matches = patients_df[
        (patients_df["dob"].astype(str) == dob) &
        (
            patients_df["first_name"].str.lower().isin(parts) |
            patients_df["last_name"].str.lower().isin(parts) |
            (patients_df["first_name"].str.lower() + " " + patients_df["last_name"].str.lower() == name)
        )
    ]
    if len(matches) == 0:
        return None  # new patient
    else:
        return matches.iloc[0].to_dict()

def visit_duration_mins(is_new: bool) -> int:
    return 60 if is_new else 30

def get_available_slots(availability_df: pd.DataFrame, doctor_id: str, date_str: str, minutes: int):
    day_slots = availability_df[
        (availability_df["doctor_id"] == doctor_id) &
        (availability_df["date"] == date_str) &
        (availability_df["booked"] == 0)
    ].copy().sort_values(["date", "slot_start"])
    if minutes == 30:
        return day_slots[["slot_start", "slot_end", "location"]].to_dict(orient="records")
    else:
        out = []
        prev = None
        for _, row in day_slots.iterrows():
            if prev is None:
                prev = row
                continue
            if prev["slot_end"] == row["slot_start"]:
                out.append({"slot_start": prev["slot_start"], "slot_end": row["slot_end"], "location": row["location"]})
            prev = row
        return out

def book_appointment(patient: dict, doctor_row: dict, date_str: str, slot_start: str,
                     slot_end: str, visit_type: str, insurance: dict, notes: str = ""):
    # load everything once
    doctors, availability, holidays = load_doctors_and_availability()

    # For 60-min, block two 30-min slots; for 30-min, block one
    to_block = [(slot_start, slot_end)]
    if visit_type.lower() == "new":
        start_h, start_m = map(int, slot_start.split(":"))
        end_h, end_m = map(int, slot_end.split(":"))
        total = (end_h * 60 + end_m) - (start_h * 60 + start_m)
        if total == 60:
            mid_mins = start_h * 60 + start_m + 30
            mid = f"{mid_mins // 60:02d}:{mid_mins % 60:02d}"
            to_block = [(slot_start, mid), (mid, slot_end)]

    for st, en in to_block:
        idx = availability.index[
            (availability["doctor_id"] == doctor_row["doctor_id"]) &
            (availability["date"] == date_str) &
            (availability["slot_start"] == st) &
            (availability["slot_end"] == en) &
            (availability["booked"] == 0)
        ]
        if len(idx) == 0:
            raise ValueError("Requested time is no longer available.")
        availability.loc[idx, "booked"] = 1

    # Back up the Excel file before overwriting
    if os.path.exists(DOCTOR_XLSX):
        shutil.copy(DOCTOR_XLSX, DOCTOR_XLSX + ".bak")

    # Save all three sheets back once
    with pd.ExcelWriter(DOCTOR_XLSX, engine="openpyxl") as writer:
        doctors.to_excel(writer, sheet_name="doctors", index=False)
        availability.to_excel(writer, sheet_name="availability", index=False)
        holidays.to_excel(writer, sheet_name="holidays", index=False)

    # Append booking to bookings.xlsx
    booking_id = str(uuid.uuid4())[:8]
    book_row = pd.DataFrame([{
        "booking_id": booking_id,
        "patient_id": patient.get("patient_id", "NEW"),
        "patient_name": f'{patient.get("first_name", "")} {patient.get("last_name", "")}'.strip() or patient.get("name", ""),
        "doctor_id": doctor_row["doctor_id"],
        "doctor_name": doctor_row["doctor_name"],
        "date": date_str,
        "slot_start": slot_start,
        "slot_end": slot_end,
        "location": doctor_row["location"],
        "visit_type": visit_type.lower(),
        "insurance_carrier": insurance.get("carrier", ""),
        "insurance_member_id": insurance.get("member_id", ""),
        "insurance_group": insurance.get("group", ""),
        "status": "CONFIRMED",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "notes": notes
    }])

    if os.path.exists(BOOKINGS_XLSX):
        existing = pd.read_excel(BOOKINGS_XLSX, sheet_name="bookings")
        all_rows = pd.concat([existing, book_row], ignore_index=True)
        with pd.ExcelWriter(BOOKINGS_XLSX, engine="openpyxl") as writer:
            all_rows.to_excel(writer, index=False, sheet_name="bookings")
    else:
        with pd.ExcelWriter(BOOKINGS_XLSX, engine="openpyxl") as writer:
            book_row.to_excel(writer, index=False, sheet_name="bookings")

    return booking_id

def send_message(channel: str, to: str, subject: str, message: str, booking_id: str = None):
    row = pd.DataFrame([{
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "channel": channel,
        "to": to,
        "subject": subject,
        "message": message,
        "booking_id": booking_id or ""
    }])
    if os.path.exists(COMM_LOG_CSV):
        existing = pd.read_csv(COMM_LOG_CSV)
        all_rows = pd.concat([existing, row], ignore_index=True)
        all_rows.to_csv(COMM_LOG_CSV, index=False)
    else:
        row.to_csv(COMM_LOG_CSV, index=False)

def export_admin_report():
    report_path = os.path.join(os.path.dirname(__file__),
                               f"admin_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
    doctors, avail, holidays = load_doctors_and_availability()
    patients = load_patients()
    bookings = pd.read_excel(BOOKINGS_XLSX, sheet_name="bookings") if os.path.exists(BOOKINGS_XLSX) else pd.DataFrame()
    with pd.ExcelWriter(report_path, engine="openpyxl") as writer:
        patients.to_excel(writer, index=False, sheet_name="patients")
        doctors.to_excel(writer, index=False, sheet_name="doctors")
        avail.to_excel(writer, index=False, sheet_name="availability")
        holidays.to_excel(writer, index=False, sheet_name="holidays")
        bookings.to_excel(writer, index=False, sheet_name="bookings")
    return report_path

def get_template_path(name: str) -> str:
    path = os.path.join(TEMPLATE_DIR, name)
    if os.path.exists(path):
        return path
    raise FileNotFoundError(f"Template not found: {name}")
