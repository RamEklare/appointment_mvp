
import os
import streamlit as st
import pandas as pd
from datetime import datetime
from appointment_core import (
    load_patients, load_doctors_and_availability, search_patient, visit_duration_mins,
    get_available_slots, book_appointment, send_message, export_admin_report, get_template_path
)

st.set_page_config(page_title="Clinic Scheduling MVP", page_icon="🗓️", layout="wide")

st.title("🗓️ Medical Appointment Scheduling – MVP-1")

with st.sidebar:
    st.header("Admin")
    if st.button("Export Admin Report"):
        path = export_admin_report()
        st.success(f"Exported: {os.path.basename(path)}")
        with open(path, "rb") as f:
            st.download_button("Download Report", f, file_name=os.path.basename(path))

# Step 1: Greeting & Patient Lookup
st.subheader("1) Patient Greeting & Lookup")
col1, col2, col3 = st.columns(3)
with col1:
    name = st.text_input("Full Name", placeholder="e.g., Aarav Patel")
with col2:
    dob = st.date_input("Date of Birth")
with col3:
    preferred_doctor = st.selectbox("Preferred Doctor (optional)", [""] + list(load_doctors_and_availability()[0]["doctor_name"].unique()))

if st.button("Lookup Patient"):
    patients = load_patients()
    match = search_patient(patients, name, dob.isoformat())
    if match is None:
        st.info("New patient detected.")
        st.session_state["patient"] = {"name": name, "dob": dob.isoformat(), "patient_id":"NEW",
                                       "first_name": name.split()[0] if name else "", "last_name": " ".join(name.split()[1:]) if name else ""}
        st.session_state["is_new"] = True
    else:
        st.success(f"Returning patient: {match['first_name']} {match['last_name']} (ID: {match['patient_id']})")
        st.session_state["patient"] = match
        st.session_state["is_new"] = False

# Step 2: Smart Scheduling
st.subheader("2) Smart Scheduling")
if "patient" in st.session_state:
    doctors, availability, holidays = load_doctors_and_availability()
    # Pick doctor
    doc = None
    if preferred_doctor:
        doc = doctors[doctors["doctor_name"] == preferred_doctor].iloc[0].to_dict()
    else:
        # default to patient's preferred or first
        pdoc = st.session_state["patient"].get("preferred_doctor_id")
        if pdoc and pdoc in list(doctors["doctor_id"]):
            doc = doctors[doctors["doctor_id"] == pdoc].iloc[0].to_dict()
        else:
            doc = doctors.iloc[0].to_dict()
    st.write(f"Selected Doctor: **{doc['doctor_name']}** ({doc['specialty']}) – {doc['location']}")

    # Date selection
    dates = sorted(availability[availability["doctor_id"] == doc["doctor_id"]]["date"].unique())
    date_choice = st.selectbox("Pick a date", dates)

    # Duration based on new vs returning
    minutes = visit_duration_mins(st.session_state["is_new"])
    visit_type = "New" if st.session_state["is_new"] else "Returning"
    st.caption(f"Visit Type: **{visit_type}** → Duration **{minutes} minutes**")

    # Slots
    slots = get_available_slots(availability, doc["doctor_id"], date_choice, minutes)
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
            carrier = st.text_input("Insurance Carrier", value=st.session_state["patient"].get("insurance_carrier",""))
        with colB:
            member_id = st.text_input("Member ID", value=st.session_state["patient"].get("insurance_member_id",""))
        with colC:
            group = st.text_input("Group", value=st.session_state["patient"].get("insurance_group",""))

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

                # Step 5: Form Distribution (email templates after confirmation)
                st.subheader("5) Form Distribution")
                intake = get_template_path("intake_form_template.html")
                consent = get_template_path("consent_form_template.html")
                with open(intake,"rb") as f1, open(consent,"rb") as f2:
                    st.download_button("Download Intake Form", f1, file_name="intake_form.html")
                    st.download_button("Download Consent Form", f2, file_name="consent_form.html")
                send_message("EMAIL", email_to or "unknown@example.com", "Intake Forms",
                             "Please complete the attached intake and consent forms before your visit.", booking_id)

                # Step 6: Reminder System (3 reminders)
                st.subheader("6) Reminder System (Simulated)")
                send_message("EMAIL", email_to or "unknown@example.com", "Reminder 1",
                             "Friendly reminder about your appointment. No action required.", booking_id)
                send_message("EMAIL", email_to or "unknown@example.com", "Reminder 2 – Action Required",
                             "Have you filled the forms? Please confirm your visit.", booking_id)
                send_message("SMS", sms_to or "9999999999", "Reminder 3 – Action Required",
                             "Confirm visit? Reply with reason if cancelling.", booking_id)
                st.info("Reminders logged in communications_log.csv")

            except Exception as e:
                st.error(f"Booking failed: {e}")

# Admin views
st.divider()
st.subheader("📊 Admin Review – Current Data")
colx, coly = st.columns(2)
with colx:
    st.caption("Patients (simulated EMR)")
    st.dataframe(load_patients(), use_container_width=True, height=250)
with coly:
    st.caption("Doctor Availability")
    st.dataframe(load_doctors_and_availability()[1].query("booked == 0").head(200), use_container_width=True, height=250)

st.caption("Bookings Ledger")
if os.path.exists("bookings.xlsx"):
    st.dataframe(pd.read_excel("bookings.xlsx", sheet_name="bookings").tail(50), use_container_width=True, height=250)
else:
    st.write("No bookings yet.")
