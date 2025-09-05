# Medical Appointment Scheduling – MVP-1

This is a minimal, local-only MVP with synthetic data and a Streamlit UI.

## Files
- `data/patients_sample_50.csv` – 50 synthetic patients
- `data/doctor_schedules_sample.xlsx` – doctors, availability (next 14 days, 30-min slots), holidays sheet
- `data/appointment_templates/` – `intake_form_template.html`, `consent_form_template.html`
- `appointment_core.py` – core Python functions
- `streamlit_app.py` – Streamlit app
- `bookings.xlsx` – ledger of confirmed bookings (created/updated by the app)
- `communications_log.csv` – simulated email/SMS log
- `requirements.txt`

## Run locally
```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Notes
- Calendly is simulated by writing to `bookings.xlsx` and marking availability in `data/doctor_schedules_sample.xlsx`.
- Email/SMS are simulated via entries in `communications_log.csv`. Replace `send_message` with real integrations later.
