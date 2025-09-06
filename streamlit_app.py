import os
import uuid
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from appointment_core import (
    load_patients, load_doctors_and_availability, search_patient, visit_duration_mins,
    get_available_slots, book_appointment, send_message, export_admin_report, get_template_path
)

# ----------------------
# Config & helpers
# ----------------------
st.set_page_config(page_title="Clinic Scheduling MVP", page_icon="🗓️", layout="wide")
COMM_LOG = "communications_log.csv"

def ensure_comm_log_exists():
    if not os.path.exists(COMM_LOG):
        df = pd.DataFrame(columns=[
            "comm_id", "booking_id", "patient_id", "patient_name", "email", "phone",
            "reminder_no", "channel", "scheduled_at", "action_required", "status", "response", "created_at"
        ])
        df.to_csv(COMM_LOG, index=False)


def append_comm(row: dict):
    ensure_comm_log_exists()
    df = pd.read_csv(COMM_LOG)
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_csv(COMM_LOG, index=False)


def mark_comm_response(comm_id, status, response=""):
    ensure_comm_log_exists()
    df = pd.read_csv(COMM_LOG)
    mask = df["comm_id"] == comm_id
    if mask.any():
        df.loc[mask, "status"] = status
        df.loc[mask, "response"] = response
        df.to_csv(COMM_LOG, index=False)
        return True
    return False


# ----------------------
# Page UI
# ----------------------
st.title("🗓️ Medical Appointment Scheduling")

# Load static data once to avoid repeated IO
try:
    doctors_df, availability_df, holidays_df = load_doctors_and_availability()
except Exception as e:
    st.error(f"Failed to load doctors/availability: {e}")
    doctors_df = pd.DataFrame()
    availability_df = pd.DataFrame()
    holidays_df = pd.DataFrame()

# Sidebar admin
with st.sidebar:
    st.header("Admin")
    if st.button("Export Admin Report"):
        try:
            path = export_admin_report()
            st.success(f"Exported: {os.path.basename(path)}")
            with open(path, "rb") as f:
                st.download_button("Download Report", f, file_name=os.path.basename(path))
        except Exception as e:
            st.error(f"Export failed: {e}")

# Initialize session_state keys
if "patient" not in st.session_state:
    st.session_state["patient"] = {}
if "is_new" not in st.session_state:
    st.session_state["is_new"] = True

# Step 1: Greeting & Patient Lookup
st.subheader("1) Patient Greeting & Lookup")
col1, col2, col3 = st.columns(3)
with col1:
    name = st.text_input("Full Name", placeholder="e.g., Aarav Patel")
with col2:
    dob = st.date_input("Date of Birth")
with col3:
    # Build doctor list safely
    doctor_names = [""]
    if not doctors_df.empty:
        doctor_names = [""] + sorted(list(doctors_df["doctor_name"].unique()))
    preferred_doctor = st.selectbox("Preferred Doctor (optional)", doctor_names)

if st.button("Lookup Patient"):
    try:
        patients = load_patients()
        match = search_patient(patients, name, dob.isoformat())
        if match is None:
            st.info("New patient detected.")
            st.session_state["patient"] = {
                "name": name,
                "dob": dob.isoformat(),
                "patient_id": "NEW",
                "first_name": name.split()[0] if name else "",
                "last_name": " ".join(name.split()[1:]) if name else ""
            }
            st.session_state["is_new"] = True
        else:
            st.success(f"Returning patient: {match['first_name']} {match['last_name']} (ID: {match['patient_id']})")
            st.session_state["patient"] = match
            st.session_state["is_new"] = False
    except Exception as e:
        st.error(f"Patient lookup failed: {e}")

# Step 2: Smart Scheduling
st.subheader("2) Smart Scheduling")
if st.session_state.get("patient"):
    try:
        doctors = doctors_df
        availability = availability_df
        holidays = holidays_df

        # Pick doctor
        doc = None
        if preferred_doctor:
            sel = doctors[doctors["doctor_name"] == preferred_doctor]
            if not sel.empty:
                doc = sel.iloc[0].to_dict()
        if doc is None:
            # default to patient's preferred or first
            pdoc = st.session_state["patient"].get("preferred_doctor_id")
            if pdoc and pdoc in list(doctors["doctor_id"]):
                doc = doctors[doctors["doctor_id"] == pdoc].iloc[0].to_dict()
            else:
                doc = doctors.iloc[0].to_dict() if not doctors.empty else {"doctor_name":"Unknown","specialty":"","location":"","doctor_id":None}

        st.write(f"Selected Doctor: **{doc['doctor_name']}** ({doc.get('specialty','')}) – {doc.get('location','')}")

        # Date selection
        if not availability.empty and doc.get("doctor_id") is not None:
            dates = sorted(availability[availability["doctor_id"] == doc["doctor_id"]]["date"].unique())
        else:
            dates = []
        if not dates:
            st.warning("No availability data for selected doctor.")
        date_choice = st.selectbox("Pick a date", dates) if dates else None

        # Duration based on new vs returning
        minutes = visit_duration_mins(st.session_state.get("is_new", True))
        visit_type = "New" if st.session_state.get("is_new", True) else "Returning"
        st.caption(f"Visit Type: **{visit_type}** → Duration **{minutes} minutes**")

        # Slots
        slots = get_available_slots(availability, doc.get("doctor_id"), date_choice, minutes) if date_choice else []
        if not slots:
            st.warning("No slots available for the selected date. Try another date.")
        else:
            slot_labels = [f"{s['slot_start']}-{s['slot_end']} @ {s['location']}" for s in slots]
            pick = st.selectbox("Available Slots", slot_labels)
            pick_idx = slot_labels.index(pick)
            chosen = slots[pick_idx]

            # Step 3: Insurance Collection
            st.subheader("3) Insurance Collection")
            colA, colB, colC = st.columns(3)
            with colA:
                carrier = st.text_input("Insurance Carrier", value=st.session_state["patient"].get("insurance_carrier", ""))
            with colB:
                member_id = st.text_input("Member ID", value=st.session_state["patient"].get("insurance_member_id", ""))
            with colC:
                group = st.text_input("Group", value=st.session_state["patient"].get("insurance_group", ""))

            # Step 4: Confirmation & Calendar (simulated Calendly by writing to Excel)
            st.subheader("4) Appointment Confirmation")
            notes = st.text_area("Notes to clinic (optional)")
            if st.button("Confirm & Book Appointment"):
                try:
                    booking_id = book_appointment(
                        st.session_state["patient"], doc, date_choice, chosen["slot_start"], chosen["slot_end"],
                        visit_type, {"carrier": carrier, "member_id": member_id, "group": group}, notes
                    )
                    st.success(f"Booked! Confirmation ID: {booking_id}")

                    # Simulated emails/SMS
                    email_to = st.session_state["patient"].get("email", "")
                    sms_to = st.session_state["patient"].get("phone", "")
                    send_message("EMAIL", email_to or "unknown@example.com", "Appointment Confirmation",
                                 f"Your appointment is confirmed on {date_choice} at {chosen['slot_start']} with {doc['doctor_name']}.", booking_id)
                    send_message("SMS", sms_to or "9999999999", "Appointment Confirmation",
                                 f"Appt {date_choice} {chosen['slot_start']} with {doc['doctor_name']} – Reply YES to confirm.", booking_id)
                    st.balloons()

                    # Step 5: Form Distribution (download links)
                    st.subheader("5) Form Distribution")
                    try:
                        intake = get_template_path("New Patient Intake Form.pdf")
                        consent = get_template_path("consent_form_template.html")
                        with open(intake, "rb") as f1, open(consent, "rb") as f2:
                            st.download_button("Download Patient Intake Form", f1, file_name="Patient_intake_form.pdf")
                            st.download_button("Download Consent Form", f2, file_name="consent_form.html")
                        send_message("EMAIL", email_to or "unknown@example.com", "Intake Forms",
                                     "Please complete the attached intake and consent forms before your visit.", booking_id)
                    except Exception as e:
                        st.warning(f"Could not attach templates: {e}")

                    # Step 6: Reminder System (3 reminders)
                    st.subheader("6) Reminder System (Simulated)")
                    ensure_comm_log_exists()
                    now = datetime.utcnow()

                    # 1st reminder: regular (no action required)
                    r1 = {
                        "comm_id": str(uuid.uuid4()),
                        "booking_id": booking_id,
                        "patient_id": st.session_state["patient"].get("patient_id","NEW"),
                        "patient_name": st.session_state["patient"].get("name",""),
                        "email": email_to or "unknown@example.com",
                        "phone": sms_to or "9999999999",
                        "reminder_no": 1,
                        "channel": "EMAIL",
                        "scheduled_at": (now + timedelta(days=7)).isoformat(),
                        "action_required": False,
                        "status": "sent",
                        "response": "",
                        "created_at": now.isoformat()
                    }
                    append_comm(r1)

                    # 2nd reminder: asks "Have you filled the forms?" (action required on email)
                    r2 = r1.copy()
                    r2.update({
                        "comm_id": str(uuid.uuid4()),
                        "reminder_no": 2,
                        "channel": "EMAIL",
                        "scheduled_at": (now + timedelta(days=3)).isoformat(),
                        "action_required": True,
                        "status": "sent",
                    })
                    append_comm(r2)

                    # 3rd reminder: SMS asking to confirm visit (action required)
                    r3 = r1.copy()
                    r3.update({
                        "comm_id": str(uuid.uuid4()),
                        "reminder_no": 3,
                        "channel": "SMS",
                        "scheduled_at": (now + timedelta(days=1)).isoformat(),
                        "action_required": True,
                        "status": "sent",
                    })
                    append_comm(r3)

                    st.info("3 reminders scheduled and logged in communications_log.csv")

                except Exception as e:
                    st.error(f"Booking failed: {e}")

    except Exception as e:
        st.error(f"Scheduling module failed: {e}")

# Admin views
st.divider()
st.subheader("📊 Admin Review – Current Data")
colx, coly = st.columns(2)
with colx:
    st.caption("Patients (simulated EMR)")
    try:
        st.dataframe(load_patients(), use_container_width=True, height=250)
    except Exception as e:
        st.write(f"Unable to load patients: {e}")
with coly:
    st.caption("Doctor Availability")
    try:
        st.dataframe(availability_df.query("booked == 0").head(200), use_container_width=True, height=250)
    except Exception:
        st.write("No availability to show")

st.caption("Bookings Ledger")
if os.path.exists("bookings.xlsx"):
    try:
        st.dataframe(pd.read_excel("bookings.xlsx", sheet_name="bookings").tail(50), use_container_width=True, height=250)
    except Exception as e:
        st.write(f"Error reading bookings.xlsx: {e}")
else:
    st.write("No bookings yet.")

# Admin: Communications log management (confirmations / cancellations)
st.subheader("Communications Log & Actions")
ensure_comm_log_exists()
comm_df = pd.read_csv(COMM_LOG)
if comm_df.empty:
    st.write("No communications logged yet.")
else:
    st.dataframe(comm_df.sort_values("created_at", ascending=False).head(200), use_container_width=True, height=300)

    st.markdown("**Review / Update a communication entry**")
    comm_ids = list(comm_df["comm_id"])
    sel_comm = st.selectbox("Select comm_id to update", [""] + comm_ids)
    if sel_comm:
        row = comm_df[comm_df["comm_id"] == sel_comm].iloc[0].to_dict()
        st.write(row)
        col1, col2 = st.columns(2)
        with col1:
            new_status = st.selectbox("New status", ["sent", "confirmed", "cancelled", "no_response"], index=0)
        with col2:
            response_text = st.text_input("Response / Cancellation reason (optional)")
        if st.button("Apply Update"):
            ok = mark_comm_response(sel_comm, new_status, response_text)
            if ok:
                st.success("Updated communication entry")
            else:
                st.error("Failed to update entry")

st.caption("Reminder System\n3 automated reminders with confirmations on their email and SMS.\n1st reminder is regular, 2nd and 3rd reminders require action:\n1) Have they filled the forms?\n2) Is the visit confirmed? If not, capture cancellation reason.")

st.caption("Scheduling & tracking")

# Small footer
st.write("\n---\nMade with ❤️ — Clinic Scheduling MVP")
