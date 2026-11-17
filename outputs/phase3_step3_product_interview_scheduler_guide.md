> **STUBBED**: this output comes from a stubbed step, not a working feature.

# Interview Scheduler Guide

## Overview
A lightweight Flask‑based web app for SME HR teams in Egypt to create interview slots, share a public booking link, sync with calendars, and export schedules.

## Architecture
- **Frontend**: HTML + Bootstrap, minimal JavaScript for form handling.
- **Backend**: Python 3, Flask, Flask‑Login, Flask‑SQLAlchemy.
- **Database**: SQLite (local) or PostgreSQL (production).
- **Integrations**: iCal generation, email via Flask‑Mail.

## Required Packages

pip install Flask Flask-Login Flask-SQLAlchemy Flask-Mail python-dotenv icalendar


## Database Schema (SQLAlchemy models)
- **User**: id, email, password_hash, role (HR admin/member).
- **InterviewSlot**: id, user_id (FK), start_time, end_time, duration, is_booked.
- **CandidateBooking**: id, slot_id (FK), candidate_name, candidate_email, booked_at.

## Core Features Implementation
### 1. User Authentication
- Set up Flask‑Login with User model.
- Register/login routes using email + hashed password.

### 2. Interview Slot Creation
- Form for HR to select date, start time, duration.
- Store slots; calculate `end_time` = `start_time + duration`.

### 3. Public Booking Link
- Public route `/book/<slot_id>` displays slot details.
- Candidate fills name & email → creates CandidateBooking, marks slot as booked, sends confirmation email.

### 4. Calendar Sync (iCal)
- Generate `.ics` file on the fly:
python
from icalendar import Calendar, Event
cal = Calendar()
event = Event()
event.add('dtstart', slot.start_time)
event.add('dtend', slot.end_time)
cal.add_component(event)
return Response(cal.to_ical(), mimetype='text/calendar')

- Provide download button on HR dashboard.

### 5. CSV Export
- Query all booked slots, write to `StringIO` with `csv.writer`.
- Return as `text/csv` attachment.

## Deployment Tips
- Use `gunicorn` + Nginx for production.
- Store secrets (mail server, DB URL) in `.env`.
- Set up a daily backup of the database.

## Next Steps
- Add tiered subscription checks (team size).
- Implement role‑based access (admin vs. member).
- Localize UI strings to Arabic (e.g., "جدولة المقابلات").
