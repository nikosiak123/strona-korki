# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview

This is a Polish online tutoring platform ("Zakręcone Korepetycje") that handles lesson bookings, scheduling, and client management. The platform integrates with Airtable for data storage, Microsoft Teams for video meetings, and Facebook Messenger for notifications.

## Architecture

### Technology Stack
- **Backend**: Flask (Python) with gunicorn
- **Frontend**: Vanilla HTML/CSS/JavaScript (no framework)
- **Database**: Airtable (via pyairtable API)
- **Infrastructure**: Dockerized application (Cloud Run ready)
- **External Services**: 
  - Microsoft Graph API (Teams meeting generation)
  - Facebook Messenger API (notifications)
  - Selenium + Chrome (Facebook profile search automation)

### Core Data Models (Airtable Tables)

1. **Korepetytorzy (Tutors)**
   - Stores tutor schedules (Poniedziałek, Wtorek, etc.)
   - Subject qualifications (Przedmioty) and teaching levels (PoziomNauczania)
   - Contact links (LINK field for Facebook profile)

2. **Klienci (Clients)**
   - Identified by ClientID (PSID from Messenger)
   - Stores first name (Imię), last name (Nazwisko)
   - Facebook profile link (LINK) populated via automated search

3. **Rezerwacje (Reservations)**
   - Single lessons with Status field: "Dostępny", "Oczekuje na płatność", "Opłacona", "Niedostępny", "Przeniesiona", "Anulowana (brak płatności)"
   - Typ field: "Jednorazowa" or "Cykliczna"
   - ManagementToken for client-side management
   - JestTestowa field marks test lessons (free trial)

4. **StaleRezerwacje (Cyclic Reservations)**
   - Recurring weekly schedules
   - Aktywna field determines if still active
   - Must be confirmed each week to create actual reservation

### Application Flow

**Test Lesson Booking** (`rezerwacja-testowa.html` → `script.js`)
1. Client receives personalized link with clientID (PSID)
2. Validates client via `/api/verify-client`
3. Fetches available time slots via `/api/get-schedule`
4. Creates reservation via `/api/create-reservation` with `JestTestowa=True`
5. Generates Teams link, sends Messenger confirmation
6. Schedules follow-up message 62 minutes after lesson start
7. Launches background Facebook profile search

**Permanent Booking** (`rezerwacja-stala.html` → `script-cykliczny.js`)
1. Client can book recurring weekly slots
2. If `isOneTime` checkbox: creates single lesson
3. If not `isOneTime`: creates cyclic reservation
4. Cyclic reservations appear in client dashboard

**Client Dashboard** (`moje-lekcje.html` → client-side JS)
1. Shows cyclic reservations with confirm button
2. Lists upcoming confirmed lessons
3. Shows lesson history
4. Confirms next lesson via `/api/confirm-next-lesson` (creates actual reservation from cyclic)
5. Cancels cyclic slot via `/api/cancel-cyclic-reservation`

**Tutor Panel** (`panel-korepetytora.html` → `script-panel.js`)
1. Authenticated via tutorID in URL
2. View/edit weekly schedule via `/api/update-tutor-schedule`
3. Block specific time slots via `/api/block-single-slot`
4. Add one-time available slots via `/api/add-one-time-slot`
3. View student contact info in schedule

### Key Business Logic

**Payment Deadline System**
- Test lessons: Can be managed up to 1 minute before start
- Regular lessons: Must be paid 12 hours before start
- Background scheduler runs every minute via APScheduler
- `check_and_cancel_unpaid_lessons()` changes status to "Anulowana (brak płatności)"

**Lesson Rescheduling** (`/api/reschedule-reservation`)
- Creates new reservation with same data but new date/time
- Marks original as "Przeniesiona (zakończona)"
- Preserves payment status (Opłacona field)

**Conflict Handling**
- When confirming cyclic lesson, checks for existing reservations
- If conflict exists, creates temp "Przeniesiona" reservation for client to reschedule
- Returns 409 status with managementToken

**Facebook Profile Search** (Selenium automation)
- Runs in background thread after test lesson booking
- Loads cookies from `/var/www/korki/cookies.pkl`
- Searches Facebook by name + profile picture hash matching
- Updates Airtable LINK field with found profile

## Common Development Commands

### Running Locally
```bash
# Install dependencies
pip install -r requirements.txt

# Run development server (includes background scheduler)
python backend.py

# Production server (via Gunicorn, as in Dockerfile)
gunicorn --bind 0.0.0.0:8080 --workers 1 --threads 8 backend:app
```

### Docker
```bash
# Build image
docker build -t strona-korki .

# Run container
docker run -p 8080:8080 strona-korki
```

### Testing
No formal test suite exists. Manual testing workflow:
1. Access HTML pages with test clientID/tutorID in URL params
2. Verify Airtable records created correctly
3. Check Messenger notifications sent

## Important Configuration

### Sensitive Data in Code
**WARNING**: The following are hardcoded in `backend.py` lines 35-54:
- `AIRTABLE_API_KEY`
- `MS_CLIENT_SECRET`
- `MESSENGER_PAGE_TOKEN` (loaded from `/home/nikodnaj3/strona/config.json`)

When modifying, ensure these are moved to environment variables for security.

### Paths and Constants
- `PATH_DO_GOOGLE_CHROME`: `/usr/bin/google-chrome`
- `PATH_DO_RECZNEGO_CHROMEDRIVER`: `/usr/local/bin/chromedriver`
- `COOKIES_FILE`: `/var/www/korki/cookies.pkl`
- `HASH_DIFFERENCE_THRESHOLD`: 10 (for profile picture matching)

### Level Mapping
The `LEVEL_MAPPING` dict maps school types to Airtable tags:
- `szkola_podstawowa` → `["podstawowka"]`
- `liceum_podstawowy`/`technikum_podstawowy` → `["liceum_podstawa"]`
- `liceum_rozszerzony`/`technikum_rozszerzony` → `["liceum_rozszerzenie"]`

## API Endpoints

### Client Operations
- `GET /api/verify-client?clientID={psid}` - Validate client exists
- `GET /api/get-schedule?startDate={date}&schoolType={type}&subject={subj}` - Get available slots
- `POST /api/create-reservation` - Book lesson (test/one-time/cyclic)
- `GET /api/get-client-dashboard?clientID={psid}` - Dashboard data
- `POST /api/confirm-next-lesson` - Confirm next cyclic lesson
- `POST /api/cancel-cyclic-reservation` - Delete cyclic reservation
- `GET /api/get-reservation-details?token={mgmt_token}` - Single lesson details
- `POST /api/cancel-reservation` - Cancel single lesson
- `POST /api/reschedule-reservation` - Move lesson to new time
- `POST /api/check-cyclic-availability` - Check conflicts before confirming cyclic

### Tutor Operations
- `GET /api/get-tutor-schedule?tutorID={id}` - Get tutor's weekly hours
- `POST /api/update-tutor-schedule` - Update weekly availability
- `POST /api/block-single-slot` - Block/unblock specific datetime
- `POST /api/add-one-time-slot` - Add extra available slot

## Code Patterns

### Airtable Queries
```python
# Find by unique ID
client_record = clients_table.first(formula=f"{{ClientID}} = '{client_id.strip()}'")

# Filter by date range
formula = f"AND(IS_AFTER({{Data}}, DATETIME_PARSE('{start}', 'YYYY-MM-DD')), IS_BEFORE({{Data}}, DATETIME_PARSE('{end}', 'YYYY-MM-DD')))"
reservations = reservations_table.all(formula=formula)

# Update record
reservations_table.update(record['id'], {"Status": "Opłacona"})

# Batch update (max 10 at a time)
reservations_table.batch_update(records_to_update)
```

### Date/Time Handling
- All dates stored as `YYYY-MM-DD` strings
- All times stored as `HH:MM` strings
- Use `datetime.strptime()` for parsing
- Warsaw timezone (`pytz.timezone('Europe/Warsaw')`) for scheduler

### Frontend-Backend Communication
- Frontend uses `fetch()` with `API_BASE_URL` constant
- All POST requests send JSON bodies
- clientID passed as URL param for GET, in body for POST
- Status messages shown via `.reservation-status` div

## File Structure Overview

**HTML Pages** (user-facing):
- `index.html` - Landing page
- `rezerwacja-testowa.html` - Test lesson booking
- `rezerwacja-stala.html` - Permanent/one-time booking
- `moje-lekcje.html` - Client dashboard
- `panel-korepetytora.html` - Tutor management panel
- `edit.html` - Lesson rescheduling interface
- `confirmation.html` - Post-booking confirmation
- `login.html` - Tutor authentication (minimal)

**JavaScript Files**:
- `script.js` - Test lesson booking logic
- `script-cykliczny.js` - Permanent booking logic
- `script-panel.js` - Tutor panel logic

**Backend**:
- `backend.py` - Single Flask application file (1599 lines)

**Styling**:
- `style.css` - Global styles

**Infrastructure**:
- `Dockerfile` - Container definition
- `requirements.txt` - Python dependencies (Flask, flask-cors, pyairtable, requests, gunicorn)

## Critical Debugging Notes

### Common Issues

**Cookies Expiration**
If Facebook search fails, check `/var/www/korki/cookies.pkl` exists and is valid. The `initialize_driver_and_login()` function validates this with extensive logging.

**Airtable Rate Limits**
Backend includes DEBUG logging for `urllib3` and `pyairtable` (lines 87-91). Watch for 429 errors in logs.

**Scheduler Not Running**
The `scheduler.start()` only runs when `__name__ == '__main__'` (line 1593). In production with gunicorn, scheduler starts per worker. Consider using single worker or external cron.

**Teams Link Generation Failures**
Check MS_CLIENT_SECRET validity. If `generate_teams_meeting_link()` returns None, reservation creation aborts with 500 error.

## Language and Localization

All user-facing text is in Polish. Key translations:
- Korepetytorzy = Tutors
- Rezerwacje = Reservations  
- Klienci = Clients
- Opłacona = Paid
- Dostępny = Available
- Niedostępny = Unavailable/Blocked
