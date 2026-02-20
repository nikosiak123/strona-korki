# --- Mechanizm wolnej kwoty z bazą danych ---
def get_free_amount(client_id):
    client = clients_table.first(formula=f"{{ClientID}} = '{client_id}'")
    if client:
        amount = int(client['fields'].get('wolna_kwota', 0))
        return amount
    print("DEBUG: Client not found")
    return 0

def set_free_amount(client_id, amount):
    client = clients_table.first(formula=f"{{ClientID}} = '{client_id}'")
    if client:
        clients_table.update(client['id'], {'wolna_kwota': int(amount)})

def add_free_amount(client_id, amount):
    current = get_free_amount(client_id)
    set_free_amount(client_id, current + int(amount))

def subtract_free_amount(client_id, amount):
    current = get_free_amount(client_id)
    new_amount = max(0, current - int(amount))
    set_free_amount(client_id, new_amount)

# Dodaj wolną kwotę przy anulowaniu lekcji (np. >12h przed rozpoczęciem)
def handle_paid_lesson_cancellation(lesson):
    fields = lesson.get('fields', {})
    client_id = fields.get('Klient')
    if fields.get('Oplacona'):
        cena = fields.get('Cena', 0)
        if not cena:
            cena = calculate_lesson_price(fields.get('TypSzkoly'), fields.get('Poziom'), fields.get('Klasa'))
        add_free_amount(client_id, cena)

# Odejmij wolną kwotę przy płatności za nową lekcję
def handle_new_lesson_payment(lesson):
    fields = lesson.get('fields', {})
    client_id = fields.get('Klient')
    cena = calculate_lesson_price(fields.get('TypSzkoly'), fields.get('Poziom'), fields.get('Klasa'))
    wolna_kwota = get_free_amount(client_id)
    if wolna_kwota > 0:
        if wolna_kwota >= cena:
            reservations_table.update(lesson['id'], {"Oplacona": True, "Status": "Opłacona"})
            subtract_free_amount(client_id, cena)
        else:
            subtract_free_amount(client_id, wolna_kwota)
            # Pozostała kwota do zapłaty przez Przelewy24

# Endpoint API: pobierz wolną kwotę klienta
import os
import json
import uuid
import traceback
import urllib.parse
import threading
import hashlib
import sys
from functools import wraps
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../strona')))
from flask import Flask, jsonify, request, abort, session, send_from_directory
from flask_cors import CORS
from datetime import datetime, timedelta
from datetime import time as dt_time
import time
import requests
from apscheduler.schedulers.background import BackgroundScheduler
import pytz
import atexit

scheduler = None
import logging 
import pickle
from io import BytesIO
from bot import create_or_find_client_in_airtable, load_history, save_history
from vertexai.generative_models import Content, Part

# --- Konfiguracja ---
import sys
import os
# Dodaj ścieżkę do katalogu nadrzędnego
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import (
    MS_TENANT_ID, MS_CLIENT_ID, MS_CLIENT_SECRET, MEETING_ORGANIZER_USER_ID,
    ADMIN_PASSWORD,
    P24_MERCHANT_ID, P24_POS_ID, P24_CRC_KEY, P24_API_KEY, P24_SANDBOX, P24_API_URL,
    BREVO_API_KEY, BREVO_API_URL, FROM_EMAIL,
    EXTERNAL_STATS_URL,
    MESSENGER_PAGE_ID,
    FB_PAGE_ACCESS_TOKEN
)
 
# Import lokalnej bazy danych SQLite zamiast Airtable
from database import DatabaseTable, init_database
import database # Import modułu, aby sprawdzić jego ścieżkę


print("--- Uruchamianie backend.py ---")

# Jawne wywołanie migracji bazy danych na starcie
print("--- Inicjalizacja bazy danych ---")
init_database()
print("--- Baza danych zainicjalizowana ---")

# Inicjalizacja tabel bazy danych
tutors_table = DatabaseTable('Korepetytorzy')
reservations_table = DatabaseTable('Rezerwacje')
clients_table = DatabaseTable('Klienci')
cyclic_reservations_table = DatabaseTable('StaleRezerwacje')

MESSENGER_PAGE_TOKEN = FB_PAGE_ACCESS_TOKEN
if MESSENGER_PAGE_TOKEN:
    print(f"--- MESSENGER: Pomyślnie załadowano token dostępu do strony z config.py.")
else:
    print(f"!!! MESSENGER: OSTRZEŻENIE - Nie znaleziono tokena dla strony {MESSENGER_PAGE_ID} w pliku config.py.")

app = Flask(__name__, static_folder='.', static_url_path='')
app.secret_key = os.urandom(24)  # Dla sesji Flask
CORS(app)

def require_admin(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin' not in session:
            abort(401)
        return f(*args, **kwargs)
    return decorated_function

# --- Endpointy dla stron HTML (bez .html w URL) ---

@app.route('/')
def index():
    return send_from_directory('templates', 'index.html')

@app.route('/login')
def login():
    return send_from_directory('templates', 'login.html')

@app.route('/panel-korepetytora')
def panel_korepetytora():
    return send_from_directory('templates', 'panel-korepetytora.html')

@app.route('/moje-lekcje')
def moje_lekcje():
    return send_from_directory('templates', 'moje-lekcje.html')

@app.route('/panel-systemowy')
def panel_systemowy():
    return send_from_directory('templates', 'panel-systemowy.html')

@app.route('/confirmation')
def confirmation():
    return send_from_directory('templates', 'confirmation.html')

@app.route('/edit')
def edit():
    return send_from_directory('templates', 'edit.html')

@app.route('/polityka-prywatnosci')
def polityka_prywatnosci():
    return send_from_directory('templates', 'polityka-prywatnosci.html')

@app.route('/potwierdzenie-platnosci')
def potwierdzenie_platnosci():
    return send_from_directory('templates', 'potwierdzenie-platnosci.html')

@app.route('/regulamin')
def regulamin():
    return send_from_directory('templates', 'regulamin.html')

@app.route('/rezerwacja-stala')
def rezerwacja_stala():
    return send_from_directory('templates', 'rezerwacja-stala.html')

@app.route('/potwierdzenie-lekcji')
def potwierdzenie_lekcji():
    return send_from_directory('templates', 'potwierdzenie-lekcji.html')

# --- Endpointy API ---

# Endpoint API: pobierz wolną kwotę klienta
@app.route('/api/get-free-amount')

def get_free_amount_api():
    client_id = request.args.get('clientID')
    if not client_id:
        abort(400, "Brak parametru clientID.")
    amount = get_free_amount(client_id)
    return jsonify({"freeAmount": amount})


WEEKDAY_MAP = { 0: "Poniedziałek", 1: "Wtorek", 2: "Środa", 3: "Czwartek", 4: "Piątek", 5: "Sobota", 6: "Niedziela" }
LEVEL_MAPPING = {
    "szkola_podstawowa": ["podstawowka"], "liceum_podstawowy": ["liceum_podstawa"],
    "technikum_podstawowy": ["liceum_podstawa"], "liceum_rozszerzony": ["liceum_rozszerzenie"],
    "technikum_rozszerzony": ["liceum_rozszerzenie"]
}
last_fetched_schedule = {}
logging.basicConfig(level=logging.DEBUG, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Obniżenie poziomu logowania dla innych, bardziej "hałaśliwych" bibliotek,
# aby skupić się na zapytaniach HTTP i logach Flask.
logging.getLogger('werkzeug').setLevel(logging.INFO)
logging.getLogger('apscheduler').setLevel(logging.WARNING)
logging.getLogger('tzlocal').setLevel(logging.INFO)

# KLUCZOWE LINIE: Włącz logowanie na poziomie DEBUG dla urllib3 i requests
logging.getLogger('urllib3.connectionpool').setLevel(logging.DEBUG) 
logging.getLogger('requests.packages.urllib3.connectionpool').setLevel(logging.DEBUG)
# --- Funkcje pomocnicze ---
# ================================================
# === FUNKCJE WYSZUKIWARKI PROFILI FACEBOOK ====
# ================================================
def normalize_tutor_field(field_value):
    """Normalizuje pola korepetytora - konwertuje JSON string na listę."""
    if isinstance(field_value, str):
        try:
            return json.loads(field_value)
        except (json.JSONDecodeError, TypeError):
            return [field_value] if field_value else []
    elif isinstance(field_value, list):
        return field_value
    else:
        return [str(field_value)] if field_value else []
def send_followup_message(client_id, lesson_date_str, lesson_time_str, subject):
    """Wysyła wiadomość kontrolną po zakończeniu lekcji testowej."""
    
    if not MESSENGER_PAGE_TOKEN:
        logging.warning("MESSENGER: Nie można wysłać follow-upu - brak tokena.")
        return

    # Pobieramy pełne dane klienta
    client_record = clients_table.first(formula=f"{{ClientID}} = '{client_id.strip()}'")
    psid = client_record['fields'].get('ClientID') if client_record else None

    if not psid:
        logging.error(f"MESSENGER: Nie znaleziono PSID dla ClientID: {client_id}. Anulowano wysyłkę.")
        return

    dashboard_link = f"https://zakręcone-korepetycje.pl/moje-lekcje?clientID={psid}"
    ankieta_link = "https://docs.google.com/forms/d/1sNFt0jWy0hakuVTvZm_YJYThxCVV3lUmZ1Xh81-BZew/edit"
    
    # Użycie potrójnego cudzysłowu zapobiega błędom unterminated string literal
    message_to_send = f"""Witaj! Mam nadzieję, że Twoja lekcja testowa z {subject} była udana! 😊

Zapraszamy do dalszej współpracy. Aby umówić się na stałe zajęcia, wystarczy w panelu klienta nacisnąć przycisk 'Zarezerwuj stałe zajęcia'.
Dostęp do panelu: {dashboard_link}

Stałe zajęcia gwarantują miejsce o wybranej godzinie w każdym tygodniu. Jeśli wolisz lekcję jednorazową, zaznacz odpowiednie pole podczas rezerwacji.

Bardzo pomogłoby nam, gdybyś wypełnił krótką ankietę (zajmuje mniej niż 30 sekund): 
{ankieta_link}"""
    
    send_messenger_confirmation(psid, message_to_send, MESSENGER_PAGE_TOKEN)
    logging.info(f"MESSENGER: Wysłano wiadomość follow-up do {psid}.")

def send_confirmation_reminder(management_token):
    """Wysyła przypomnienie o konieczności potwierdzenia lekcji testowej."""
    
    if not MESSENGER_PAGE_TOKEN:
        logging.warning("MESSENGER: Nie można wysłać przypomnienia o potwierdzeniu - brak tokena.")
        return

    # Znajdź rezerwację po tokenie
    reservation = reservations_table.first(formula=f"{{ManagementToken}} = '{management_token}'")
    if not reservation:
        logging.error(f"Nie znaleziono rezerwacji dla tokenu: {management_token}")
        return
    
    fields = reservation.get('fields', {})
    client_id = fields.get('Klient')
    lesson_date = fields.get('Data')
    lesson_time = fields.get('Godzina')
    subject = fields.get('Przedmiot', 'nieznany przedmiot')
    
    # Sprawdź czy lekcja jest już potwierdzona
    if fields.get('confirmed', False):
        logging.info(f"Lekcja {management_token} jest już potwierdzona, pomijam przypomnienie.")
        return

    # Pobieramy dane klienta
    client_record = clients_table.first(formula=f"{{ClientID}} = '{client_id.strip()}'")
    psid = client_record['fields'].get('ClientID') if client_record else None

    if not psid:
        logging.error(f"MESSENGER: Nie znaleziono PSID dla ClientID: {client_id}. Anulowano wysyłkę.")
        return

    confirmation_link = f"https://zakręcone-korepetycje.pl/potwierdzenie-lekcji?token={management_token}"
    dashboard_link = f"https://zakręcone-korepetycje.pl/moje-lekcje?clientID={psid}"
    
    message_to_send = f"""🔔 PRZYPOMNIENIE: Potwierdź swoją lekcję testową!

Masz zaplanowaną lekcję testową z {subject} na {lesson_date} o godzinie {lesson_time}.

Aby lekcja się odbyła, musisz ją potwierdzić w ciągu najbliższych 18 godzin.

Potwierdź teraz: {confirmation_link}

Możesz też potwierdzić w panelu klienta: {dashboard_link}

Jeśli nie potwierdzisz lekcji na 6 godzin przed jej rozpoczęciem, zostanie ona automatycznie odwołana."""
    
    send_messenger_confirmation(psid, message_to_send, MESSENGER_PAGE_TOKEN)
    logging.info(f"MESSENGER: Wysłano przypomnienie o potwierdzeniu do {psid} dla lekcji {management_token}.")

def check_unconfirmed_lessons():
    """Sprawdza niepotwierdzone lekcje testowe i odwołuje te, które minął deadline."""
    now = datetime.now()
    logging.info("Sprawdzanie niepotwierdzonych lekcji testowych...")
    
    # Znajdź wszystkie niepotwierdzone lekcje testowe
    unconfirmed_lessons = reservations_table.all(formula="AND({JestTestowa} = 1, {confirmed} = 0, NOT({Status} = 'Odwołana - brak potwierdzenia'), NOT({Status} = 'Przeniesiona (zakończona)'), NOT({Status} = 'Anulowana (brak płatności)'))")
    
    for lesson in unconfirmed_lessons:
        fields = lesson.get('fields', {})
        lesson_datetime_str = f"{fields.get('Data')} {fields.get('Godzina')}"
        
        try:
            lesson_start = datetime.strptime(lesson_datetime_str, "%Y-%m-%d %H:%M")
            time_until_lesson = lesson_start - now
            
            # Jeśli zostało mniej niż 6 godzin LUB lekcja już minęła
            if time_until_lesson <= timedelta(hours=6):
                logging.info(f"Odwołuję niepotwierdzoną lekcję testową (wygasła): {fields.get('ManagementToken')}")
                
                # Odwołaj lekcję
                reservations_table.update(lesson['id'], {"Status": "Odwołana - brak potwierdzenia"})
                
                # Powiadom korepetytora
                notify_tutor_about_lesson_change(
                    fields.get('Korepetytor'), 
                    "cancelled", 
                    f"Przedmiot: {fields.get('Przedmiot')}, Data: {fields.get('Data')}, Godzina: {fields.get('Godzina')}, Klient: {fields.get('Klient')} - ODWOŁANA (brak potwierdzenia)"
                )
                
                # Wyślij wiadomość do klienta
                if MESSENGER_PAGE_TOKEN:
                    client_record = clients_table.first(formula=f"{{ClientID}} = '{fields.get('Klient').strip()}'")
                    if client_record:
                        psid = client_record['fields'].get('ClientID')
                        message = f"""❌ Twoja lekcja testowa z {fields.get('Przedmiot')} na {fields.get('Data')} o {fields.get('Godzina')} została odwołana.

Przyczyna: Brak potwierdzenia lekcji w wymaganym terminie (24h przed lekcją).

Jeśli nadal jesteś zainteresowany korepetycjami, możesz zarezerwować nową lekcję w panelu klienta."""
                        send_messenger_confirmation(psid, message, MESSENGER_PAGE_TOKEN)
                        
        except ValueError as e:
            logging.error(f"Błąd parsowania daty dla lekcji {fields.get('ManagementToken')}: {e}")

@app.route('/api/cancel-cyclic-reservation', methods=['POST'])
def cancel_cyclic_reservation():
    try:
        data = request.json
        cyclic_reservation_id = data.get('cyclicReservationId')

        if not cyclic_reservation_id:
            abort(400, "Brak identyfikatora stałej rezerwacji.")

        # Znajdź rekord stałej rezerwacji
        record_to_cancel = cyclic_reservations_table.get(cyclic_reservation_id)
        
        if not record_to_cancel:
            abort(404, "Nie znaleziono stałej rezerwacji o podanym ID.")

        # --- ZMIANA JEST TUTAJ ---
        # Usuń rekord stałej rezerwacji zamiast go dezaktywować
        cyclic_reservations_table.delete(record_to_cancel['id'])
        
        print(f"USUNIĘTO STAŁY TERMIN: Rekord o ID {record_to_cancel['id']} został trwale usunięty.")

        return jsonify({"message": "Stały termin został pomyślnie odwołany."})

    except Exception as e:
        traceback.print_exc()
        abort(500, "Wystąpił błąd serwera podczas anulowania stałego terminu.")



def send_messenger_confirmation(psid, message_text, page_access_token):
    """Wysyła wiadomość potwierdzającą na Messengerze."""
    if not all([psid, message_text, page_access_token]):
        logging.warning("MESSENGER: Błąd wysyłania - brak PSID, treści lub tokenu.")
        return
    
    # FIX: Walidacja PSID - pomiń krótkie i testowe identyfikatory
    psid_str = str(psid).strip()
    if len(psid_str) < 10 or psid_str in ['123456789', 'test', 'DOSTEPNY', 'BLOKADA']:
        logging.warning(f"MESSENGER: Pominięto wysyłkę do testowego/nieprawidłowego PSID: {psid_str[:5]}...")
        return

    params = {"access_token": page_access_token}
    payload = {
        "recipient": {"id": psid_str},
        "message": {"text": message_text},
        "messaging_type": "MESSAGE_TAG",
        "tag": "POST_PURCHASE_UPDATE"
    }
    
    try:
        logging.info(f"MESSENGER: Próba wysłania wiadomości do PSID {psid_str[:5]}...")
        r = requests.post("https://graph.facebook.com/v19.0/me/messages", 
                         params=params, 
                         json=payload, 
                         timeout=30)
        r.raise_for_status()
        logging.info(f"MESSENGER: Wysłano wiadomość do {psid_str[:5]}...")
    except requests.exceptions.RequestException as e:
        logging.error(f"MESSENGER: Błąd wysyłki do {psid_str[:5]}...: {e}")
        if e.response:
            logging.error(f"MESSENGER: Odpowiedź: {e.response.text}")

def check_and_cancel_unpaid_lessons():
    """To zadanie jest uruchamiane w tle, aby ZMIENIĆ STATUS nieopłaconych lekcji."""

    warsaw_tz = pytz.timezone('Europe/Warsaw')
    current_local_time = datetime.now(warsaw_tz)

    try:
        # --- Sprawdzamy wszystkie nieopłacone lekcje (bez warunku czasowego w Airtable) ---
        formula = f"AND(NOT({{Oplacona}}), OR({{Status}} = 'Oczekuje na płatność', {{Status}} = 'Termin płatności minął'), NOT({{Status}} = 'Anulowana (brak płatności)'))"

        potential_lessons = reservations_table.all(formula=formula)
        
        if not potential_lessons:
            return

        lessons_to_cancel = []
        
        for lesson in potential_lessons:
            fields = lesson.get('fields', {})
            lesson_date_str = fields.get('Data')
            lesson_time_str = fields.get('Godzina')
            is_test_lesson = fields.get('JestTestowa', False)
            lesson_status = fields.get('Status', '')

            if not lesson_date_str or not lesson_time_str:
                continue

            lesson_datetime_naive = datetime.strptime(f"{lesson_date_str} {lesson_time_str}", "%Y-%m-%d %H:%M")
            lesson_datetime_aware = warsaw_tz.localize(lesson_datetime_naive)
            
            # Jeśli to lekcja testowa, nie anuluj jej automatycznie
            if is_test_lesson:
                continue
            
            # Jeśli status to "Termin płatności minął", anuluj natychmiast
            if lesson_status == 'Termin płatności minął':
                lessons_to_cancel.append(lesson)
                logging.info(f"Lekcja ID {lesson['id']} z {lesson_date_str} o {lesson_time_str} ma status 'Termin płatności minął' - anulowanie natychmiastowe.")
                continue
            
            # Dla "Oczekuje na płatność" sprawdź deadline
            payment_deadline = lesson_datetime_aware - timedelta(hours=12)  # 12h dla normalnych
            
            if current_local_time > payment_deadline:
                lessons_to_cancel.append(lesson)
                logging.info(f"Lekcja ID {lesson['id']} z {lesson_date_str} o {lesson_time_str} zakwalifikowana do anulowania. Termin płatności: {payment_deadline.strftime('%Y-%m-%d %H:%M:%S')}")

        if not lessons_to_cancel:
            return

        logging.info(f"AUTOMATYCZNE ANULOWANIE: Znaleziono {len(lessons_to_cancel)} nieopłaconych lekcji do zmiany statusu.")

        records_to_update = []
        for lesson in lessons_to_cancel:
            records_to_update.append({
                "id": lesson['id'],
                "fields": {"Status": "Anulowana (brak płatności)"}
            })

        for i in range(0, len(records_to_update), 10):
            chunk = records_to_update[i:i+10]
            reservations_table.batch_update(chunk)
            logging.info(f"Pomyślnie zaktualizowano status dla fragmentu rezerwacji: {[rec['id'] for rec in chunk]}")

        logging.info("AUTOMATYCZNE ANULOWANIE: Zakończono proces zmiany statusu.")

    except Exception as e:
        logging.error(f"!!! BŁĄD w zadaniu anulowania lekcji: {e}", exc_info=True)




def parse_time_range(time_range_str):
    try:
        if not time_range_str or '-' not in time_range_str: return None, None
        start_str, end_str = time_range_str.split('-')
        start_time = datetime.strptime(start_str.strip(), '%H:%M').time()
        end_time = datetime.strptime(end_str.strip(), '%H:%M').time()
        return start_time, end_time
    except ValueError: return None, None

def get_available_times_for_day(schedule_value, master_times):
    """Get available times for a day from list of times."""
    if isinstance(schedule_value, list):
        # Format: list of selected time slots
        return [t for t in schedule_value if t in master_times]
    else:
        return []

def normalize_tutor_field(raw_value):
    """
    Normalize a tutor field (Przedmioty or PoziomNauczania) that can be a list or string.
    Returns a list of lowercase, trimmed strings.
    
    Args:
        raw_value: Can be a list, JSON string, CSV string, or None.
    
    Examples:
        ['Math', 'Physics'] -> ['math', 'physics']
        '["Math", "Physics"]' -> ['math', 'physics']
        'Math, Physics' -> ['math', 'physics']
        None -> []
    """
    if isinstance(raw_value, list):
        return [s.strip().lower() for s in raw_value if isinstance(s, str)]
    elif isinstance(raw_value, str):
        try:
            parsed = json.loads(raw_value)
            return [s.strip().lower() for s in parsed if isinstance(s, str)]
        except (json.JSONDecodeError, TypeError):
            return [s.strip().lower() for s in raw_value.split(',') if s.strip()]
    else:
        return []

def generate_teams_meeting_link(meeting_subject):
    """Generuje link do spotkania Microsoft Teams."""
    try:
        # Pobierz token dostępu
        token_url = f"https://login.microsoftonline.com/{MS_TENANT_ID}/oauth2/v2.0/token"
        token_data = {
            'grant_type': 'client_credentials',
            'client_id': MS_CLIENT_ID,
            'client_secret': MS_CLIENT_SECRET,
            'scope': 'https://graph.microsoft.com/.default'
        }
        
        token_r = requests.post(token_url, data=token_data, timeout=10)
        if token_r.status_code != 200:
            logging.error(f"MS Teams token error {token_r.status_code}: {token_r.text}")
            return None
        
        access_token = token_r.json().get('access_token')
        if not access_token:
            logging.error("MS Teams: Brak access_token w odpowiedzi")
            return None
        
        # Utwórz spotkanie
        meetings_url = f"https://graph.microsoft.com/v1.0/users/{MEETING_ORGANIZER_USER_ID}/onlineMeetings"
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        
        start_time = datetime.utcnow() + timedelta(minutes=5)
        end_time = start_time + timedelta(hours=1)
        
        # FIX: Poprawiony format daty z .000Z
        meeting_payload = {
            "startDateTime": start_time.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
            "endDateTime": end_time.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
            "subject": meeting_subject
        }
        
        meeting_r = requests.post(meetings_url, headers=headers, json=meeting_payload, timeout=10)
        
        if meeting_r.status_code == 201:
            # FIX: Zmieniono z 'joinUrl' na 'joinWebUrl'
            join_url = meeting_r.json().get('joinWebUrl')
            if join_url:
                logging.info(f"MS Teams: Utworzono spotkanie - {meeting_subject}")
                return join_url
            else:
                logging.error("MS Teams: Brak joinWebUrl w odpowiedzi")
                return None
        else:
            logging.error(f"MS Teams meeting error {meeting_r.status_code}: {meeting_r.text}")
            return None
    
    except Exception as e:
        logging.error(f"MS Teams exception: {e}", exc_info=True)
        return None

def find_reservation_by_token(token):
    if not token: return None
    return reservations_table.first(formula=f"{{ManagementToken}} = '{token}'")

# === Funkcje pomocnicze dla limitu godzin tygodniowo ===

def get_week_start(date):
    """Zwraca poniedziałek dla podanej daty."""
    return date - timedelta(days=date.weekday())

def get_tutor_hours_for_week(tutor_name, week_start_date):
    """
    Liczy sumę godzin korepetytora w tygodniu od week_start_date (poniedziałek).
    
    Args:
        tutor_name: Imię i nazwisko korepetytora
        week_start_date: Data poniedziałku (datetime.date)
    
    Returns:
        int: Liczba godzin (każda lekcja = 1 godzina)
    """
    week_end_date = week_start_date + timedelta(days=7)
    
    # Formaty dat dla SQLite (YYYY-MM-DD)
    start_str = week_start_date.strftime('%Y-%m-%d')
    end_str = week_end_date.strftime('%Y-%m-%d')
    
    # Formuła zlicza lekcje z statusami "opłaconych" (nie liczy przeniesionych, anulowanych, etc.)
    formula = f"""AND(
        {{Korepetytor}} = '{tutor_name}',
        IS_AFTER({{Data}}, DATETIME_PARSE('{(week_start_date - timedelta(days=1)).strftime('%Y-%m-%d')}', 'YYYY-MM-DD')),
        IS_BEFORE({{Data}}, DATETIME_PARSE('{end_str}', 'YYYY-MM-DD')),
        OR({{Status}} = 'Opłacona', {{Status}} = 'Oczekuje na płatność')
    )"""
    
    lessons = reservations_table.all(formula=formula)
    return len(lessons)  # Każda lekcja = 1h

def check_if_client_has_cyclic_with_tutor(client_id, tutor_name):
    """Sprawdza, czy klient ma aktywne stałe zajęcia z korepetytorem."""
    formula = f"AND({{Klient_ID}} = '{client_id}', {{Korepetytor}} = '{tutor_name}', {{Aktywna}} = 1)"
    return cyclic_reservations_table.first(formula=formula) is not None

def check_if_client_has_any_lessons_with_tutor(client_id, tutor_name):
    """Sprawdza, czy klient miał jakiekolwiek zajęcia z korepetytorem (oprócz anulowanych)."""
    formula = f"AND({{Klient}} = '{client_id}', {{Korepetytor}} = '{tutor_name}', NOT({{Status}} = 'Anulowana (brak płatności)'), NOT({{Status}} = 'Przeniesiona (zakończona)'))"
    lessons = reservations_table.all(formula=formula)
    return len(lessons) > 0

def check_if_client_has_booked_test_lesson(client_id):
    """Sprawdza, czy klient ma aktywną lub wykorzystaną lekcję testową.
    Anulowane lekcje testowe (przez klienta, system lub brak płatności/potwierdzenia) nie blokują ponownej rezerwacji.
    """
    # Statusy, które NIE powinny blokować ponownej rezerwacji (traktowane jako niewykorzystane)
    # Zgodnie z życzeniem klienta: Odwołana przez klienta umożliwia ponowną rezerwację.
    formula = f"""AND(
        {{Klient}} = '{client_id}',
        {{JestTestowa}} = 1,
        NOT(OR(
            {{Status}} = 'Odwołana przez klienta',
            {{Status}} = 'Anulowana (brak płatności)',
            {{Status}} = 'Odwołana - brak potwierdzenia'
        ))
    )"""
    lesson = reservations_table.first(formula=formula)
    return lesson is not None

# === Koniec funkcji pomocniczych ===

# === Funkcje płatności Przelewy24 ===

def calculate_lesson_price(school_type, school_level=None, school_class=None):
    """
    Oblicza cenę lekcji na podstawie typu szkoły, poziomu i klasy.
    Zwraca cenę w groszach.
    """
    if school_type == 'szkola_podstawowa':
        return 6500
    if school_class and ('4' in str(school_class).lower() or '5' in str(school_class).lower()):
        return 8000
    if school_level == 'rozszerzony':
        return 7500
    return 7000

def generate_p24_sign(session_id, merchant_id, amount, currency, crc):
    """
    Generuje podpis SHA-384 dla Przelewy24 (REST API v1).
    Ważne: podpis powstaje z JSON-a bez spacji.
    """
    sign_payload = {
        "sessionId": session_id,
        "merchantId": int(merchant_id),
        "amount": int(amount),
        "currency": currency,
        "crc": crc
    }
    # Generowanie stringa JSON bez spacji (separators)
    sign_json = json.dumps(sign_payload, separators=(',', ':'))
    return hashlib.sha384(sign_json.encode('utf-8')).hexdigest()

# === Koniec funkcji płatności ===

# W pliku backend.py

def is_cancellation_allowed(record):
    fields = record.get('fields', {})
    lesson_date_str = fields.get('Data')
    lesson_time_str = fields.get('Godzina')

    # Pobieramy status lekcji testowej. Domyślnie False, jeśli pole nie istnieje.
    is_test_lesson = fields.get('JestTestowa', False)

    if not lesson_date_str or not lesson_time_str:
        return False

    try:
        # Pamiętaj, że datetime.now() domyślnie jest naiwne (bez strefy czasowej),
        # ale ponieważ Airtable Data/Godzina również jest naiwne, porównanie powinno działać.
        lesson_datetime = datetime.strptime(f"{lesson_date_str} {lesson_time_str}", "%Y-%m-%d %H:%M")
    except ValueError:
        # Błąd formatu daty/czasu w rekordzie
        return False

    time_remaining = lesson_datetime - datetime.now()

    # Warunek dla lekcji testowych: Pozwalamy na zarządzanie do 6 godzin przed rozpoczęciem.
    if is_test_lesson:
        return time_remaining > timedelta(hours=6)

    # Warunek dla wszystkich innych lekcji: Obowiązuje standardowe 12 godzin.
    return time_remaining > timedelta(hours=12)

def is_lesson_ended(record):
    """Sprawdza, czy lekcja już się zakończyła."""
    fields = record.get('fields', {})
    lesson_date_str = fields.get('Data')
    lesson_time_str = fields.get('Godzina')

    if not lesson_date_str or not lesson_time_str:
        return False

    try:
        lesson_datetime = datetime.strptime(f"{lesson_date_str} {lesson_time_str}", "%Y-%m-%d %H:%M")
        # Lekcja kończy się 1 godzinę po rozpoczęciu
        lesson_end = lesson_datetime + timedelta(hours=1)
        return lesson_end < datetime.now()
    except ValueError:
        return False

def send_email_via_brevo(to_email, subject, html_content):
    """Wysyła email przez Brevo API z rozszerzonym logowaniem i unikalnym tematem."""
    headers = {
        "accept": "application/json",
        "api-key": BREVO_API_KEY,
        "content-type": "application/json"
    }
    
    # Dodajemy timestamp do tematu (zapobiega grupowaniu w Gmailu)
    from datetime import datetime
    unique_subject = f"{subject} [{datetime.now().strftime('%H:%M:%S')}]"

    payload = {
        "sender": {
            "name": "Zakręcone Korepetycje",
            "email": FROM_EMAIL
        },
        "to": [{"email": to_email}],
        "subject": unique_subject,
        "htmlContent": html_content
    }
    try:
        logging.info(f"EMAIL_DEBUG: Próba wysyłki do korepetytora {to_email}...")
        response = requests.post(BREVO_API_URL, json=payload, headers=headers, timeout=15)
        
        if response.status_code == 201:
            logging.info(f"✅ Email do korepetytora zaakceptowany. ID: {response.json().get('messageId')}")
        else:
            logging.error(f"❌ Brevo odrzuciło maila do korepetytora: {response.status_code} - {response.text}")
    except Exception as e:
        logging.error(f"❌ Wyjątek krytyczny w send_email_via_brevo (backend): {e}")

def notify_tutor_about_lesson_change(tutor_name, change_type, lesson_details):
    """Wysyła powiadomienie do korepetytora o zmianie w lekcji."""
    tutor = tutors_table.first(formula=f"{{ImieNazwisko}} = '{tutor_name}'")
    if not tutor or not tutor['fields'].get('Email'):
        logging.warning(f"Brak emaila dla korepetytora {tutor_name}")
        return
    
    email = tutor['fields']['Email']
    tutor_id = tutor['fields'].get('TutorID')
    panel_link = f"https://zakręcone-korepetycje.pl/panel-korepetytora?tutorID={tutor_id}"
    
    if change_type == "new":
        subject = "Nowa lekcja została zarezerwowana"
        html = f"<p>Witaj {tutor_name},</p><p>Masz nową lekcję:</p><p>{lesson_details}</p><p>Dostęp do panelu: <a href='{panel_link}'>Panel korepetytora</a></p><p>Pozdrawiam,<br>Zakręcone Korepetycje</p>"
    elif change_type == "cancelled":
        subject = "Lekcja została anulowana"
        html = f"<p>Witaj {tutor_name},</p><p>Lekcja została anulowana:</p><p>{lesson_details}</p><p>Dostęp do panelu: <a href='{panel_link}'>Panel korepetytora</a></p><p>Pozdrawiam,<br>Zakręcone Korepetycje</p>"
    elif change_type == "rescheduled":
        subject = "Lekcja została przesunięta"
        html = f"<p>Witaj {tutor_name},</p><p>Lekcja została przesunięta:</p><p>{lesson_details}</p><p>Dostęp do panelu: <a href='{panel_link}'>Panel korepetytora</a></p><p>Pozdrawiam,<br>Zakręcone Korepetycje</p>"
    elif change_type == "confirmed":
        subject = "Lekcja została potwierdzona"
        html = f"<p>Witaj {tutor_name},</p><p>Lekcja została potwierdzona:</p><p>{lesson_details}</p><p>Dostęp do panelu: <a href='{panel_link}'>Panel korepetytora</a></p><p>Pozdrawiam,<br>Zakręcone Korepetycje</p>"
    else:
        return
    
    send_email_via_brevo(email, subject, html)

# --- Endpointy API ---
@app.route('/api/check-cyclic-availability', methods=['POST'])
def check_cyclic_availability():
    """Sprawdza dostępność i w razie konfliktu tworzy tymczasowy rekord do zarządzania."""
    try:
        cyclic_reservation_id = request.json.get('cyclicReservationId')
        if not cyclic_reservation_id: abort(400, "Brak ID.")

        cyclic_record = cyclic_reservations_table.get(cyclic_reservation_id)
        if not cyclic_record: abort(404, "Nie znaleziono rezerwacji.")
        
        fields = cyclic_record.get('fields', {})
        tutor = fields.get('Korepetytor')
        day_name = fields.get('DzienTygodnia')
        lesson_time = fields.get('Godzina')
        
        day_num = list(WEEKDAY_MAP.keys())[list(WEEKDAY_MAP.values()).index(day_name)]
        today = datetime.now().date()
        days_ahead = day_num - today.weekday()
        if days_ahead <= 0: days_ahead += 7
        next_lesson_date = today + timedelta(days=days_ahead)
        next_lesson_date_str = next_lesson_date.strftime('%Y-%m-%d')
        
        formula_check = f"AND({{Korepetytor}} = '{tutor}', DATETIME_FORMAT({{Data}}, 'YYYY-MM-DD') = '{next_lesson_date_str}', {{Godzina}} = '{lesson_time}')"
        existing_reservation = reservations_table.first(formula=formula_check)

        if existing_reservation:
            # --- NOWA LOGIKA OBSŁUGI KONFLIKTU ---
            client_uuid = fields.get('Klient_ID', '').strip()
            
            # Tworzymy tymczasowy rekord, aby klient mógł nim zarządzać
            temp_token = str(uuid.uuid4())
            temp_reservation = {
                "Klient": client_uuid,
                "Korepetytor": tutor,
                "Data": next_lesson_date_str,
                "Godzina": lesson_time,
                "Przedmiot": fields.get('Przedmiot'),
                "ManagementToken": temp_token,
                "Typ": "Cykliczna",
                "Status": "Przeniesiona" # Od razu nadajemy status "Przeniesiona"
            }
            reservations_table.create(temp_reservation)

            return jsonify({
                "isAvailable": False,
                "message": f"Niestety, termin {next_lesson_date_str} o {lesson_time} został w międzyczasie jednorazowo zablokowany przez korepetystora.",
                "managementToken": temp_token # Zwracamy token do zarządzania
            })
        
        return jsonify({"isAvailable": True})

    except Exception as e:
        traceback.print_exc()
        abort(500, "Błąd serwera podczas sprawdzania dostępności.")

# ⚠️ UWAGA: Ten endpoint jest tylko do testów i panelu admina.
# Prawdziwe płatności powinny przechodzić przez:
# /api/initiate-payment → Przelewy24 → /api/payment-notification (webhook)
@app.route('/api/mark-lesson-as-paid', methods=['POST'])
def mark_lesson_as_paid():
    """Endpoint do symulacji płatności - TYLKO DLA ADMINISTRATORÓW."""
    require_admin()
    
    try:
        token = request.json.get('managementToken')
        if not token:
            abort(400, "Brak tokena zarządzającego w zapytaniu.")

        # Znajdź rezerwację na podstawie unikalnego tokena
        record_to_update = reservations_table.first(formula=f"{{ManagementToken}} = '{token}'")
        
        if not record_to_update:
            abort(404, "Nie znaleziono rezerwacji o podanym tokenie.")

        # Przygotuj dane do aktualizacji w Airtable
        update_data = {
            "Oplacona": True,
            "Status": "Opłacona"
        }
        reservations_table.update(record_to_update['id'], update_data)
        
        # Logika wysyłania powiadomienia na Messengerze
        if MESSENGER_PAGE_TOKEN:
            fields = record_to_update.get('fields', {})
            psid = fields.get('Klient')
            if psid:
                message_to_send = (
                    f"Dziękujemy za płatność! Twoja lekcja z przedmiotu '{fields.get('Przedmiot')}' w dniu {fields.get('Data')} o {fields.get('Godzina')} "
                    f"jest już w pełni potwierdzona i opłacona. Do zobaczenia!"
                )
                send_messenger_confirmation(psid, message_to_send, MESSENGER_PAGE_TOKEN)
            
        print(f"Oznaczono lekcję (ID: {record_to_update['id']}) jako OPŁACONĄ.")
        
        return jsonify({"message": "Lekcja została oznaczona jako opłacona."})

    except Exception as e:
        traceback.print_exc()
        abort(500, "Wystąpił błąd podczas oznaczania lekcji jako opłaconej.")

@app.route('/api/initiate-payment', methods=['POST'])
def initiate_payment():
    """Inicjalizuje płatność w systemie Przelewy24."""
    try:
        data = request.json
        token = data.get('managementToken')
        
        if not token:
            abort(400, "Brak tokena zarządzającego.")
        
        # Znajdź lekcję
        lesson = reservations_table.first(formula=f"{{ManagementToken}} = '{token}'")
        if not lesson:
            abort(404, "Lekcja nie znaleziona")
        
        fields = lesson['fields']
        
        # Pobierz email klienta (lub użyj domyślnego jeśli brak)
        client_id = fields.get('Klient')
        client_email = "klient@example.com"  # Domyślny
        
        if client_id:
            client_record = clients_table.first(formula=f"{{ClientID}} = '{client_id}'")
            if client_record:
                # Spróbuj pobrać email z różnych pól
                client_email = (
                    client_record['fields'].get('Email') or 
                    client_record['fields'].get('email') or 
                    "klient@example.com"
                )
        
        # Oblicz cenę
        amount = calculate_lesson_price(
            fields.get('TypSzkoly'), 
            fields.get('Poziom'), 
            fields.get('Klasa')
        )
        
        # Sprawdź wolną kwotę klienta
        wolna_kwota = get_free_amount(client_id) if client_id else 0
        if wolna_kwota >= amount:
            # Wolna kwota pokrywa pełną cenę - oznacz lekcję jako opłaconą bez P24
            reservations_table.update(lesson['id'], {"Oplacona": True, "Status": "Opłacona"})
            subtract_free_amount(client_id, amount)
            return jsonify({"message": "Lekcja opłacona z wolnej kwoty."})
        elif wolna_kwota > 0:
            # Częściowe pokrycie - zmniejsz kwotę do zapłaty o wolną kwotę
            amount -= wolna_kwota
            # Zapisz wykorzystaną wolną kwotę w rekordzie lekcji
            reservations_table.update(lesson['id'], {"WolnaKwotaUzyta": wolna_kwota})
        
        # --- NOWY, POPRAWNY KOD ---
        # Używamy tokena lekcji jako ID sesji, aby móc ją potem znaleźć w bazie!
        session_id = token
        sign = generate_p24_sign(session_id, P24_MERCHANT_ID, amount, "PLN", P24_CRC_KEY)

        # To rozwiązanie jest uniwersalne - bierze adres z paska przeglądarki (ten działający z 6vc)
        # Wymuszamy adres techniczny (Punycode), który jest akceptowany przez P24
        # Używamy końcówki 6vc, którą podałeś jako działającą
        current_host = "https://xn--zakrcone-korepetycje-6vc.pl/"

        payload = {
            "merchantId": P24_MERCHANT_ID,
            "posId": P24_POS_ID,
            "sessionId": session_id,
            "amount": amount,
            "currency": "PLN",
            "description": f"Lekcja {fields.get('Przedmiot')}",
            "email": client_email,
            "country": "PL",
            "language": "pl",
            # Tutaj używamy dynamicznego adresu:
            "urlReturn": f"{current_host}potwierdzenie-platnosci?token={token}",
            "urlStatus": f"{current_host}api/payment-notification",
            "sign": sign
        }

        # Przelewy24 może odrzucać URL-e z escapowanymi znakami Unicode
        payload_json = json.dumps(payload, ensure_ascii=False)

        logging.info(f"P24 payload: {payload}")

        response = requests.post(
            f"{P24_API_URL}/api/v1/transaction/register",
            data=payload_json,
            headers={'Content-Type': 'application/json'},
            auth=(str(P24_POS_ID), P24_API_KEY)
        )

        logging.info(f"P24 request sent, status: {response.status_code}")

        if response.status_code == 200:
            result = response.json()
            logging.info(f"P24 Response: {result}")
            
            if 'data' in result and 'token' in result['data']:
                p24_token = result['data']['token']
                payment_url = f"{P24_API_URL}/trnRequest/{p24_token}"
                logging.info(f"Generated payment URL: {payment_url}")
                return jsonify({"paymentUrl": payment_url})
            else:
                logging.error(f"P24 Response missing data.token: {result}")
                return jsonify({"error": "Błąd Przelewy24 - brak tokena", "details": result}), 500
        else:
            logging.error(f"P24 Error: {response.status_code} - {response.text}")
            return jsonify({"error": "Błąd Przelewy24", "details": response.json() if response.content else "No response"}), 500
    
    except Exception as e:
        logging.error(f"Payment initiation error: {e}", exc_info=True)
        abort(500, "Błąd inicjalizacji płatności")

@app.route('/api/payment-notification', methods=['POST'])
def payment_notification():
    """
    Webhook obsługujący powiadomienie o płatności z Przelewy24 (API v1 REST).
    """
    try:
        # P24 w API v1 wysyła dane jako JSON
        data = request.get_json()
        
        # Jeśli dane nie są JSONem, spróbuj odebrać jako form (zależnie od konfiguracji serwera)
        if not data:
            data = request.form.to_dict()

        if not data or 'sign' not in data:
            logging.error("P24: Otrzymano pusty lub błędny webhook.")
            return "Invalid data", 400

        session_id = data.get('sessionId')
        logging.info(f"Otrzymano powiadomienie płatności P24 dla sesji: {session_id}")

        # --- KROK 1: Weryfikacja sygnatury otrzymanego powiadomienia ---
        # Pola wymagane do obliczenia sign w powiadomieniu (zgodnie z dokumentacją v1)
        sign_check_payload = {
            "merchantId": int(data.get('merchantId')),
            "posId": int(data.get('posId')),
            "sessionId": data.get('sessionId'),
            "amount": int(data.get('amount')),
            "originAmount": int(data.get('originAmount', data.get('amount'))),
            "currency": data.get('currency'),
            "orderId": int(data.get('orderId')),
            "methodId": int(data.get('methodId')),
            "statement": data.get('statement'),
            "crc": P24_CRC_KEY
        }
        
        # Tworzymy JSON bez spacji (separators)
        sign_check_json = json.dumps(sign_check_payload, separators=(',', ':'))
        calculated_sign = hashlib.sha384(sign_check_json.encode('utf-8')).hexdigest()

        if calculated_sign != data.get('sign'):
            logging.error(f"P24: BŁĄD SYGNATURY! Otrzymano: {data.get('sign')}, Obliczono: {calculated_sign}")
            return "Invalid signature", 403

        # --- KROK 2: Weryfikacja transakcji (Transaction Verify) ---
        # W API v1 musimy wysłać PUT na /api/v1/transaction/verify, aby zatwierdzić płatność
        
        # Obliczamy podpis dla żądania weryfikacji
        verify_sign_data = {
            "sessionId": data.get('sessionId'),
            "orderId": int(data.get('orderId')),
            "amount": int(data.get('amount')),
            "currency": data.get('currency'),
            "crc": P24_CRC_KEY
        }
        verify_sign_json = json.dumps(verify_sign_data, separators=(',', ':'))
        verify_sign = hashlib.sha384(verify_sign_json.encode('utf-8')).hexdigest()

        verify_payload = {
            "merchantId": int(data.get('merchantId')),
            "posId": int(data.get('posId')),
            "sessionId": data.get('sessionId'),
            "amount": int(data.get('amount')),
            "currency": data.get('currency'),
            "orderId": int(data.get('orderId')),
            "sign": verify_sign
        }

        # Wysyłamy żądanie weryfikacji (PUT)
        verify_response = requests.put(
            f"{P24_API_URL}/api/v1/transaction/verify",
            json=verify_payload,
            auth=(str(P24_POS_ID), P24_API_KEY),
            timeout=15
        )

        if verify_response.status_code != 200:
            logging.error(f"P24: Błąd weryfikacji końcowej (Verify). Status: {verify_response.status_code}, Body: {verify_response.text}")
            return "Verify failed", 500

        # --- KROK 3: Aktualizacja bazy danych ---
        # SessionId to nasz ManagementToken
        safe_session_id = ''.join(c for c in session_id if c.isalnum() or c == '-')
        lesson = reservations_table.first(formula=f"{{ManagementToken}} = '{safe_session_id}'")
        
        if lesson:
            reservations_table.update(lesson['id'], {
                "Oplacona": True, 
                "Status": "Opłacona"
            })
            logging.info(f"Lekcja {lesson['id']} została pomyślnie OPŁACONA.")
            
            # Odejmij wykorzystaną wolną kwotę
            wolna_uzyta = lesson['fields'].get('WolnaKwotaUzyta', 0)
            if wolna_uzyta > 0:
                client_id = lesson['fields'].get('Klient')
                if client_id:
                    subtract_free_amount(client_id, wolna_uzyta)
            
            # --- KROK 4: Powiadomienie Messenger ---
            if MESSENGER_PAGE_TOKEN:
                fields = lesson.get('fields', {})
                psid = fields.get('Klient')
                if psid:
                    msg = (
                        f"✅ Płatność otrzymana!\n"
                        f"Twoja lekcja z przedmiotu '{fields.get('Przedmiot')}' "
                        f"zaplanowana na {fields.get('Data')} o {fields.get('Godzina')} "
                        f"została pomyślnie opłacona. Dziękujemy!"
                    )
                    send_messenger_confirmation(psid, msg, MESSENGER_PAGE_TOKEN)
        else:
            logging.warning(f"P24: Otrzymano płatność, ale nie znaleziono lekcji dla sesji: {safe_session_id}")

        # P24 oczekuje odpowiedzi "OK" (status 200)
        return "OK", 200

    except Exception as e:
        logging.error(f"P24: Wyjątek w payment_notification: {e}", exc_info=True)
        return "Internal Error", 500

@app.route('/api/get-tutor-lessons')
def get_tutor_lessons():
    try:
        tutor_name = request.args.get('tutorName')
        if not tutor_name:
            abort(400, "Brak parametru tutorName.")

        # Pobierz mapę klientów z ich imionami i LINKAMI
        all_clients_records = clients_table.all()
        clients_map = {
            rec['fields'].get('ClientID'): {
                'studentFirstName': rec['fields'].get('Imie', 'Uczeń'),
                'studentLastName': rec['fields'].get('Nazwisko', ''),
                'clientFirstName': rec['fields'].get('ImieKlienta', 'Klient'),
                'clientLastName': rec['fields'].get('NazwiskoKlienta', ''),
                'link': None
            }
            for rec in all_clients_records if 'ClientID' in rec.get('fields', {})
        }

        formula = f"{{Korepetytor}} = '{tutor_name}'"
        lessons_records = reservations_table.all(formula=formula)

        upcoming_lessons = []
        today = datetime.now().date()
        for record in lessons_records:
            fields = record.get('fields', {})
            
            lesson_date_str = fields.get('Data')
            if not lesson_date_str:
                continue
            
            try:
                lesson_date = datetime.strptime(lesson_date_str, "%Y-%m-%d").date()
                if lesson_date < today:
                    continue
            except ValueError:
                continue
                
            status = fields.get('Status')
            if status in ['Niedostępny', 'Dostępny']:
                continue

            client_id = fields.get('Klient')
            client_info = clients_map.get(client_id, {})
            
            lesson_data = {
                'record_id': record['id'],
                'date': fields.get('Data'),
                'time': fields.get('Godzina'),
                'studentName': f"{client_info.get('studentFirstName', 'Brak danych')} {client_info.get('studentLastName', '')}",
                'studentFirstName': client_info.get('studentFirstName', 'Brak danych'),
                'studentLastName': client_info.get('studentLastName', ''),
                'clientFirstName': client_info.get('clientFirstName', 'Brak danych'),
                'clientLastName': client_info.get('clientLastName', ''),
                'studentContactLink': None,
                'subject': fields.get('Przedmiot'),
                'schoolType': fields.get('TypSzkoly'),
                'schoolLevel': fields.get('Poziom'),
                'schoolClass': fields.get('Klasa'),
                'teamsLink': fields.get('TeamsLink'),
                'isPaid': fields.get('Oplacona', False),
                'isTest': fields.get('JestTestowa', False)
            }
            upcoming_lessons.append(lesson_data)
        
        upcoming_lessons.sort(key=lambda x: datetime.strptime(f"{x['date']} {x['time']}", "%Y-%m-%d %H:%M"))

        return jsonify(upcoming_lessons)

    except Exception as e:
        traceback.print_exc()
        abort(500, "Wystąpił błąd serwera podczas pobierania lekcji korepetytora.")

@app.route('/api/get-master-schedule')
def get_master_schedule():
    try:
        # Fixed master time slots for the new block-based system
        master_time_slots = ['08:00', '09:10', '10:20', '11:30', '12:40', '13:50', '15:00', '16:10', '17:20', '18:30', '19:40', '20:50']
        return jsonify(master_time_slots)
        
    except Exception as e:
        traceback.print_exc()
        abort(500, "Błąd serwera podczas generowania głównego grafiku.")

@app.route('/api/tutor-reschedule', methods=['POST'])
def tutor_reschedule():
    try:
        data = request.json
        tutor_name, date, time = data.get('tutorName'), data.get('date'), data.get('time')

        formula = f"AND({{Korepetytor}} = '{tutor_name}', DATETIME_FORMAT({{Data}}, 'YYYY-MM-DD') = '{date}', {{Godzina}} = '{time}')"
        record_to_reschedule = reservations_table.first(formula=formula)

        if record_to_reschedule:
            # ### DODANO: Sprawdzanie, czy lekcja się już zakończyła ###
            if is_lesson_ended(record_to_reschedule):
                return jsonify({"message": "Nie można edytować terminów lekcji, które już się zakończyły."}), 403

            fields = record_to_reschedule.get('fields', {})
            psid = fields.get('Klient')

            reservations_table.update(record_to_reschedule['id'], {"Status": "Przeniesiona"})

            # --- DODANO POWIADOMIENIE ---
            if MESSENGER_PAGE_TOKEN and psid:
                dashboard_link = f"https://zakręcone-korepetycje.pl/moje-lekcje?clientID={psid}"
                message_to_send = (
                    f"Ważna informacja! Twój korepetytor musiał przenieść lekcję zaplanowaną na {date} o {time}.\n\n"
                    f"Prosimy o wejście do panelu klienta i wybranie nowego, dogodnego terminu:\n{dashboard_link}"
                )
                send_messenger_confirmation(psid, message_to_send, MESSENGER_PAGE_TOKEN)
            # --- KONIEC DODAWANIA ---

            return jsonify({"message": "Status lekcji został zmieniony na 'Przeniesiona'. Uczeń został poinformowany."})
        else:
            # Tutaj obsługujemy stały termin - jest trudniej znaleźć klienta, na razie pomijamy powiadomienie.
            new_exception = {
                "Korepetytor": tutor_name, "Data": date, "Godzina": time,
                "Status": "Przeniesiona", "Typ": "Cykliczna Wyjątek"
            }
            reservations_table.create(new_exception)
            return jsonify({"message": "Stały termin na ten dzień został oznaczony jako 'Przeniesiona'."})

    except Exception as e:
        traceback.print_exc()
        abort(500, "Wystąpił błąd podczas przenoszenia lekcji.")

@app.route('/api/add-adhoc-slot', methods=['POST'])
def add_adhoc_slot():
    try:
        data = request.json
        tutor_id, tutor_name, date, time = data.get('tutorID'), data.get('tutorName'), data.get('date'), data.get('time')

        if not all([tutor_id, tutor_name, date, time]):
            abort(400, "Brak wymaganych danych.")

        tutor_record = tutors_table.first(formula=f"{{TutorID}} = '{tutor_id.strip()}'")
        if not tutor_record or tutor_record['fields'].get('ImieNazwisko') != tutor_name:
            abort(403, "Brak uprawnień.")



        new_available_slot = {
            "Klient": "DOSTEPNY",  # Placeholder dla slotu bez klienta
            "Korepetytor": tutor_name,
            "Data": date,
            "Godzina": time,
            "Typ": "Jednorazowa",
            "Status": "Dostępny" # Ta opcja musi istnieć w Airtable
        }
        reservations_table.create(new_available_slot)

        print(f"DODANO JEDNORAZOWY TERMIN: {date} {time} dla {tutor_name}")
        # ### POPRAWKA - DODANO BRAKUJĄCY RETURN ###
        return jsonify({"message": "Dodano nowy, jednorazowy dostępny termin."})

    except Exception as e:
        traceback.print_exc()
        abort(500, "Wystąpił błąd podczas dodawania terminu.")


@app.route('/api/verify-client')
def verify_client():
    client_id = request.args.get('clientID')
    if not client_id: abort(400, "Brak identyfikatora klienta.")
    client_record = clients_table.first(formula=f"{{ClientID}} = '{client_id.strip()}'")
    if not client_record: abort(404, "Klient o podanym identyfikatorze nie istnieje.")
    return jsonify({"firstName": client_record['fields'].get('Imie'), "lastName": client_record['fields'].get('Nazwisko')})

@app.route('/api/get-tutor-schedule')
def get_tutor_schedule():
    tutor_id = request.args.get('tutorID')
    if not tutor_id: abort(400, "Brak identyfikatora korepetytora.")
    tutor_record = tutors_table.first(formula=f"{{TutorID}} = '{tutor_id.strip()}'")
    if not tutor_record: abort(404, "Nie znaleziono korepetytora.")
    fields = tutor_record.get('fields', {})

    # Parse schedule fields as JSON if they are arrays
    # Map old day names to new ones for backward compatibility
    day_mapping = {
        "Poniedziałek": ["Poniedziałek", "Poniedzialek"],
        "Wtorek": ["Wtorek", "Wtorek"],
        "Środa": ["Środa", "Sroda"],
        "Czwartek": ["Czwartek", "Czwartek"],
        "Piątek": ["Piątek", "Piatek"],
        "Sobota": ["Sobota", "Sobota"],
        "Niedziela": ["Niedziela", "Niedziela"]
    }

    schedule = {}
    for new_day, possible_names in day_mapping.items():
        value = None
        for name in possible_names:
            value = fields.get(name, "")
            if value:
                break
        if isinstance(value, str) and value:
            try:
                schedule[new_day] = json.loads(value)
            except json.JSONDecodeError:
                # Try ast.literal_eval for Python list format
                import ast
                try:
                    parsed = ast.literal_eval(value)
                    if isinstance(parsed, list):
                        schedule[new_day] = parsed
                    else:
                        schedule[new_day] = []
                except (ValueError, SyntaxError):
                    schedule[new_day] = []
        elif isinstance(value, list):
            schedule[new_day] = value
        else:
            schedule[new_day] = []

    return jsonify({
        "Imię i Nazwisko": fields.get("ImieNazwisko"),
        "Poniedziałek": schedule.get("Poniedziałek", []),
        "Wtorek": schedule.get("Wtorek", []),
        "Środa": schedule.get("Środa", []),
        "Czwartek": schedule.get("Czwartek", []),
        "Piątek": schedule.get("Piątek", []),
        "Sobota": schedule.get("Sobota", []),
        "Niedziela": schedule.get("Niedziela", []),
        "Przedmioty": normalize_tutor_field(fields.get("Przedmioty", [])),
        "PoziomNauczania": normalize_tutor_field(fields.get("PoziomNauczania", [])),
        "Email": fields.get("Email", ""),
        "LimitGodzinTygodniowo": fields.get("LimitGodzinTygodniowo")
    })

@app.route('/api/get-tutor-by-name')
def get_tutor_by_name():
    tutor_name = request.args.get('tutorName')
    if not tutor_name:
        abort(400, "Brak tutorName.")
    
    # Sanitize input by stripping whitespace
    tutor_name = tutor_name.strip()
    
    tutor_record = tutors_table.first(formula=f"{{ImieNazwisko}} = '{tutor_name}'")
    if not tutor_record:
        abort(404, "Nie znaleziono korepetytora.")
    
    return jsonify({
        "name": tutor_record['fields'].get('ImieNazwisko'),
        "contactLink": None
    })

@app.route('/api/update-tutor-schedule', methods=['POST'])
def update_tutor_schedule():
    data = request.json
    tutor_id = data.get('tutorID')
    new_schedule = data.get('schedule')
    if not tutor_id or not new_schedule: abort(400, "Brak wymaganych danych.")
    tutor_record = tutors_table.first(formula=f"{{TutorID}} = '{tutor_id.strip()}'")
    if not tutor_record: abort(404, "Nie znaleziono korepetytora.")
    fields_to_update = {day: json.dumps(time_range) if isinstance(time_range, list) else time_range for day, time_range in new_schedule.items() if time_range is not None}
    tutors_table.update(tutor_record['id'], fields_to_update)
    return jsonify({"message": "Grafik został pomyślnie zaktualizowany."})

@app.route('/api/update-tutor-profile', methods=['POST'])
def update_tutor_profile():
    data = request.json
    tutor_id = data.get('tutorID')
    poziom_nauczania = data.get('PoziomNauczania')
    email = data.get('Email')
    if not tutor_id: abort(400, "Brak identyfikatora korepetytora.")
    tutor_record = tutors_table.first(formula=f"{{TutorID}} = '{tutor_id.strip()}'")
    if not tutor_record: abort(404, "Nie znaleziono korepetytora.")
    fields_to_update = {}
    if email is not None:
        fields_to_update['Email'] = email
    if fields_to_update:
        tutors_table.update(tutor_record['id'], fields_to_update)
    return jsonify({"message": "Profil został pomyślnie zaktualizowany."})

@app.route('/api/block-single-slot', methods=['POST'])
def block_single_slot():
    try:
        data = request.json
        tutor_id = data.get('tutorID')
        tutor_name = data.get('tutorName')
        date = data.get('date')
        time = data.get('time')

        if not all([tutor_id, tutor_name, date, time]):
            abort(400, "Brak wymaganych danych.")

        tutor_record = tutors_table.first(formula=f"{{TutorID}} = '{tutor_id.strip()}'")
        if not tutor_record or tutor_record['fields'].get('ImieNazwisko') != tutor_name:
            abort(403, "Brak uprawnień.")

        formula = f"AND({{Korepetytor}} = '{tutor_name}', DATETIME_FORMAT({{Data}}, 'YYYY-MM-DD') = '{date}', {{Godzina}} = '{time}')"
        existing_reservation = reservations_table.first(formula=formula)

        if existing_reservation:
            fields = existing_reservation.get('fields', {})
            status = fields.get('Status')
            klient = fields.get('Klient')

            # Case 1: Unblocking a blocked slot
            if status == 'Niedostępny' or klient == 'BLOKADA':
                reservations_table.delete(existing_reservation['id'])
                return jsonify({"message": "Termin został odblokowany."})
            
            # Case 2: Blocking an ad-hoc available slot
            elif status == 'Dostępny' or klient == 'DOSTEPNY':
                update_data = { "Status": "Niedostępny", "Klient": "BLOKADA" }
                reservations_table.update(existing_reservation['id'], update_data)
                return jsonify({"message": "Termin został zablokowany."})

            # Case 3: It's a student's lesson
            else:
                return jsonify({"message": "Nie można zarządzać terminem, który jest zarezerwowany na lekcję. Użyj opcji 'Przełóż zajęcia'."}), 409
        else:
            # Case 4: No reservation exists, create a new block
            new_block = {
                "Klient": "BLOKADA", "Korepetytor": tutor_name, "Data": date,
                "Godzina": time, "Typ": "Jednorazowa", "Status": "Niedostępny"
            }
            reservations_table.create(new_block)
            return jsonify({"message": "Termin został zablokowany."})

    except Exception as e:
        traceback.print_exc()
        abort(500, "Wystąpił błąd podczas zmiany statusu terminu.")
        
# Importy i definicje pozostają bez zmian (datetime, timedelta, jsonify, etc.)

# Importy i definicje pozostają bez zmian (datetime, timedelta, jsonify, etc.)

@app.route('/api/get-schedule')
def get_schedule():
    global last_fetched_schedule
    try:
        start_date_str = request.args.get('startDate')
        if not start_date_str: abort(400, "Brak parametru startDate")
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = start_date + timedelta(days=7)
        
        school_type = request.args.get('schoolType')
        school_level = request.args.get('schoolLevel')
        
        # --- ZMIANA: Konwersja na małe litery od razu po pobraniu ---
        subject = request.args.get('subject', '').lower()
        tutor_name_filter = request.args.get('tutorName')
        client_id = request.args.get('clientID')
        all_tutors_templates = tutors_table.all()
        filtered_tutors = []

        if tutor_name_filter:
            found_tutor = next((t for t in all_tutors_templates if t.get('fields', {}).get('ImieNazwisko') == tutor_name_filter), None)
            if found_tutor:
                # Sprawdzenie limitu godzin tygodniowo
                fields = found_tutor.get('fields', {})
                tutor_name = fields.get('ImieNazwisko')
                tutor_limit = fields.get('LimitGodzinTygodniowo')
                if tutor_limit is not None:
                    week_start = get_week_start(start_date)
                    current_hours = get_tutor_hours_for_week(tutor_name, week_start)
                    
                    if current_hours >= tutor_limit:
                        # Korepetytor przekroczył limit - pomijamy go w grafiku
                        pass
                    else:
                        filtered_tutors.append(found_tutor)
                else:
                    # Brak limitu - dodaj korepetytora
                    filtered_tutors.append(found_tutor)
        else:
            if not all([school_type, subject]): abort(400, "Brak wymaganych parametrów (schoolType, subject)")
            
            required_level_tags = []
            if school_type == 'szkola_podstawowa': required_level_tags = LEVEL_MAPPING.get(school_type, [])
            elif (school_type in ['liceum', 'technikum']) and school_level:
                key_podstawa = f"{school_type}_podstawowy"
                required_level_tags = LEVEL_MAPPING.get(key_podstawa, [])
                if school_level == 'rozszerzony':
                    key_rozszerzenie = f"{school_type}_rozszerzony"
                    required_level_tags.extend(LEVEL_MAPPING.get(key_rozszerzenie, []))
            
            if not required_level_tags: return jsonify([])

            for tutor in all_tutors_templates:
                fields = tutor.get('fields', {})
                tutor_name = fields.get('ImieNazwisko')
                
                # --- ULEPSZONA LOGIKA: Obsługa list i stringów ---
                tutor_subjects = normalize_tutor_field(fields.get('Przedmioty', []))
                tutor_levels = normalize_tutor_field(fields.get('PoziomNauczania', []))
                # --- KONIEC ZMIAN ---

                # Teraz porównanie jest bezpieczne i niezależne od wielkości liter
                teaches_level = all(tag in tutor_levels for tag in required_level_tags)
                teaches_subject = subject in tutor_subjects
                
                # Wyjątek: jeśli klient miał jakiekolwiek zajęcia z tym korepetytorem, pokaż go nawet jeśli poziomy się zmieniły
                has_any_lessons = False
                if client_id and not teaches_level:
                    has_any_lessons = check_if_client_has_any_lessons_with_tutor(client_id, tutor_name)

                if (teaches_level and teaches_subject) or has_any_lessons:
                    # Sprawdzenie limitu godzin tygodniowo
                    tutor_limit = fields.get('LimitGodzinTygodniowo')
                    
                    if tutor_limit is not None:
                        week_start = get_week_start(start_date)
                        current_hours = get_tutor_hours_for_week(tutor_name, week_start)
                        
                        if current_hours >= tutor_limit:
                            # Korepetytor przekroczył limit - pomijamy go w grafiku
                            continue
                    
                    filtered_tutors.append(tutor)
        
        booked_slots = {}
        all_clients = {rec['fields'].get('ClientID'): rec['fields'] for rec in clients_table.all() if 'ClientID' in rec.get('fields', {})}
        formula_reservations = f"AND(IS_AFTER({{Data}}, DATETIME_PARSE('{start_date - timedelta(days=1)}', 'YYYY-MM-DD')), IS_BEFORE({{Data}}, DATETIME_PARSE('{end_date}', 'YYYY-MM-DD')))"
        reservations = reservations_table.all(formula=formula_reservations)
        
        for record in reservations:
            fields = record.get('fields', {})
            key = (fields.get('Korepetytor'), fields.get('Data'), fields.get('Godzina'))
            status = fields.get('Status')
            if status != 'Dostępny':
                student_name = all_clients.get(fields.get('Klient'), {}).get('Imie', 'Uczeń')
                client_info = all_clients.get(fields.get('Klient'), {})
                student_name = client_info.get('Imie', 'Uczeń')
                
                if status == 'Przeniesiona (zakończona)':
                    slot_status = "completed"
                elif status in ['Niedostępny', 'Przeniesiona']:
                    slot_status = 'blocked_by_tutor' if status == 'Niedostępny' else 'rescheduled_by_tutor'
                else:
                    slot_status = "booked_lesson"
                
                booked_slots[key] = {
                    "record_id": record['id'],
                    "status": slot_status,
                    "studentName": student_name if slot_status != "completed" else f"{student_name} (Zakończona)",
                    "studentFirstName": client_info.get('Imie', 'Uczeń'),
                    "studentLastName": client_info.get('Nazwisko', ''),
                    "clientFirstName": client_info.get('ImieKlienta', 'Klient'),
                    "clientLastName": client_info.get('NazwiskoKlienta', ''),
                    "studentContactLink": None,
                    "subject": fields.get('Przedmiot'), "schoolType": fields.get('TypSzkoly'),
                    "schoolLevel": fields.get('Poziom'), "schoolClass": fields.get('Klasa'), "teamsLink": fields.get('TeamsLink'),
                    "isPaid": fields.get('Oplacona', False),
                    "isTest": fields.get('JestTestowa', False)
                }


        cyclic_reservations = cyclic_reservations_table.all(formula="{Aktywna}=1")
        for rec in cyclic_reservations:
            fields = rec.get('fields', {})
            day_name = fields.get('DzienTygodnia')
            client_uuid = fields.get('Klient_ID')
            if not day_name or not client_uuid: continue
            try:
                day_num = list(WEEKDAY_MAP.keys())[list(WEEKDAY_MAP.values()).index(day_name)]
                for day_offset in range(7):
                    current_date = start_date + timedelta(days=day_offset)
                    if current_date.weekday() == day_num:
                        key = (fields.get('Korepetytor'), current_date.strftime('%Y-%m-%d'), fields.get('Godzina'))
                        if key not in booked_slots:
                            client_info = all_clients.get(client_uuid, {})
                            student_name = client_info.get('Imie', 'Uczeń')
                            booked_slots[key] = {
                                "status": "cyclic_reserved", "studentName": f"{student_name} (Cykliczne)",
                                "studentFirstName": client_info.get('Imie', 'Uczeń'),
                                "studentLastName": client_info.get('Nazwisko', ''),
                                "clientFirstName": client_info.get('ImieKlienta', 'Klient'),
                                "clientLastName": client_info.get('NazwiskoKlienta', ''),
                                "subject": fields.get('Przedmiot'), "schoolType": fields.get('TypSzkoly'),
                                "schoolLevel": fields.get('Poziom'), "schoolClass": fields.get('Klasa')
                            }
            except ValueError: pass
        
        master_start_time = dt_time(8, 0)
        master_end_time = dt_time(22, 0)
        master_times = ['08:00', '09:10', '10:20', '11:30', '12:40', '13:50', '15:00', '16:10', '17:20', '18:30', '19:40', '20:50']

        available_slots = []
        for template in filtered_tutors:
            fields = template.get('fields', {})
            tutor_name = fields.get('ImieNazwisko')
            if not tutor_name: continue
            for day_offset in range(7):
                current_date = start_date + timedelta(days=day_offset)
                day_name = WEEKDAY_MAP[current_date.weekday()]
                # Try to get schedule_value with backward compatibility for old day names
                possible_names = [day_name]  # Polish name
                if day_name == "Poniedziałek":
                    possible_names.append("Poniedzialek")
                elif day_name == "Środa":
                    possible_names.append("Sroda")
                elif day_name == "Piątek":
                    possible_names.append("Piatek")

                schedule_value = None
                for name in possible_names:
                    schedule_value = fields.get(name)
                    if schedule_value:
                        break

                if not schedule_value:
                    continue
                # Parse schedule_value if it's a JSON string (from database)
                if isinstance(schedule_value, str):
                    try:
                        schedule_value = json.loads(schedule_value)
                    except json.JSONDecodeError:
                        import ast
                        try:
                            parsed = ast.literal_eval(schedule_value)
                            if isinstance(parsed, list):
                                schedule_value = parsed
                            else:
                                schedule_value = []
                        except (ValueError, SyntaxError) as e:
                            schedule_value = []
                available_times = get_available_times_for_day(schedule_value, master_times)
                if not available_times:
                    continue
                current_date_str = current_date.strftime('%Y-%m-%d')
                slots_for_day = 0
                
                # === ŻELAZNA ZASADA 12 GODZIN (tylko dla widoku klienta) ===
                is_tutor_panel = bool(tutor_name_filter)
                now = datetime.now()
                min_booking_time = now + timedelta(hours=12)

                for slot_time_str in available_times:
                    key = (tutor_name, current_date_str, slot_time_str)
                    
                    # Stosuj zasadę 12h tylko w panelu klienta
                    if not is_tutor_panel:
                        try:
                            slot_time_obj = datetime.strptime(slot_time_str, "%H:%M").time()
                            slot_datetime = datetime.combine(current_date, slot_time_obj)
                            
                            if slot_datetime < min_booking_time:
                                continue
                        except ValueError:
                            continue
                    # Jeśli slot nie jest zajęty, dodaj go do listy dostępnych
                    if key not in booked_slots:
                        # ... reszta kodu dodawania slotu ...
                        available_slots.append({
                            'tutor': tutor_name,
                            'date': current_date_str,
                            'time': slot_time_str,
                            'status': 'available'
                        })
                        slots_for_day += 1
                
        adhoc_slots_count = 0
        for record in reservations:
            fields = record.get('fields', {})
            if fields.get('Status') == 'Dostępny':
                available_slots.append({
                    "tutor": fields.get('Korepetytor'), "date": fields.get('Data'),
                    "time": fields.get('Godzina'), "status": "available"
                })
                adhoc_slots_count += 1
        if tutor_name_filter:
            final_schedule = []
            final_schedule = [slot for slot in available_slots if slot.get('tutor') == tutor_name_filter]
            for template in filtered_tutors:
                fields = template.get('fields', {})
                tutor_name = fields.get('ImieNazwisko')
                if not tutor_name: continue
                for day_offset in range(7):
                    current_date = start_date + timedelta(days=day_offset)
                    day_name = WEEKDAY_MAP[current_date.weekday()]
                    schedule_value = fields.get(day_name)
                    if not schedule_value: continue
                    available_times = get_available_times_for_day(schedule_value, master_times)
                    if not available_times: continue

                    current_date_str = current_date.strftime('%Y-%m-%d')

                    # Try to get schedule_value with backward compatibility
                    possible_names = [day_name]
                    if day_name == "Poniedziałek":
                        possible_names.append("Poniedzialek")
                    elif day_name == "Środa":
                        possible_names.append("Sroda")
                    elif day_name == "Piątek":
                        possible_names.append("Piatek")

                    schedule_value = None
                    for name in possible_names:
                        schedule_value = fields.get(name)
                        if schedule_value:
                            break
                    if not schedule_value:
                        continue
                    # Parse schedule_value if it's a JSON string
                    if isinstance(schedule_value, str):
                        try:
                            parsed = json.loads(schedule_value)
                            schedule_value = parsed
                        except json.JSONDecodeError as e:
                            import ast
                            try:
                                parsed = ast.literal_eval(schedule_value)
                                if isinstance(parsed, list):
                                    schedule_value = parsed
                                else:
                                    schedule_value = []
                            except (ValueError, SyntaxError) as e:
                                schedule_value = []
                    available_times = get_available_times_for_day(schedule_value, master_times)
                    if not available_times:
                        continue
                    current_date_str = current_date.strftime('%Y-%m-%d')
                    slots_for_day = 0
                    for slot_time_str in available_times:
                        key = (tutor_name, current_date_str, slot_time_str)

                        slot_info = {'tutor': tutor_name, 'date': current_date_str, 'time': slot_time_str}
                        if key in booked_slots:
                            slot_info.update(booked_slots[key])
                        else:
                            slot_info['status'] = 'available'
                            slots_for_day += 1

                        final_schedule.append(slot_info)
            # --- DODANA LOGIKA: Dodanie zarezerwowanych slotów spoza grafiku stałego (włączając lekcje z przeszłości) ---
            covered_slots = set()
            for slot in final_schedule:
                covered_slots.add((slot['tutor'], slot['date'], slot['time']))
                
            booked_slots_not_in_schedule = []
            for key, slot_data in booked_slots.items():
                tname, tdate, ttime = key
                # Sprawdzamy, czy slot jest dla bieżącego korepetytora i nie został już dodany (np. był poza grafikiem stałym)
                if tname == tutor_name_filter and key not in covered_slots:
                    # Sprawdzamy czy czas jest w master_times, aby poprawnie wyświetlić w gridzie kalendarza
                    if ttime in master_times:
                        slot_data['tutor'] = tname
                        slot_data['date'] = tdate
                        slot_data['time'] = ttime
                        booked_slots_not_in_schedule.append(slot_data)
            
            final_schedule.extend(booked_slots_not_in_schedule)
            # --- KONIEC DODANEJ LOGIKI ---
            adhoc_slots_count = 0
            for record in reservations:
                fields = record.get('fields', {})
                if fields.get('Status') == 'Dostępny':
                    # Check if this ad-hoc slot belongs to the filtered tutor, if filtering is active
                    if tutor_name_filter and fields.get('Korepetytor') != tutor_name_filter:
                        continue
                    final_schedule.append({
                        "tutor": fields.get('Korepetytor'), "date": fields.get('Data'),
                        "time": fields.get('Godzina'), "status": "available"
                    })
                    adhoc_slots_count += 1
            return jsonify(final_schedule)
        else:
            last_fetched_schedule = available_slots
            return jsonify(available_slots)

    except Exception as e:
        traceback.print_exc()
        abort(500, "Wewnętrzny błąd serwera.")


@app.route('/api/create-reservation', methods=['POST'])
def create_reservation():
    try:
        data = request.json
        
        # === DODAJ LOGI DIAGNOSTYCZNE ===
        logging.info("="*60)
        logging.info("OTRZYMANO ZAPYTANIE /api/create-reservation")
        logging.info(f"Pełne dane z request.json: {json.dumps(data, indent=2, ensure_ascii=False)}")
        logging.info(f"Typ pola 'privacyPolicyAccepted': {type(data.get('privacyPolicyAccepted'))}")
        logging.info(f"Wartość pola 'privacyPolicyAccepted': {data.get('privacyPolicyAccepted')}")
        logging.info(f"Czy 'privacyPolicyAccepted' jest True: {data.get('privacyPolicyAccepted') is True}")
        logging.info("="*60)
        # === KONIEC LOGÓW ===
        
        # Opcjonalnie - log wartości dla debugowania
        privacy_policy_accepted = data.get('privacyPolicyAccepted', True)
        logging.info(f"privacyPolicyAccepted: {privacy_policy_accepted}")
        
        # isOneTime jest True, jeśli klient zaznaczył "To jest lekcja jednorazowa"
        # Jeśli pole nie istnieje w zapytaniu (jak na stronie rezerwacji testowej), to NIE jest to isOneTime,
        # co oznacza, że jest to rezerwacja testowa, a isCyclic = False.
        is_test_lesson = 'isOneTime' not in data
        is_cyclic = not data.get('isOneTime', False) if not is_test_lesson else False
        
        client_uuid = data.get('clientID') # To jest PSID
        if not client_uuid: abort(400, "Brak ClientID.")
        
        client_record = clients_table.first(formula=f"{{ClientID}} = '{client_uuid.strip()}'")

        if is_test_lesson and check_if_client_has_booked_test_lesson(client_uuid):
            abort(409, "Klient ma już zarezerwowaną lub miał już lekcję testową. Można zarezerwować tylko jedną lekcję testową.")
        
        if not client_record: abort(404, "Klient nie istnieje.")
        
        first_name_from_form = data.get('firstName')
        last_name_from_form = data.get('lastName')
        
        client_update_data = {}
        if first_name_from_form: client_update_data['Imie'] = first_name_from_form
        if last_name_from_form: client_update_data['Nazwisko'] = last_name_from_form

        if client_update_data:
            clients_table.update(client_record['id'], client_update_data)
        
        first_name = first_name_from_form or client_record['fields'].get('Imie')
        
        tutor_for_reservation = data['tutor']
        if tutor_for_reservation == 'Dowolny dostępny':
            start_date_for_search = datetime.strptime(data['selectedDate'], '%Y-%m-%d').date()
            school_type_for_search = data.get('schoolType')
            school_level_for_search = data.get('schoolLevel')
            subject_for_search = data.get('subject')
            all_tutors_templates = tutors_table.all()
            available_tutors_for_slot = []
            for tutor_template in all_tutors_templates:
                fields = tutor_template.get('fields', {})
                tutor_name = fields.get('ImieNazwisko')
                required_level_tags = []
                if school_type_for_search == 'szkola_podstawowa': required_level_tags = LEVEL_MAPPING.get(school_type_for_search, [])
                elif (school_type_for_search in ['liceum', 'technikum']) and school_level_for_search:
                    key_podstawa = f"{school_type_for_search}_podstawowy"
                    required_level_tags = LEVEL_MAPPING.get(key_podstawa, [])
                    if school_level_for_search == 'rozszerzony':
                        key_rozszerzenie = f"{school_type_for_search}_rozszerzony"
                        required_level_tags.extend(LEVEL_MAPPING.get(key_rozszerzenie, []))
                
                # Normalize fields to handle both list and string types
                tutor_levels = normalize_tutor_field(fields.get('PoziomNauczania', []))
                tutor_subjects = normalize_tutor_field(fields.get('Przedmioty', []))
                
                teaches_this_level = all(tag in tutor_levels for tag in required_level_tags)
                teaches_this_subject = subject_for_search in tutor_subjects
                if teaches_this_level and teaches_this_subject:
                    day_of_week_name = WEEKDAY_MAP[start_date_for_search.weekday()]
                    schedule_value = fields.get(day_of_week_name)
                    
                    is_slot_available = False
                    selected_time = data['selectedTime']

                    if schedule_value:
                        # 1. Sprawdź czy to format listy (nowy system blokowy)
                        # Może być listą pythonową lub stringiem z JSONem
                        schedule_list = []
                        if isinstance(schedule_value, list):
                            schedule_list = schedule_value
                        elif isinstance(schedule_value, str):
                            try:
                                # Próba parsowania JSON
                                schedule_list = json.loads(schedule_value)
                            except json.JSONDecodeError:
                                # Jeśli nie JSON, to może być stary format zakresu
                                pass
                        
                        # Jeśli udało się uzyskać listę, sprawdzamy czy godzina w niej jest
                        if isinstance(schedule_list, list) and schedule_list:
                            if selected_time in schedule_list:
                                is_slot_available = True
                        
                        # 2. Jeśli nie udało się dopasować listy, sprawdź stary format zakresu (np. "14:00-20:00")
                        if not is_slot_available and isinstance(schedule_value, str) and '-' in schedule_value:
                            start_work, end_work = parse_time_range(schedule_value)
                            try:
                                selected_time_obj = datetime.strptime(selected_time, '%H:%M').time()
                                if start_work and end_work and start_work <= selected_time_obj < end_work:
                                    is_slot_available = True
                            except ValueError:
                                pass

                    if is_slot_available:
                        # Dodatkowe sprawdzenie: czy ten konkretny slot nie jest już zajęty u tego korepetytora
                        # (System wcześniej sprawdzał tylko ogólny grafik pracy, a nie konkretne zajętości w Rezerwacjach)
                        busy_check_formula = f"AND({{Korepetytor}} = '{tutor_name}', {{Data}} = '{data['selectedDate']}', {{Godzina}} = '{selected_time}', NOT({{Status}} = 'Anulowana (brak płatności)'), NOT({{Status}} = 'Przeniesiona (zakończona)'))"
                        is_busy = reservations_table.first(formula=busy_check_formula)
                        
                        if not is_busy:
                            available_tutors_for_slot.append(tutor_name)
            if not available_tutors_for_slot:
                abort(500, "Brak dostępnych korepetytorów.")
            tutor_for_reservation = available_tutors_for_slot[0]

        extra_info = {
            "TypSzkoly": data.get('schoolType'), "Poziom": data.get('schoolLevel'), "Klasa": data.get('schoolClass')
        }

        # Sprawdzenie limitu godzin dla korepetytora
        tutor_record = tutors_table.first(formula=f"{{ImieNazwisko}} = '{tutor_for_reservation}'")
        if tutor_record:
            tutor_limit = tutor_record['fields'].get('LimitGodzinTygodniowo')

            if tutor_limit is not None:
                lesson_date = datetime.strptime(data['selectedDate'], '%Y-%m-%d').date()
                week_start = get_week_start(lesson_date)
                current_hours = get_tutor_hours_for_week(tutor_for_reservation, week_start)

                if current_hours >= tutor_limit:
                    has_any_lessons = check_if_client_has_any_lessons_with_tutor(client_uuid, tutor_for_reservation)
                    if not has_any_lessons:
                        abort(409, f"Korepetytor osiągnął limit godzin ({tutor_limit}h) w tym tygodniu.")

        if is_cyclic:
            lesson_date = datetime.strptime(data['selectedDate'], '%Y-%m-%d').date()
            day_of_week_name = WEEKDAY_MAP[lesson_date.weekday()]
            new_cyclic_reservation = {
                "Klient_ID": client_uuid.strip(), "Korepetytor": tutor_for_reservation,
                "DzienTygodnia": day_of_week_name, "Godzina": data['selectedTime'],
                "Przedmiot": data.get('subject'), "Aktywna": True
            }
            new_cyclic_reservation.update(extra_info)
            cyclic_reservations_table.create(new_cyclic_reservation)

            # --- POWIADOMIENIE MESSENGER: CYKLICZNA ---
            if MESSENGER_PAGE_TOKEN:
                psid = client_uuid.strip()
                dashboard_link = f"https://zakręcone-korepetycje.pl/moje-lekcje?clientID={psid}"
                message_to_send = (
                    f"Dziękujemy! Twój stały termin na {data['subject']} w każdy {day_of_week_name} o {data['selectedTime']} został pomyślnie zarezerwowany.\n\n"
                    f"Pamiętaj, aby potwierdzać każdą nadchodzącą lekcję w swoim panelu klienta:\n{dashboard_link}"
                )
                send_messenger_confirmation(psid, message_to_send, MESSENGER_PAGE_TOKEN)
            # --- KONIEC POWIADOMIENIA ---

            return jsonify({"message": "Stały termin został pomyślnie zarezerwowany.", "clientID": client_uuid, "isCyclic": True})

        else: # Lekcja jednorazowa lub testowa
            management_token = str(uuid.uuid4())
            teams_link = generate_teams_meeting_link(f"Korepetycje: {data['subject']} dla {first_name}")
            if not teams_link: abort(500, "Nie udało się wygenerować linku Teams.")

            new_one_time_reservation = {
                "Klient": client_uuid.strip(), "Korepetytor": tutor_for_reservation,
                "Data": data['selectedDate'], "Godzina": data['selectedTime'],
                "Przedmiot": data.get('subject'), "ManagementToken": management_token,
                "Typ": "Jednorazowa", "Status": "Oczekuje na płatność", "TeamsLink": teams_link,
                "JestTestowa": is_test_lesson
            }
            
            # Dla lekcji testowych ustaw deadline potwierdzenia na 24h przed lekcją
            if is_test_lesson:
                lesson_datetime_str = f"{data['selectedDate']} {data['selectedTime']}"
                lesson_start = datetime.strptime(lesson_datetime_str, "%Y-%m-%d %H:%M")
                confirmation_deadline = lesson_start - timedelta(hours=24)
                new_one_time_reservation["confirmation_deadline"] = confirmation_deadline.strftime("%Y-%m-%d %H:%M:%S")
            
            new_one_time_reservation.update(extra_info)
            reservations_table.create(new_one_time_reservation)
            
            # Powiadomienie korepetytora o nowej lekcji
            lesson_details = f"Przedmiot: {data.get('subject')}, Data: {data['selectedDate']}, Godzina: {data['selectedTime']}, Klient: {first_name}"
            notify_tutor_about_lesson_change(tutor_for_reservation, "new", lesson_details)
            
            # --- DODANIE ZADANIA FOLLOW-UP DLA LEKCJI TESTOWEJ ---
            if is_test_lesson:
                
                # 1. Określenie czasu startu
                lesson_datetime_str = f"{data['selectedDate']} {data['selectedTime']}"
                lesson_start_naive = datetime.strptime(lesson_datetime_str, "%Y-%m-%d %H:%M")
                warsaw_tz = pytz.timezone('Europe/Warsaw')
                lesson_start_aware = warsaw_tz.localize(lesson_start_naive)
                
                # 2. Ustawienie uruchomienia na 90 minut po planowanym starcie
                follow_up_time = lesson_start_aware + timedelta(minutes=62)

                # 3. Dodanie zadania do schedulera
                scheduler.add_job(
                    func=send_followup_message,
                    trigger='date',
                    run_date=follow_up_time,
                    id=f'follow_up_{client_uuid}_{data["selectedDate"]}_{data["selectedTime"]}',
                    args=[client_uuid, data['selectedDate'], data['selectedTime'], data['subject']]
                )
                logging.info(f"SCHEDULER: Zaplanowano follow-up dla {client_uuid} na {follow_up_time}.")
                
                # 4. Dodanie zadania przypomnienia o potwierdzeniu na 24h przed lekcją
                confirmation_reminder_time = lesson_start_aware - timedelta(hours=24)
                scheduler.add_job(
                    func=send_confirmation_reminder,
                    trigger='date',
                    run_date=confirmation_reminder_time,
                    id=f'confirmation_reminder_{management_token}',
                    args=[management_token]
                )
                logging.info(f"SCHEDULER: Zaplanowano przypomnienie o potwierdzeniu dla {client_uuid} na {confirmation_reminder_time}.")
                
# --- POWIADOMIENIE MESSENGER: JEDNORAZOWA/TESTOWA ---
            if is_test_lesson: wiadomosc = "Lekcje można opłacić do 5 minut po rozpoczęciu zajęć. W przypadku zrezygnowania z zajeć, bardzo prosimy o odwołanie ich w panelu klienta."

            else: wiadomosc = "Pamiętaj aby opłacić lekcję do 12h przed rozpoczęciem. Nieopłacona lekcja zostanie automatycznie odwołana."

            if MESSENGER_PAGE_TOKEN:
                psid = client_uuid.strip()
                dashboard_link = f"https://zakręcone-korepetycje.pl/moje-lekcje?clientID={psid}"

                
                message_to_send = (
                    f"Dziękujemy za rezerwację!\n\n"
                    f"Twoja jednorazowa lekcja z przedmiotu '{data['subject']}' została pomyślnie umówiona na dzień "
                    f"{data['selectedDate']} o godzinie {data['selectedTime']}.\n\n"
                )

                # Dodaj ostrzeżenie o potwierdzeniu dla lekcji testowej
                if is_test_lesson:
                    # Oblicz czas do lekcji, aby dostosować wiadomość
                    lesson_datetime_str = f"{data['selectedDate']} {data['selectedTime']}"
                    lesson_datetime = datetime.strptime(lesson_datetime_str, '%Y-%m-%d %H:%M')
                    now = datetime.now()
                    time_diff = lesson_datetime - now
                    hours_diff = time_diff.total_seconds() / 3600

                    if hours_diff <= 24:
                        # Jeśli rezerwacja jest 24h przed lub mniej, klient może już teraz potwierdzić
                        message_to_send += (
                            f"⚠️ UWAGA: Lekcje testowe wymagają potwierdzenia.\n"
                            f"Możesz już teraz potwierdzić lekcję w panelu klienta.\n\n"
                        )
                    else:
                        # Jeśli więcej niż 24h, klient otrzyma przypomnienie
                        message_to_send += (
                            f"⚠️ UWAGA: Lekcje testowe wymagają potwierdzenia 24 godziny przed terminem.\n"
                            f"Otrzymasz przypomnienie na Messenger z linkiem do potwierdzenia.\n"
                            f"Możesz też potwierdzić lekcję w panelu klienta.\n\n"
                        )

                
                message_to_send += (
                    f"Możesz zarządzać, zmieniać termin, odwoływać swoje lekcje w osobistym panelu klienta pod adresem:\n{dashboard_link}\n\n"
                    f"{wiadomosc}"
                )
                send_messenger_confirmation(psid, message_to_send, MESSENGER_PAGE_TOKEN)
            else:
                print("!!! OSTRZEŻENIE: Nie wysłano wiadomości na Messengerze - brak tokena.")
            # --- KONIEC POWIADOMIENIA ---
            
            return jsonify({
                "teamsUrl": teams_link, "managementToken": management_token,
                "clientID": client_uuid, "isCyclic": False, "isTest": is_test_lesson,
                "tutorName": tutor_for_reservation
            })

    except Exception as e:
        traceback.print_exc()
        abort(500, "Błąd serwera podczas zapisu rezerwacji.")


@app.route('/api/confirm-next-lesson', methods=['POST'])
def confirm_next_lesson():
    try:
        cyclic_reservation_id = request.json.get('cyclicReservationId')
        if not cyclic_reservation_id: 
            abort(400, "Brak ID stałej rezerwacji.")

        cyclic_record = cyclic_reservations_table.get(cyclic_reservation_id)
        if not cyclic_record: 
            abort(404, "Nie znaleziono stałej rezerwacji.")
        
        fields = cyclic_record.get('fields', {})
        client_uuid = fields.get('Klient_ID', '').strip()
        tutor = fields.get('Korepetytor')
        day_name = fields.get('DzienTygodnia')
        lesson_time = fields.get('Godzina')
        subject = fields.get('Przedmiot')
        
        client_record = clients_table.first(formula=f"{{ClientID}} = '{client_uuid}'")
        if not client_record: 
            abort(404, "Powiązany klient nie istnieje.")
        first_name = client_record['fields'].get('Imie')

        day_num = list(WEEKDAY_MAP.keys())[list(WEEKDAY_MAP.values()).index(day_name)]
        today = datetime.now().date()
        days_ahead = day_num - today.weekday()
        if days_ahead <= 0: 
            days_ahead += 7
        next_lesson_date = today + timedelta(days=days_ahead)
        next_lesson_date_str = next_lesson_date.strftime('%Y-%m-%d')

        next_lesson_datetime_str = f"{next_lesson_date_str} {lesson_time}"
        next_lesson_dt = datetime.strptime(next_lesson_datetime_str, '%Y-%m-%d %H:%M')
        
        # === BLOKADA POTWIERDZANIA < 12H ===
        if next_lesson_dt < datetime.now() + timedelta(hours=12):
             abort(400, "Zbyt późno na potwierdzenie. Lekcję należy potwierdzić minimum 12 godzin przed jej rozpoczęciem.")
        # ===================================

        # Sprawdź, czy termin nie jest już zajęty
        formula_check = f"AND({{Korepetytor}} = '{tutor}', DATETIME_FORMAT({{Data}}, 'YYYY-MM-DD') = '{next_lesson_date_str}', {{Godzina}} = '{lesson_time}')"
        existing_reservation = reservations_table.first(formula=formula_check)

        if existing_reservation:
            temp_token = str(uuid.uuid4())
            temp_reservation = {
                "Klient": client_uuid, "Korepetytor": tutor, "Data": next_lesson_date_str,
                "Godzina": lesson_time, "Przedmiot": subject, "ManagementToken": temp_token,
                "Typ": "Cykliczna", "Status": "Przeniesiona"
            }
            reservations_table.create(temp_reservation)
            return jsonify({
                "error": "CONFLICT",
                "message": f"Niestety, termin {next_lesson_date_str} o {lesson_time} został w międzyczasie jednorazowo zablokowany przez korepetytora.",
                "managementToken": temp_token
            }), 409

        teams_link = generate_teams_meeting_link(f"Korepetycje: {subject} dla {first_name}")
        if not teams_link: 
            abort(500, "Nie udało się wygenerować linku Teams.")

        management_token = str(uuid.uuid4())
        new_confirmed_lesson = {
            "Klient": client_uuid,
            "Korepetytor": tutor,
            "Data": next_lesson_date_str,
            "Godzina": lesson_time,
            "Przedmiot": subject,
            "ManagementToken": management_token,
            "Typ": "Cykliczna",
            "Status": "Oczekuje na płatność",
            "TeamsLink": teams_link,
            "TypSzkoly": fields.get('TypSzkoly'),
            "Poziom": fields.get('Poziom'),
            "Klasa": fields.get('Klasa')
        }
        
        new_confirmed_lesson = {k: v for k, v in new_confirmed_lesson.items() if v is not None}
        
        # --- KLUCZOWE LOGI TUTAJ ---
        print("\n--- Rozpoczynam zapis do Airtable ---")
        print("Dane do zapisu:", json.dumps(new_confirmed_lesson, indent=2))
        klient_value = new_confirmed_lesson.get("Klient")
        print(f"Wartość dla pola 'Klient': '{klient_value}'")
        print(f"Typ wartości dla pola 'Klient': {type(klient_value)}")
        
        reservations_table.create(new_confirmed_lesson)
        print("SUKCES: Zapisano w Airtable.")

        # Powiadomienie korepetytora o potwierdzonej lekcji
        lesson_details = f"Przedmiot: {subject}, Data: {next_lesson_date_str}, Godzina: {lesson_time}, Klient: {first_name}"
        notify_tutor_about_lesson_change(tutor, "confirmed", lesson_details)

        # --- DODANO POWIADOMIENIE ---
        if MESSENGER_PAGE_TOKEN:
            psid = client_uuid.strip()
            dashboard_link = f"https://zakręcone-korepetycje.pl/moje-lekcje?clientID={psid}"
            message_to_send = (
                f"Potwierdzono! Twoja nadchodząca lekcja z przedmiotu '{subject}' została potwierdzona na dzień {next_lesson_date_str} o {lesson_time}.\n\n"
                f"Prosimy o opłacenie jej najpóźniej 12 godzin przed rozpoczęciem. Możesz zarządzać swoimi lekcjami tutaj:\n{dashboard_link}"
            )
            send_messenger_confirmation(psid, message_to_send, MESSENGER_PAGE_TOKEN)
        # --- KONIEC DODAWANIA ---
        
        return jsonify({
            "message": f"Najbliższa lekcja w dniu {next_lesson_date_str} została potwierdzona.", 
            "teamsUrl": teams_link,
            "managementToken": management_token
        })
    except Exception as e:
        print("!!! KRYTYCZNY BŁĄD w confirm_next_lesson !!!")
        traceback.print_exc()
        abort(500, "Wystąpił błąd podczas potwierdzania lekcji.")
        
@app.route('/api/get-client-dashboard')
def get_client_dashboard():
    try:
        client_id = request.args.get('clientID')
        if not client_id: 
            logging.error("Dashboard: Brak identyfikatora klienta.")
            abort(400, "Brak identyfikatora klienta.")
        
        client_id = client_id.strip()
        logging.debug(f"Dashboard: Przetwarzanie dla ClientID: {client_id}")
        
        client_record = clients_table.first(formula=f"{{ClientID}} = '{client_id}'")
        if not client_record: 
            logging.error(f"Dashboard: Nie znaleziono klienta dla ClientID: {client_id}")
            abort(404, "Nie znaleziono klienta.")
        client_name = client_record['fields'].get('Imie', 'Uczniu')

        all_tutors_records = tutors_table.all()
        all_reservations = reservations_table.all(formula=f"{{Klient}} = '{client_id}'")
        logging.debug(f"Dashboard: Znaleziono {len(all_reservations)} rezerwacji dla klienta.")
        
        upcoming = []
        past = []
        
        # --- BLOK ZWIĘKSZONEGO LOGOWANIA DLA REZERWACJI ---
        for record in all_reservations:
            record_id = record.get('id', 'N/A')
            fields = record.get('fields', {})
            
            if 'Data' not in fields or 'Godzina' not in fields: 
                logging.warning(f"Dashboard: Pominięto rezerwację ID: {record_id} - brak pól Data lub Godzina.")
                continue
            
            try:
                # W tym miejscu najczęściej występuje błąd 500 (ValueError)
                lesson_datetime = datetime.strptime(f"{fields['Data']} {fields['Godzina']}", "%Y-%m-%d %H:%M")
                logging.debug(f"Dashboard: Pomyślnie sparsowano datę dla rekordu ID: {record_id} ({fields['Data']} {fields['Godzina']}).")
            except ValueError as e:
                logging.error(f"Dashboard: BŁĄD KRYTYCZNY formatu daty dla rekordu ID: {record_id}. Dane: Data='{fields.get('Data')}', Godzina='{fields.get('Godzina')}'. Wyjątek: {e}", exc_info=True)
                # Kontynuujemy do następnego rekordu, żeby nie zepsuć całej strony (jeśli chcemy, żeby się ładowała)
                continue 
            
            status = fields.get('Status', 'N/A')
            
            lesson_data = {
                "date": fields.get('Data'),
                "time": fields.get('Godzina'),
                "tutor": fields.get('Korepetytor', 'N/A'),
                "subject": fields.get('Przedmiot', 'N/A'),
                "managementToken": fields.get('ManagementToken'),
                "status": status,
                "teamsLink": fields.get('TeamsLink'),
                "tutorContactLink": None,
                "isPaid": fields.get('Oplacona', False),
                "Typ": fields.get('Typ'),
                "isTest": fields.get('JestTestowa', False),
                "confirmed": fields.get('confirmed', False)
            }
            
            inactive_statuses = ['Anulowana (brak płatności)', 'Przeniesiona (zakończona)']
            is_test_lesson = fields.get('JestTestowa', False)
            is_paid = fields.get('Oplacona', False)
            
            # Lekcje trafiają do historii dopiero 1h po zakończeniu
            lesson_end_time = lesson_datetime + timedelta(hours=1)
            
            # Wszystkie lekcje idą do historii po zakończeniu
            should_go_to_past = False
            if status in inactive_statuses:
                should_go_to_past = True
            elif lesson_end_time < datetime.now():
                should_go_to_past = True
            
            if should_go_to_past:
                past.append(lesson_data)
            else:
                # Dodajemy informację czy lekcja jest w trakcie
                is_ongoing = lesson_datetime <= datetime.now() < lesson_end_time
                lesson_data['isOngoing'] = is_ongoing
                upcoming.append(lesson_data)
        # --- KONIEC BLOKU ZWIĘKSZONEGO LOGOWANIA ---

        # --- BLOK ZWIĘKSZONEGO LOGOWANIA DLA SORTOWANIA ---
        try:
            upcoming.sort(key=lambda x: datetime.strptime(f"{x['date']} {x['time']}", "%Y-%m-%d %H:%M"))
            past.sort(key=lambda x: datetime.strptime(f"{x['date']} {x['time']}", "%Y-%m-%d %H:%M"), reverse=True)
            logging.debug("Dashboard: Pomyślnie posortowano rezerwacje.")
        except Exception as e:
            logging.error(f"Dashboard: BŁĄD KRYTYCZNY podczas sortowania rezerwacji. Wyjątek: {e}", exc_info=True)
            # Używamy 'pass', aby zignorować błąd sortowania, jeśli dane są problematyczne,
            # co pozwoli załadować stronę nawet z nieposortowanymi listami.
            pass
        # --- KONIEC BLOKU ZWIĘKSZONEGO LOGOWANIA DLA SORTOWANIA ---

        cyclic_lessons = []
        cyclic_records = cyclic_reservations_table.all(formula=f"{{Klient_ID}} = '{client_id}'")
        logging.debug(f"Dashboard: Znaleziono {len(cyclic_records)} rezerwacji stałych.")
        
        today = datetime.now().date()

        for record in cyclic_records:
            record_id_cyclic = record.get('id', 'N/A')
            fields = record.get('fields', {})
            day_name = fields.get('DzienTygodnia')
            lesson_time = fields.get('Godzina')
            
            if not day_name or not lesson_time:
                logging.warning(f"Dashboard: Pominięto rezerwację stałą ID: {record_id_cyclic} - brak Dnia Tygodnia lub Godziny.")
                continue
            
            try:
                day_num = list(WEEKDAY_MAP.keys())[list(WEEKDAY_MAP.values()).index(day_name)]
            except ValueError:
                logging.warning(f"Dashboard: Pominięto rezerwację stałą ID: {record_id_cyclic} - nieprawidłowa nazwa dnia tygodnia: {day_name}.")
                continue
                
            days_ahead = day_num - today.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            next_lesson_date = today + timedelta(days=days_ahead)
            
            is_next_lesson_confirmed = False
            for lesson in upcoming:
                try:
                    lesson_date_str = lesson.get('date')
                    if not lesson_date_str:
                        continue
                    lesson_date = datetime.strptime(lesson_date_str, '%Y-%m-%d').date()
                    if (lesson.get('Typ') == 'Cykliczna' and 
                        lesson_date == next_lesson_date and 
                        lesson.get('time') == lesson_time):
                        is_next_lesson_confirmed = True
                        break
                except (ValueError, TypeError):
                    logging.warning(f"Dashboard: Błąd parsowania daty w `upcoming` przy sprawdzaniu potwierdzenia rezerwacji stałej. Dane: {lesson}")
                    continue

            tutor_name = fields.get('Korepetytor')
            cyclic_lessons.append({
                "id": record['id'],
                "dayOfWeek": fields.get('DzienTygodnia'),
                "time": fields.get('Godzina'),
                "tutor": tutor_name,
                "subject": fields.get('Przedmiot'),
                "isNextLessonConfirmed": is_next_lesson_confirmed,
                "tutorContactLink": None
            })

        logging.info(f"Dashboard: Pomyślnie wygenerowano dane dla panelu klienta {client_id}.")
        return jsonify({
            "clientName": client_name,
            "cyclicLessons": cyclic_lessons,
            "upcomingLessons": upcoming,
            "pastLessons": past
        })
    except Exception as e:
        # Ten blok łapie błąd 500 i loguje pełny traceback
        logging.error(f"!!! KRYTYCZNY BŁĄD w get_client_dashboard dla clientID {request.args.get('clientID', 'N/A')} !!!", exc_info=True)
        abort(500, "Wystąpił błąd podczas pobierania danych panelu klienta.")

@app.route('/api/get-reservation-details')
def get_reservation_details():
    try:
        token = request.args.get('token')
        logging.info(f"DETAILS: Pobieranie szczegółów dla tokena: {token}")
        record = find_reservation_by_token(token)
        if not record: 
            logging.warning(f"DETAILS: Nie znaleziono rezerwacji dla tokena: {token}")
            abort(404, "Nie znaleziono rezerwacji o podanym identyfikatorze.")
        
        fields = record.get('fields', {})
        logging.info(f"DETAILS: Znaleziono rekord: {json.dumps(fields, indent=2)}")
        
        client_uuid = fields.get('Klient')
        student_name = "N/A"
        
        if client_uuid:
            client_record = clients_table.first(formula=f"{{ClientID}} = '{client_uuid}'")
            if client_record:
                student_name = client_record.get('fields', {}).get('Imie', 'N/A')

        tutor_name = fields.get('Korepetytor')

        return jsonify({
            "date": fields.get('Data'),
            "time": fields.get('Godzina'),
            "tutor": tutor_name,
            "student": student_name,
            "isCancellationAllowed": is_cancellation_allowed(record),
            "isTestLesson": fields.get('JestTestowa', False),
            "clientID": client_uuid,
            "tutorContactLink": None
        })
    except Exception as e:
        traceback.print_exc()
        abort(500, "Wystąpił błąd podczas pobierania szczegółów rezerwacji.")

@app.route('/api/cancel-reservation', methods=['POST'])
def cancel_reservation():
    token = request.json.get('token')
    record = find_reservation_by_token(token)
    if not record: abort(404, "Nie znaleziono rezerwacji.")
    if not is_cancellation_allowed(record): abort(403, "Nie można odwołać rezerwacji.")
    try:
        # --- DODANO: Dodaj wolną kwotę przy odwołaniu opłaconej lekcji ---
        fields = record.get('fields', {})
        if fields.get('Oplacona') or fields.get('Status') == 'Opłacona':
            handle_paid_lesson_cancellation(record)
        # --- KONIEC DODAWANIA ---
        
        # --- DODANO POWIADOMIENIE ---
        if MESSENGER_PAGE_TOKEN:
            fields = record.get('fields', {})
            psid = fields.get('Klient')
            if psid:
                message_to_send = (
                    f"Twoja rezerwacja na lekcję z przedmiotu '{fields.get('Przedmiot')}' w dniu {fields.get('Data')} o {fields.get('Godzina')} "
                    f"została pomyślnie odwołana."
                )
                send_messenger_confirmation(psid, message_to_send, MESSENGER_PAGE_TOKEN)
        # --- KONIEC DODAWANIA ---
        
        fields = record.get('fields', {})
        if fields.get('JestTestowa', False):
            # Dla lekcji testowych zmieniamy tylko status, aby zablokować możliwość ponownej rezerwacji
            reservations_table.update(record['id'], {"Status": "Odwołana przez klienta"})
            logging.info(f"Lekcja testowa {record['id']} została oznaczona jako Odwołana przez klienta zamiast usunięcia.")
        else:
            reservations_table.delete(record['id'])
        
        # Powiadomienie korepetytora o anulowanej lekcji
        fields = record.get('fields', {})
        lesson_details = f"Przedmiot: {fields.get('Przedmiot')}, Data: {fields.get('Data')}, Godzina: {fields.get('Godzina')}, Klient: {fields.get('Klient')}"
        notify_tutor_about_lesson_change(fields.get('Korepetytor'), "cancelled", lesson_details)
        
        return jsonify({"message": "Rezerwacja została pomyślnie odwołana."})
    except Exception as e: abort(500, "Wystąpił błąd podczas odwoływania rezerwacji.")

@app.route('/api/reschedule-reservation', methods=['POST'])
def reschedule_reservation():
    try:
        data = request.json
        token = data.get('token')
        new_date = data.get('newDate')
        new_time = data.get('newTime')

        if not all([token, new_date, new_time]):
            abort(400, "Brak wymaganych danych.")

        original_record = find_reservation_by_token(token)
        if not original_record:
            abort(404, "Nie znaleziono oryginalnej rezerwacji do przeniesienia.")

        original_fields = original_record.get('fields', {})
        
        hours_limit = 6 if original_fields.get('JestTestowa', False) else 12
        if not is_cancellation_allowed(original_record) and original_fields.get('Status') != 'Przeniesiona':
            abort(403, f"Nie można zmienić terminu rezerwacji. Pozostało mniej niż {hours_limit} godzin.")

        tutor = original_fields.get('Korepetytor')
        
        formula_check = f"AND({{Korepetytor}} = '{tutor}', {{Data}} = '{new_date}', {{Godzina}} = '{new_time}')"
        print(f"DEBUG reschedule: checking formula: {formula_check}")
        existing = reservations_table.first(formula=formula_check)
        print(f"DEBUG reschedule: found existing: {existing}")
        if existing:
            return jsonify({"message": "Wybrany termin jest już zajęty. Proszę wybrać inny."}), 409
        
        new_date_obj = datetime.strptime(new_date, '%Y-%m-%d').date()
        day_of_week_name = WEEKDAY_MAP[new_date_obj.weekday()]
        cyclic_check_formula = f"AND({{Korepetytor}} = '{tutor}', {{DzienTygodnia}} = '{day_of_week_name}', {{Godzina}} = '{new_time}', {{Aktywna}}=1)"
        if cyclic_reservations_table.first(formula=cyclic_check_formula):
            return jsonify({"message": "Wybrany termin jest zajęty przez rezerwację stałą. Proszę wybrać inny."}), 409
            
        was_paid = original_fields.get('Oplacona', False)
        new_status = 'Oczekuje na płatność'

        # Sprawdzamy, czy oryginalna lekcja była opłacona (na podstawie checkboxa lub statusu)
        if was_paid or original_fields.get('Status') == 'Opłacona':
            was_paid = True
            new_status = 'Opłacona'
        
        new_reservation_data = {
            "Klient": original_fields.get('Klient'),
            "Korepetytor": tutor,
            "Data": new_date,
            "Godzina": new_time,
            "Przedmiot": original_fields.get('Przedmiot'),
            "Typ": original_fields.get('Typ', 'Jednorazowa'),
            "Status": new_status,
            "Oplacona": was_paid,
            "ManagementToken": str(uuid.uuid4()),
            "TypSzkoly": original_fields.get('TypSzkoly'),
            "Poziom": original_fields.get('Poziom'),
            "Klasa": original_fields.get('Klasa'),
            "TeamsLink": original_fields.get('TeamsLink')
        }
        reservations_table.create(new_reservation_data)

        reservations_table.update(original_record['id'], {"Status": "Przeniesiona (zakończona)"})
        
        # Powiadomienie korepetytora o przesuniętej lekcji
        lesson_details = f"Przedmiot: {original_fields.get('Przedmiot')}, Nowy termin: {new_date} {new_time}, Klient: {original_fields.get('Klient')}"
        notify_tutor_about_lesson_change(tutor, "rescheduled", lesson_details)
        
        if MESSENGER_PAGE_TOKEN:
            psid = original_fields.get('Klient')
            if psid:
                message_to_send = (
                    f"Termin Twojej lekcji został pomyślnie zmieniony.\n\n"
                    f"Nowy termin to: {new_date} o godzinie {new_time}."
                )
                send_messenger_confirmation(psid, message_to_send, MESSENGER_PAGE_TOKEN)
        
        return jsonify({"message": f"Termin został pomyślnie zmieniony na {new_date} o {new_time}."})

    except Exception as e:
        traceback.print_exc()
        abort(500, "Wystąpił błąd podczas zmiany terminu.")

@app.route('/api/get-lesson-by-token')
def get_lesson_by_token():
    """Pobiera szczegóły lekcji na podstawie tokenu zarządzania."""
    token = request.args.get('token')
    if not token:
        abort(400, "Brak tokenu.")
    
    record = find_reservation_by_token(token)
    if not record:
        abort(404, "Nie znaleziono lekcji.")
    
    return jsonify(record)

@app.route('/api/confirm-lesson', methods=['POST'])
def confirm_lesson():
    """Potwierdza lekcję testową."""
    data = request.json
    token = data.get('token')
    payment_option = data.get('paymentOption', 'later')
    
    if not token:
        abort(400, "Brak tokenu.")
    
    record = find_reservation_by_token(token)
    if not record:
        abort(404, "Nie znaleziono lekcji.")
    
    fields = record.get('fields', {})
    
    # Sprawdź czy to lekcja testowa
    if not fields.get('JestTestowa', False):
        abort(400, "Tylko lekcje testowe wymagają potwierdzenia.")
    
    # Sprawdź czy już potwierdzona
    if fields.get('confirmed', False):
        return jsonify({"success": True, "message": "Lekcja jest już potwierdzona."})
    
    # Sprawdź czas do lekcji - potwierdzenie dostępne tylko 24h przed
    lesson_datetime_str = f"{fields.get('Data')} {fields.get('Godzina')}"
    try:
        lesson_datetime = datetime.strptime(lesson_datetime_str, '%Y-%m-%d %H:%M')
        now = datetime.now()
        time_diff = lesson_datetime - now
        if time_diff.total_seconds() > 24 * 3600:  # Więcej niż 24h
            abort(400, "Potwierdzenie lekcji testowej jest dostępne tylko 24 godziny przed jej rozpoczęciem.")
    except ValueError:
        abort(400, "Nieprawidłowy format daty lub godziny.")
    
    # Potwierdź lekcję
    update_data = {"confirmed": True}
    
    # Jeśli płatność teraz, oznacz jako opłaconą
    if payment_option == 'now':
        update_data["Oplacona"] = True
        update_data["Status"] = "Opłacona"
    
    reservations_table.update(record['id'], update_data)
    
    # Wyślij potwierdzenie przez Messenger
    if MESSENGER_PAGE_TOKEN:
        client_id = fields.get('Klient')
        client_record = clients_table.first(formula=f"{{ClientID}} = '{client_id.strip()}'")
        if client_record:
            psid = client_record['fields'].get('ClientID')
            payment_text = "z obowiązkiem zapłaty teraz" if payment_option == 'now' else "z możliwością zapłaty później"
            message = f"""✅ Twoja lekcja testowa została potwierdzona {payment_text}!

📅 Data: {fields.get('Data')}
🕐 Godzina: {fields.get('Godzina')}
📚 Przedmiot: {fields.get('Przedmiot')}
👨‍🏫 Korepetytor: {fields.get('Korepetytor')}

Link do spotkania: {fields.get('TeamsLink')}"""
            send_messenger_confirmation(psid, message, MESSENGER_PAGE_TOKEN)
    
    return jsonify({"success": True, "message": "Lekcja została potwierdzona."})

@app.route('/api/cancel-lesson', methods=['POST'])
def cancel_lesson():
    """Odwołuje lekcję testową."""
    data = request.json
    token = data.get('token')
    
    if not token:
        abort(400, "Brak tokenu.")
    
    record = find_reservation_by_token(token)
    if not record:
        abort(404, "Nie znaleziono lekcji.")
    
    fields = record.get('fields', {})
    
    # Sprawdź czy to lekcja testowa
    if not fields.get('JestTestowa', False):
        abort(400, "Tylko lekcje testowe można odwoływać w ten sposób.")
    
    # Odwołaj lekcję
    reservations_table.update(record['id'], {"Status": "Odwołana przez klienta"})
    
    # Dodaj wolną kwotę jeśli była opłacona
    if fields.get('Oplacona'):
        handle_paid_lesson_cancellation(record)
    
    # Powiadom korepetytora
    lesson_details = f"Przedmiot: {fields.get('Przedmiot')}, Data: {fields.get('Data')}, Godzina: {fields.get('Godzina')}, Klient: {fields.get('Klient')}"
    notify_tutor_about_lesson_change(fields.get('Korepetytor'), "cancelled", lesson_details)
    
    # Wyślij wiadomość do klienta
    if MESSENGER_PAGE_TOKEN:
        client_id = fields.get('Klient')
        client_record = clients_table.first(formula=f"{{ClientID}} = '{client_id.strip()}'")
        if client_record:
            psid = client_record['fields'].get('ClientID')
            message = f"""❌ Twoja lekcja testowa została odwołana.

📅 Data: {fields.get('Data')}
🕐 Godzina: {fields.get('Godzina')}
📚 Przedmiot: {fields.get('Przedmiot')}"""
            send_messenger_confirmation(psid, message, MESSENGER_PAGE_TOKEN)
    
    return jsonify({"success": True, "message": "Lekcja została odwołana."})

# ===================================
# ENDPOINTY PANELU ADMINISTRACYJNEGO
# ===================================

@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    """Logowanie do panelu administracyjnego."""
    password = request.json.get('password')
    if password == ADMIN_PASSWORD:
        session['admin_logged_in'] = True
        return jsonify({"success": True, "message": "Zalogowano pomyślnie."})
    else:
        return jsonify({"success": False, "message": "Nieprawidłowe hasło."}), 401

@app.route('/api/admin/logout', methods=['POST'])
def admin_logout():
    """Wylogowanie z panelu administracyjnego."""
    session.pop('admin_logged_in', None)
    return jsonify({"success": True, "message": "Wylogowano."})

@app.route('/api/admin/check-auth', methods=['GET'])
def admin_check_auth():
    """Sprawdza czy użytkownik jest zalogowany."""
    is_logged_in = session.get('admin_logged_in', False)
    return jsonify({"authenticated": is_logged_in})

def require_admin():
    """Dekorator sprawdzający autoryzację admina."""
    if not session.get('admin_logged_in', False):
        abort(403, "Brak autoryzacji.")

@app.route('/api/admin/tables', methods=['GET'])
def get_all_tables():
    """Zwraca listę wszystkich tabel."""
    require_admin()
    tables = ['Klienci', 'Korepetytorzy', 'Rezerwacje', 'StaleRezerwacje']
    return jsonify({"tables": tables})

@app.route('/api/admin/table/<table_name>', methods=['GET'])
def get_table_data(table_name):
    """Pobiera wszystkie dane z danej tabeli."""
    require_admin()
    
    allowed_tables = ['Klienci', 'Korepetytorzy', 'Rezerwacje', 'StaleRezerwacje']
    if table_name not in allowed_tables:
        abort(404, "Tabela nie istnieje.")
    
    table = DatabaseTable(table_name)
    records = table.all()
    
    return jsonify({"records": records})

@app.route('/api/admin/table/<table_name>/record', methods=['POST'])
def create_table_record(table_name):
    """Tworzy nowy rekord w tabeli."""
    require_admin()
    
    allowed_tables = ['Klienci', 'Korepetytorzy', 'Rezerwacje', 'StaleRezerwacje']
    if table_name not in allowed_tables:
        abort(404, "Tabela nie istnieje.")
    
    fields = request.json.get('fields', {})
    if not fields:
        abort(400, "Brak danych do utworzenia rekordu.")
    
    table = DatabaseTable(table_name)
    try:
        new_record = table.create(fields)
        return jsonify({"success": True, "record": new_record})
    except Exception as e:
        traceback.print_exc()
        abort(500, f"Błąd podczas tworzenia rekordu: {str(e)}")

@app.route('/api/admin/table/<table_name>/record/<record_id>', methods=['GET'])
def get_table_record(table_name, record_id):
    """Pobiera pojedynczy rekord z tabeli."""
    require_admin()

    allowed_tables = ['Klienci', 'Korepetytorzy', 'Rezerwacje', 'StaleRezerwacje']
    if table_name not in allowed_tables:
        abort(404, "Tabela nie istnieje.")

    table = DatabaseTable(table_name)
    try:
        record = table.get(record_id)
        return jsonify(record)
    except Exception as e:
        traceback.print_exc()
        abort(500, f"Błąd podczas pobierania rekordu: {str(e)}")

@app.route('/api/admin/table/<table_name>/record/<record_id>', methods=['PUT'])
def update_table_record(table_name, record_id):
    """Aktualizuje rekord w tabeli."""
    require_admin()

    allowed_tables = ['Klienci', 'Korepetytorzy', 'Rezerwacje', 'StaleRezerwacje']
    if table_name not in allowed_tables:
        abort(404, "Tabela nie istnieje.")

    fields = request.json.get('fields', {})
    if not fields:
        abort(400, "Brak danych do aktualizacji.")

    table = DatabaseTable(table_name)
    try:
        updated_record = table.update(record_id, fields)
        return jsonify({"success": True, "record": updated_record})
    except Exception as e:
        traceback.print_exc()
        abort(500, f"Błąd podczas aktualizacji rekordu: {str(e)}")

@app.route('/api/admin/table/<table_name>/record/<record_id>', methods=['DELETE'])
def delete_table_record(table_name, record_id):
    """Usuwa rekord z tabeli."""
    require_admin()
    
    allowed_tables = ['Klienci', 'Korepetytorzy', 'Rezerwacje', 'StaleRezerwacje']
    if table_name not in allowed_tables:
        abort(404, "Tabela nie istnieje.")
    
    table = DatabaseTable(table_name)
    try:
        table.delete(record_id)
        return jsonify({"success": True, "message": "Rekord został usunięty."})
    except Exception as e:
        traceback.print_exc()
        abort(500, f"Błąd podczas usuwania rekordu: {str(e)}")

@app.route('/api/admin/manual-users', methods=['GET'])
def get_manual_users():
    require_admin()
    try:
        import os
        logging.info(f"DEBUG: CWD: {os.getcwd()}")
        conversation_store_dir = "../strona/conversation_store"
        logging.info(f"DEBUG: Sprawdzam katalog: {conversation_store_dir}, istnieje: {os.path.exists(conversation_store_dir)}")
        manual_users = []
        
        if os.path.exists(conversation_store_dir):
            logging.info(f"DEBUG: Znaleziono pliki: {[f for f in os.listdir(conversation_store_dir) if f.endswith('.json')]}")
            for filename in os.listdir(conversation_store_dir):
                if filename.endswith('.json'):
                    psid = filename[:-5]  # remove .json
                    filepath = os.path.join(conversation_store_dir, filename)
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            history_data = json.load(f)

                        # Sprawdź czy ostatni komunikat to POST_RESERVATION_MODE
                        last_msg_role = history_data[-1].get('role') if history_data else None
                        last_msg_text = history_data[-1].get('parts', [{}])[0].get('text') if history_data else None
                        logging.info(f"DEBUG: Plik {filename}, ostatni komunikat: role={last_msg_role}, text={last_msg_text}")
                        if history_data and any(msg.get('role') == 'model' and msg.get('parts', [{}])[0].get('text') == 'MANUAL_MODE' for msg in history_data):
                            # Pobierz nazwę klienta
                            client_record = clients_table.first(formula=f"{{ClientID}} = '{psid}'")
                            client_name = client_record['fields'].get('Imie', 'Nieznany') if client_record else 'Nieznany'
                            
                            # Oblicz liczbę nieodczytanych wiadomości
                            unread_count = sum(1 for msg in history_data if msg.get('role') == 'user' and not msg.get('read', False))

                            # Sprawdź czy ma nieodczytane wiadomości (ostatnia wiadomość od user)
                            has_unread = unread_count > 0

                            # Ostatnia wiadomość
                            last_msg = ''
                            for msg in reversed(history_data):
                                if msg.get('parts'):
                                    last_msg = msg['parts'][0].get('text', '')
                                    if last_msg:
                                        break

                            # Pobierz dodatkowe informacje
                            free_amount = get_free_amount(psid)
                            full_name = f"{client_record['fields'].get('Imie', '')} {client_record['fields'].get('Nazwisko', '')}".strip() if client_record else 'Nieznany'

                            # Lista rezerwacji z statusami
                            reservations = []
                            client_reservations = reservations_table.all(formula=f"{{Klient}} = '{psid}'")
                            for res in client_reservations:
                                fields = res.get('fields', {})
                                statuses = []
                                if fields.get('confirmed'):
                                    statuses.append('potwierdzona')
                                if fields.get('Oplacona') or fields.get('Status') == 'Opłacona':
                                    statuses.append('opłacona')
                                if fields.get('Status') == 'Przeniesiona (zakończona)':
                                    statuses.append('odbyta')
                                if statuses:  # Dodaj tylko jeśli ma przynajmniej jeden status
                                    reservations.append({
                                        'date': fields.get('Data'),
                                        'time': fields.get('Godzina'),
                                        'subject': fields.get('Przedmiot'),
                                        'statuses': statuses
                                    })

                            manual_users.append({
                                'psid': psid,
                                'name': client_name,
                                'lastMessage': last_msg[:100] + '...' if len(last_msg) > 100 else last_msg,
                                'hasUnread': has_unread,
                                'unreadCount': unread_count,
                                'freeAmount': free_amount,
                                'studentParentName': full_name,
                                'reservations': reservations
                            })
                    except Exception as e:
                        logging.error(f"Błąd przetwarzania pliku {filename}: {e}")

        logging.info(f"DEBUG: Zwrócono {len(manual_users)} użytkowników w trybie ręcznym")

        return jsonify({'users': manual_users})
    except Exception as e:
        logging.error(f"Błąd w get_manual_users: {e}", exc_info=True)
        return jsonify({'users': []}), 500

@app.route('/api/admin/user-chat/<psid>', methods=['GET'])
def get_user_chat(psid):
    require_admin()
    try:
        from bot import load_history  # Import z bot.py
        history = load_history(psid)

        messages = []
        for full_i, msg in enumerate(history):
            if msg.parts:
                text = msg.parts[0].text
                if text in ['MANUAL_MODE', 'POST_RESERVATION_MODE']:
                    continue  # Pomiń komunikaty trybu
                role = 'user' if msg.role == 'user' else 'bot'
                read_status = getattr(msg, 'read', False) if role == 'user' else True
                messages.append({'role': role, 'text': text, 'read': read_status, 'index': len(messages), 'fullIndex': full_i})

        return jsonify({'messages': messages})
    except Exception as e:
        logging.error(f"Błąd w get_user_chat: {e}", exc_info=True)
        return jsonify({'messages': []}), 500

@app.route('/api/admin/send-message', methods=['POST'])
def admin_send_message():
    require_admin()
    try:
        data = request.json
        psid = data.get('psid')
        message = data.get('message')

        if not psid or not message:
            return jsonify({'error': 'Brak PSID lub wiadomości'}), 400

        if not MESSENGER_PAGE_TOKEN:
            return jsonify({'error': 'Brak tokena strony Messenger'}), 500

        # Wyślij wiadomość
        params = {"access_token": MESSENGER_PAGE_TOKEN}
        payload = {"recipient": {"id": psid}, "message": {"text": message}, "messaging_type": "MESSAGE_TAG", "tag": "POST_PURCHASE_UPDATE"}

        response = requests.post("https://graph.facebook.com/v19.0/me/messages", params=params, json=payload, timeout=30)
        response.raise_for_status()

        # Dodaj wiadomość do historii i oznacz wszystkie wiadomości użytkownika jako przeczytane
        from bot import load_history, save_history  # Import z bot.py
        history = load_history(psid)
        from vertexai.generative_models import Content, Part
        history.append(Content(role="model", parts=[Part.from_text(message)]))
        # Oznacz wszystkie wiadomości użytkownika jako przeczytane
        for msg in history:
            if msg.role == 'user':
                msg.read = True
        # Jeśli ostatni komunikat to POST_RESERVATION_MODE, dodaj go ponownie, aby utrzymać tryb
        if history and len(history) > 1 and history[-2].parts[0].text == 'POST_RESERVATION_MODE':
            history.append(Content(role="model", parts=[Part.from_text('POST_RESERVATION_MODE')]))
        save_history(psid, history)

        return jsonify({'success': True})
    except Exception as e:
        logging.error(f"Błąd w admin_send_message: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/end-manual/<psid>', methods=['POST'])
def end_manual_mode(psid):
    require_admin()
    try:
        from bot import load_history, save_history  # Import z bot.py
        from vertexai.generative_models import Part
        history = load_history(psid)
        # Bezpośrednia zamiana w pliku JSON dla pewności
        import os
        filepath = os.path.join(os.path.dirname(__file__), "../strona/conversation_store", f"{psid}.json")
        logging.info(f"Zamieniam MANUAL_MODE na POST_RESERVATION_MODE w pliku: {filepath}")
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            original_content = content
            content = content.replace('"MANUAL_MODE"', '"POST_RESERVATION_MODE"')
            if content != original_content:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(content)
                logging.info("Zamiana wykonana w pliku.")
            else:
                logging.info("Nie znaleziono MANUAL_MODE do zamiany.")
        except Exception as e:
            logging.error(f"Błąd podczas bezpośredniej zamiany w pliku: {e}")

        # Wyślij wiadomość o zakończeniu pomocy człowieka
        if MESSENGER_PAGE_TOKEN:
            message = "Pomoc człowieka została zakończona. Jeśli potrzebujesz dalszej pomocy, napisz 'pomoc'."
            send_messenger_confirmation(psid, message, MESSENGER_PAGE_TOKEN)

        return jsonify({'success': True})
    except Exception as e:
        logging.error(f"Błąd w end_manual_mode: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/facebook-stats', methods=['GET'])
def get_facebook_stats():
    require_admin()
    try:
        response = requests.get(EXTERNAL_STATS_URL)
        response.raise_for_status()
        data = response.json()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/admin/facebook-hourly-stats', methods=['GET'])
def get_facebook_hourly_stats():
    """Pobiera statystyki godzinowe z zewnętrznego serwera statystyk."""
    require_admin()
    try:
        # Tworzymy URL do serwera statystyk, podmieniając końcówkę
        external_url = EXTERNAL_STATS_URL.replace('/api/facebook-stats', '/api/facebook-hourly-stats')
        
        # Pobieramy dane
        response = requests.get(external_url, timeout=5)
        response.raise_for_status()
        
        return jsonify(response.json())
    except Exception as e:
        logging.error(f"Błąd pobierania statystyk godzinowych: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/admin/facebook-errors', methods=['GET'])
def get_facebook_errors():
    require_admin()
    try:
        # Fetch from external server
        external_errors_url = EXTERNAL_STATS_URL.replace('/api/facebook-stats', '/api/facebook-errors')
        response = requests.get(external_errors_url)
        response.raise_for_status()
        data = response.json()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/admin/download-error', methods=['GET'])
def download_error():
    require_admin()
    try:
        filename = request.args.get('file')
        if not filename:
            abort(400, "Brak parametru file.")

        # Fetch from external server
        external_download_url = EXTERNAL_STATS_URL.replace('/api/facebook-stats', '/api/download-error') + f'?file={filename}'
        response = requests.get(external_download_url)
        response.raise_for_status()

        # Return the file content
        from flask import Response
        return Response(response.content, mimetype=response.headers.get('content-type'), headers={"Content-Disposition": response.headers.get('content-disposition', f'attachment; filename={filename}')})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/admin/mark-read/<psid>', methods=['POST'])
def mark_messages_read(psid):
    require_admin()
    try:
        data = request.json
        up_to_full_index = data.get('upToFullIndex')
        from bot import load_history, save_history
        history = load_history(psid)
        if up_to_full_index is not None:
            for i in range(min(up_to_full_index + 1, len(history))):
                if history[i].role == 'user':
                    history[i].read = True
        else:
            # If no index, mark all user messages as read
            for msg in history:
                if msg.role == 'user':
                    msg.read = True
        save_history(psid, history)
        return jsonify({'success': True})
    except Exception as e:
        logging.error(f"Błąd w mark_messages_read: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/user-details/<psid>', methods=['GET'])
def get_user_details(psid):
    require_admin()
    try:
        # Pobierz szczegóły klienta
        client_record = clients_table.first(formula=f"{{ClientID}} = '{psid}'")
        client_name = client_record['fields'].get('Imie', 'Nieznany') if client_record else 'Nieznany'
        full_name = f"{client_record['fields'].get('Imie', '')} {client_record['fields'].get('Nazwisko', '')}".strip() if client_record else 'Nieznany'

        # Pobierz wolną kwotę
        free_amount = get_free_amount(psid)

        # Lista rezerwacji z statusami
        reservations = []
        client_reservations = reservations_table.all(formula=f"{{Klient}} = '{psid}'")
        for res in client_reservations:
            fields = res.get('fields', {})
            statuses = []
            if fields.get('confirmed'):
                statuses.append('potwierdzona')
            if fields.get('Oplacona') or fields.get('Status') == 'Opłacona':
                statuses.append('opłacona')
            if fields.get('Status') == 'Przeniesiona (zakończona)':
                statuses.append('odbyta')
            if statuses:  # Dodaj tylko jeśli ma przynajmniej jeden status
                reservations.append({
                    'date': fields.get('Data'),
                    'time': fields.get('Godzina'),
                    'subject': fields.get('Przedmiot'),
                    'statuses': statuses
                })

        # Pobierz historię czatu
        from bot import load_history  # Import z bot.py
        history = load_history(psid)

        messages = []
        has_unread = False
        last_msg = ''
        for full_i, msg in enumerate(history):
            if msg.parts:
                text = msg.parts[0].text
                if text in ['MANUAL_MODE', 'POST_RESERVATION_MODE']:
                    continue
                role = 'user' if msg.role == 'user' else 'bot'
                read_status = getattr(msg, 'read', False) if role == 'user' else True
                messages.append({'role': role, 'text': text, 'read': read_status, 'fullIndex': full_i})

        # Sprawdź nieodczytane wiadomości (ostatnia wiadomość od user, ignorując komunikaty trybu)
        filtered_history = [msg for msg in history if not (msg.parts and msg.parts[0].text in ['MANUAL_MODE', 'POST_RESERVATION_MODE'])]
        if filtered_history and filtered_history[-1].role == 'user':
            has_unread = True

        # Pobierz ostatni komunikat
        for msg in reversed(history):
            if msg.parts:
                text = msg.parts[0].text
                if text and text not in ['MANUAL_MODE', 'POST_RESERVATION_MODE']:
                    last_msg = text
                    break

        # Sprawdź czy tryb ręczny jest aktywny
        manual_mode_active = any(msg for msg in history if msg.role == 'model' and msg.parts and msg.parts[0].text == 'MANUAL_MODE')

        # Szczegóły użytkownika
        user_details = {
            'psid': psid,
            'name': client_name,
            'lastMessage': last_msg[:100] + '...' if len(last_msg) > 100 else last_msg,
            'hasUnread': has_unread,
            'freeAmount': free_amount,
            'studentParentName': full_name,
            'reservations': reservations,
            'manualModeActive': manual_mode_active
        }

        return jsonify({
            'user': user_details,
            'messages': messages
        })
    except Exception as e:
        logging.error(f"Błąd w get_user_details: {e}", exc_info=True)
        return jsonify({'error': 'Błąd serwera'}), 500

@app.route('/api/admin/enable-manual/<psid>', methods=['POST'])
def enable_manual_mode(psid):
    """Włącza tryb ręczny dla użytkownika – bot zapisuje wiadomości, ale nie odpowiada."""
    require_admin()
    try:
        history = load_history(psid)
        # Sprawdź, czy tryb ręczny już jest aktywny
        if any(msg.role == 'model' and msg.parts[0].text == 'MANUAL_MODE' for msg in history):
            return jsonify({"message": "Tryb ręczny już aktywny."})

        # Dodaj znacznik MANUAL_MODE jako wiadomość modelu
        history.append(Content(role="model", parts=[Part.from_text('MANUAL_MODE')]))
        save_history(psid, history)

        logging.info(f"Tryb ręczny włączony dla {psid}")
        return jsonify({"success": True, "message": "Tryb ręczny włączony."})
    except Exception as e:
        logging.error(f"Błąd włączania trybu ręcznego dla {psid}: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route('/api/admin/send-reservation-link', methods=['POST'])
def send_reservation_link():
    """Wysyła do użytkownika link rezerwacji i przełącza w tryb po-rezerwacyjny."""
    require_admin()
    try:
        data = request.json
        psid = data.get('psid')
        if not psid:
            abort(400, "Brak PSID")

        page_token = MESSENGER_PAGE_TOKEN
        if not page_token:
            abort(500, "Brak tokena Messenger")

        # Utwórz lub znajdź klienta w bazie (potrzebny do linku)
        client_id = create_or_find_client_in_airtable(psid, page_token, clients_table)
        if not client_id:
            abort(500, "Nie udało się utworzyć/znaleźć klienta")

        # Wygeneruj link rezerwacji
        reservation_link = f"https://zakręcone-korepetycje.pl/rezerwacja-testowa.html?clientID={client_id}"
        final_message = (f"Utworzyłem dla Państwa osobisty link do rezerwacji.\n\n"
                         f"{reservation_link}\n\n"
                         f"Lekcję testową można wyjątkowo opłacić po połączeniu z korepetytorem.")

        # Wyślij wiadomość przez Messenger
        send_messenger_confirmation(psid, final_message, page_token)

        # Załaduj historię i dodaj wysłaną wiadomość oraz znacznik POST_RESERVATION_MODE
        history = load_history(psid)
        history.append(Content(role="model", parts=[Part.from_text(final_message)]))

        # Usuń ewentualny znacznik MANUAL_MODE (jeśli był)
        history = [msg for msg in history if not (msg.role == 'model' and msg.parts[0].text == 'MANUAL_MODE')]

        # Dodaj znacznik trybu po-rezerwacyjnego
        history.append(Content(role="model", parts=[Part.from_text('POST_RESERVATION_MODE')]))
        save_history(psid, history)

        return jsonify({"success": True, "message": "Link wysłany."})
    except Exception as e:
        logging.error(f"Błąd wysyłania linku rezerwacji: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route('/api/admin/reset-test-user', methods=['POST'])
def reset_test_user():
    require_admin()
    try:
        client_id = '9159589357480361'  # Hardcoded test user ID

        # Remove all confirmation reminders for the client
        if scheduler:
            # Get all reservations for the client
            client_reservations = reservations_table.all(formula=f"{{Klient}} = '{client_id}'")
            tokens = [res['fields'].get('ManagementToken') for res in client_reservations if res['fields'].get('ManagementToken')]
            
            jobs = scheduler.get_jobs()
            for job in jobs:
                if 'confirmation_reminder' in job.id:
                    token = job.id.replace('confirmation_reminder_', '')
                    if token in tokens:
                        scheduler.remove_job(job.id)
                        logging.info(f"Usunięto zadanie przypomnienia: {job.id}")

        # Delete the conversation file
        conversation_file = os.path.join(os.path.dirname(__file__), "../strona/conversation_store", f"{client_id}.json")
        if os.path.exists(conversation_file):
            os.remove(conversation_file)
            logging.info(f"Usunięto plik konwersacji: {conversation_file}")
        else:
            logging.info(f"Plik konwersacji nie istnieje: {conversation_file}")

        return jsonify({"message": "Użytkownik testowy został zresetowany."})
    except Exception as e:
        logging.error(f"Błąd w reset_test_user: {e}", exc_info=True)
        return jsonify({'error': 'Błąd serwera'}), 500

@app.route('/api/update-tutor-weekly-limit', methods=['POST'])
def update_tutor_weekly_limit():
    """Aktualizuje limit godzin tygodniowo dla korepetytora."""
    try:
        data = request.json
        tutor_id = data.get('tutorID')
        weekly_limit = data.get('weeklyLimit')  # None lub int
        
        if not tutor_id:
            abort(400, "Brak tutorID.")
        
        # Weryfikacja korepetytora
        tutor_record = tutors_table.first(formula=f"{{TutorID}} = '{tutor_id.strip()}'")
        if not tutor_record:
            abort(404, "Nie znaleziono korepetytora.")
        
        # Walidacja limitu (0-168 godzin lub None)
        if weekly_limit is not None:
            if not isinstance(weekly_limit, int) or weekly_limit < 0 or weekly_limit > 168:
                abort(400, "Limit musi być liczbą od 0 do 168 lub null (brak limitu).")
        
        # Aktualizacja
        tutors_table.update(tutor_record['id'], {'LimitGodzinTygodniowo': weekly_limit})
        
        return jsonify({
            "message": "Limit godzin został zaktualizowany.",
            "weeklyLimit": weekly_limit
        })
        
    except Exception as e:
        traceback.print_exc()
        abort(500, "Błąd podczas aktualizacji limitu godzin.")

@app.route('/api/get-tutor-weekly-hours')
def get_tutor_weekly_hours():
    """Zwraca aktualny stan godzin korepetytora w bieżącym tygodniu."""
    try:
        tutor_name = request.args.get('tutorName')
        if not tutor_name:
            abort(400, "Brak tutorName.")
        
        # Pobierz limit
        tutor_record = tutors_table.first(formula=f"{{ImieNazwisko}} = '{tutor_name}'")
        if not tutor_record:
            abort(404, "Nie znaleziono korepetytora.")
        
        tutor_limit = tutor_record['fields'].get('LimitGodzinTygodniowo')
        
        # Na razie zwracamy uproszczone dane - TODO: zaimplementować właściwe obliczenia
        current_hours = 0  # Tymczasowo 0
        
        return jsonify({
            "currentHours": current_hours,
            "weeklyLimit": tutor_limit,
            "hasLimit": tutor_limit is not None
        })
        
    except Exception as e:
        traceback.print_exc()
        abort(500, "Błąd podczas pobierania danych o godzinach.")

@app.route('/api/send-reminder-message', methods=['POST'])
def send_reminder_message():
    try:
        data = request.json
        record_id = data.get('record_id')

        if not record_id:
            abort(400, "Brak record_id.")

        lesson_record = reservations_table.get(record_id)
        if not lesson_record:
            abort(404, "Nie znaleziono lekcji.")

        fields = lesson_record.get('fields', {})
        client_psid = fields.get('Klient')
        tutor_name = fields.get('Korepetytor')
        
        if not client_psid or not tutor_name:
            abort(400, "Brak danych klienta lub korepetytora w rekordzie lekcji.")

        if not MESSENGER_PAGE_TOKEN:
            logging.error("MESSENGER: Nie można wysłać przypomnienia - brak tokena strony.")
            abort(500, "Błąd serwera: brak konfiguracji do wysyłania wiadomości.")
            
        tutor_name_encoded = urllib.parse.quote(tutor_name)
        # Assuming the profile link can be constructed this way.
        profile_link = f"https://zakręcone-korepetycje.pl/index.html?tutor={tutor_name_encoded}"
        
        message = (
            f"Nasz korepetytor ({tutor_name}) poprosił nas, aby przypomnieć o skontaktowaniu się z nim przez Messengera w celu omówienia szczegółów zajęć.\n\n"
            f"Link do profilu: {profile_link}"
        )

        send_messenger_confirmation(client_psid, message, MESSENGER_PAGE_TOKEN)
        
        return jsonify({"message": "Wiadomość przypominająca została wysłana."})

    except Exception as e:
        traceback.print_exc()
        abort(500, f"Wystąpił błąd serwera: {str(e)}")

@app.route('/api/admin/facebook-status-screenshots', methods=['GET'])
def get_facebook_status_screenshots_proxy():
    require_admin()
    try:
        # Zamieniamy końcówkę URL na odpowiednią dla statusów
        external_url = EXTERNAL_STATS_URL.replace('/api/facebook-stats', '/api/facebook-status-screenshots')
        response = requests.get(external_url, timeout=5)
        response.raise_for_status()
        return jsonify(response.json())
    except Exception as e:
        logging.error(f"Błąd pobierania listy statusów: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/admin/download-status-screenshot', methods=['GET'])
def download_status_screenshot_proxy():
    require_admin()
    try:
        filename = request.args.get('file')
        if not filename:
            abort(400, "Brak parametru file.")

        # Budujemy URL do pobrania z zewnętrznego serwera
        external_url = EXTERNAL_STATS_URL.replace('/api/facebook-stats', '/api/download-status-screenshot') + f'?file={filename}'
        
        # Pobieramy plik z maszyny A
        response = requests.get(external_url, stream=True, timeout=10)
        response.raise_for_status()

        # Przekazujemy plik do przeglądarki
        from flask import Response
        return Response(
            response.content,
            mimetype=response.headers.get('content-type'),
            headers={"Content-Disposition": f'attachment; filename={filename}'}
        )
    except Exception as e:
        logging.error(f"Błąd pobierania pliku statusu: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/<path:path>')
def catch_all(path):
    if path.startswith('api/'):
        abort(404)
    file_path = path + '.html' if '.' not in path else path
    try:
        return send_from_directory('.', file_path)
    except FileNotFoundError:
        abort(404)

@app.route('/stats')
def stats():
    try:
        import sys
        sys.path.append('/home/nikodnaj/strona')
        from database_stats import get_stats
        stats_data = get_stats()
        html = "<h1>Statystyki komentarzy Facebook</h1><table border='1'><tr><th>Data</th><th>Przesłane</th><th>Odrzucone</th><th>Oczekuje</th><th>Ostatni komentarz</th></tr>"
        for stat in stats_data:
            html += f"<tr><td>{stat['Data']}</td><td>{stat['Przeslane']}</td><td>{stat['Odrzucone']}</td><td>{stat['Oczekuje']}</td><td>{stat['LastCommentTime'] or 'Brak'}</td></tr>"
        html += "</table>"
        return html
    except Exception as e:
        return f"Błąd: {e}"

if __name__ == '__main__':
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=check_and_cancel_unpaid_lessons, trigger="interval", seconds=60)
    # Zmieniamy na 5 minut (lub nawet minutes=1 dla szybszej reakcji)
    scheduler.add_job(func=check_unconfirmed_lessons, trigger="interval", minutes=5)
    scheduler.start()
    # Zarejestruj funkcję, która zamknie scheduler przy wyjściu z aplikacji
    atexit.register(lambda: scheduler.shutdown())
    print("--- Uruchamianie serwera na porcie 8080 ---")
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=False)