import os
import json
import uuid
import traceback
import threading
from flask import Flask, jsonify, request, abort
from flask_cors import CORS
from pyairtable import Api
from datetime import datetime, timedelta
from datetime import time as dt_time
import time
import requests
from apscheduler.schedulers.background import BackgroundScheduler
import pytz
import atexit
import logging 
import pickle
from io import BytesIO
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.common.exceptions import TimeoutException, WebDriverException, NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from PIL import Image
import imagehash

# --- Konfiguracja ---
PATH_DO_GOOGLE_CHROME = "/usr/bin/google-chrome"
PATH_DO_RECZNEGO_CHROMEDRIVER = "/usr/local/bin/chromedriver"
COOKIES_FILE = "/var/www/korki/cookies.pkl"
HASH_DIFFERENCE_THRESHOLD = 10

AIRTABLE_API_KEY = "patcSdupvwJebjFDo.7e15a93930d15261989844687bcb15ac5c08c84a29920c7646760bc6f416146d"
AIRTABLE_BASE_ID = "appTjrMTVhYBZDPw9"
TUTORS_TABLE_NAME = "Korepetytorzy"
RESERVATIONS_TABLE_NAME = "Rezerwacje"
CLIENTS_TABLE_NAME = "Klienci"
CYCLIC_RESERVATIONS_TABLE_NAME = "StaleRezerwacje"

MS_TENANT_ID = "58928953-69aa-49da-b96c-100396a3caeb"
MS_CLIENT_ID = "8bf9be92-1805-456a-9162-ffc7cda3b794"
MS_CLIENT_SECRET = "MQ~8Q~VD9sI3aB19_Drwqndp4j5V_WAjmwK3yaQD"
MEETING_ORGANIZER_USER_ID = "8cf07b71-d305-4450-9b70-64cb5be6ecef"

api = Api(AIRTABLE_API_KEY)
tutors_table = api.table(AIRTABLE_BASE_ID, TUTORS_TABLE_NAME)
reservations_table = api.table(AIRTABLE_BASE_ID, RESERVATIONS_TABLE_NAME)
clients_table = api.table(AIRTABLE_BASE_ID, CLIENTS_TABLE_NAME)
cyclic_reservations_table = api.table(AIRTABLE_BASE_ID, CYCLIC_RESERVATIONS_TABLE_NAME)

MESSENGER_PAGE_TOKEN = None
MESSENGER_PAGE_ID = "638454406015018" # ID strony, z której wysyłamy

try:
    # Podajemy PEŁNĄ ścieżkę do pliku konfiguracyjnego bota
    with open('/home/nikodnaj3/strona/config.json', 'r', encoding='utf-8') as f:
        bot_config = json.load(f)
        MESSENGER_PAGE_TOKEN = bot_config.get("PAGE_CONFIG", {}).get(MESSENGER_PAGE_ID, {}).get("token")
    if MESSENGER_PAGE_TOKEN:
        print("--- MESSENGER: Pomyślnie załadowano token dostępu do strony.")
    else:
        print(f"!!! MESSENGER: OSTRZEŻENIE - Nie znaleziono tokena dla strony {MESSENGER_PAGE_ID} w config.json.")
except Exception as e:
    print(f"!!! MESSENGER: OSTRZEŻENIE - Nie udało się wczytać pliku config.json bota: {e}")

app = Flask(__name__)
CORS(app)

WEEKDAY_MAP = { 0: "Poniedziałek", 1: "Wtorek", 2: "Środa", 3: "Czwartek", 4: "Piątek", 5: "Sobota", 6: "Niedziela" }
LEVEL_MAPPING = {
    "szkola_podstawowa": ["podstawowka"], "liceum_podstawowy": ["liceum_podstawa"],
    "technikum_podstawowy": ["liceum_podstawa"], "liceum_rozszerzony": ["liceum_rozszerzenie"],
    "technikum_rozszerzony": ["liceum_rozszerzenie"]
}
last_fetched_schedule = {}

# --- Funkcje pomocnicze ---
# ================================================
# === FUNKCJE WYSZUKIWARKI PROFILI FACEBOOK ====
# ================================================

def calculate_image_hash(image_source):
    try:
        image = Image.open(BytesIO(image_source))
        return imagehash.phash(image)
    except Exception as e:
        print(f"BŁĄD: Nie można przetworzyć obrazu: {e}")
        return None

def load_cookies(driver, file_path):
    if not os.path.exists(file_path): return False
    try:
        with open(file_path, 'rb') as file: cookies = pickle.load(file)
        if not cookies: return False
        driver.get("https://www.facebook.com"); time.sleep(1)
        for cookie in cookies:
            if 'expiry' in cookie: cookie['expiry'] = int(cookie['expiry'])
            driver.add_cookie(cookie)
        driver.refresh(); time.sleep(2)
        return True
    except: return False

def initialize_driver_and_login():
    print("\n" + "="*50)
    print("--- ROZPOCZYNAM TEST LOGOWANIA (z backend.py) ---")
    print("="*50)
    
    driver = None
    try:
        # --- Krok 1: Weryfikacja plików z dodatkowymi logami ---
        print("\n[Krok 1/5] Weryfikacja plików i uprawnień...")
        
        # Sprawdzamy, gdzie skrypt jest aktualnie uruchomiony
        current_working_dir = os.getcwd()
        print(f"      -> Bieżący katalog roboczy (CWD): {current_working_dir}")

        # Sprawdzamy ścieżkę do pliku cookies
        print(f"      -> Oczekiwana ścieżka do ciasteczek: {COOKIES_FILE}")

        if not os.path.exists(COOKIES_FILE):
            print(f"!!! KRYTYCZNY BŁĄD: Plik {COOKIES_FILE} NIE ISTNIEJE z perspektywy skryptu.")
            # Sprawdźmy, czy plik istnieje, ale może mamy problem z uprawnieniami do katalogu nadrzędnego
            parent_dir = os.path.dirname(COOKIES_FILE)
            print(f"      -> Sprawdzam zawartość katalogu nadrzędnego: {parent_dir}")
            try:
                dir_contents = os.listdir(parent_dir)
                print(f"      -> Zawartość katalogu: {dir_contents}")
                if "cookies.pkl" in dir_contents:
                    print("      -> UWAGA: Plik 'cookies.pkl' jest w katalogu, ale os.path.exists() go nie widzi. To może być problem z uprawnieniami.")
            except Exception as e:
                print(f"      -> BŁĄD: Nie można odczytać zawartości katalogu {parent_dir}: {e}")
            return None # Zakończ, jeśli pliku nie ma
        
        print(f"      -> OK: Plik {COOKIES_FILE} istnieje.")

        # Sprawdzamy, czy mamy uprawnienia do odczytu pliku
        if not os.access(COOKIES_FILE, os.R_OK):
            print(f"!!! KRYTYCZNY BŁĄD: Brak uprawnień do ODCZYTU pliku {COOKIES_FILE}.")
            # Spróbujmy wyświetlić uprawnienia
            try:
                stat_info = os.stat(COOKIES_FILE)
                print(f"      -> Uprawnienia pliku: {oct(stat_info.st_mode)}")
                print(f"      -> Właściciel (UID): {stat_info.st_uid}, Grupa (GID): {stat_info.st_gid}")
            except Exception as e:
                print(f"      -> Nie można odczytać statystyk pliku: {e}")
            return None # Zakończ, jeśli nie ma uprawnień

        print(f"      -> OK: Skrypt ma uprawnienia do odczytu pliku {COOKIES_FILE}.")

        # --- Krok 2: Inicjalizacja przeglądarki (bez zmian) ---
        print("\n[Krok 2/5] Uruchamianie przeglądarki...")
        service = ChromeService(executable_path=PATH_DO_RECZNEGO_CHROMEDRIVER)
        options = webdriver.ChromeOptions()
        options.binary_location = PATH_DO_GOOGLE_CHROME
        options.add_argument("--headless")
        options.add_argument("--disable-notifications")
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        driver = webdriver.Chrome(service=service, options=options)
        print("      -> Sukces. Przeglądarka uruchomiona.")
        
        # --- Krok 3: Ładowanie ciasteczek (z dodatkową obsługą błędów) ---
        print(f"\n[Krok 3/5] Próba załadowania ciasteczek z pliku {COOKIES_FILE}...")
        driver.get("https://www.facebook.com"); time.sleep(1)

        try:
            with open(COOKIES_FILE, 'rb') as file:
                cookies = pickle.load(file)
            
            if not cookies:
                print("!!! BŁĄD: Plik z ciasteczkami jest pusty.")
                driver.quit()
                return None

            for cookie in cookies:
                if 'expiry' in cookie:
                    cookie['expiry'] = int(cookie['expiry'])
                driver.add_cookie(cookie)
            
            print("      -> Sukces. Ciasteczka dodane do przeglądarki.")
        
        except (pickle.UnpicklingError, EOFError) as e:
            print(f"!!! KRYTYCZNY BŁĄD: Plik {COOKIES_FILE} jest uszkodzony lub w nieprawidłowym formacie: {e}")
            driver.quit()
            return None
        
        # --- Krok 4: Odświeżenie i weryfikacja ---
        print("\n[Krok 4/5] Odświeżanie strony i weryfikacja logowania...")
        driver.refresh()
        time.sleep(5)
        
        wait = WebDriverWait(driver, 15)
        search_input_xpath = "//input[@aria-label='Szukaj na Facebooku']"
        
        print("      -> Oczekuję na pojawienie się pola 'Szukaj na Facebooku'...")
        wait.until(EC.presence_of_element_located((By.XPATH, search_input_xpath)))
        
        print("\nSUKCES: Sesja przeglądarki jest aktywna i jesteś zalogowany!")
        return driver

    except Exception as e:
        print("\n!!! WYSTĄPIŁ NIESPODZIEWANY BŁĄD w initialize_driver_and_login !!!")
        traceback.print_exc()
        return None
    finally:
        print("--- Zakończono proces inicjalizacji przeglądarki (w ramach bloku finally). ---")

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

        # Zaktualizuj rekord, ustawiając go jako nieaktywny (zamiast usuwać)
        cyclic_reservations_table.update(record_to_cancel['id'], {"Aktywna": False})
        
        print(f"ANULOWANO STAŁY TERMIN: ID {record_to_cancel['id']} został oznaczony jako nieaktywny.")

        return jsonify({"message": "Stały termin został pomyślnie odwołany."})

    except Exception as e:
        traceback.print_exc()
        abort(500, "Wystąpił błąd serwera podczas anulowania stałego terminu.")


def find_profile_and_update_airtable(record_id, first_name, last_name, profile_pic_url):
    """Główna funkcja, która wykonuje cały proces wyszukiwania dla jednego klienta, robiąc zrzuty ekranu."""
    driver = None
    # Zdefiniuj ścieżkę do zapisywania screenshotów
    SCREENSHOTS_DIR = os.path.join(os.getcwd(), "screenshots")
    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
    
    print("\n" + "="*60)
    print(f"--- WYSZUKIWARKA: Start dla klienta '{first_name} {last_name}' (ID rekordu: {record_id}) ---")
    print(f"      -> Zrzuty ekranu będą zapisywane w: {SCREENSHOTS_DIR}")
    print("="*60)

    try:
        # ... (Krok 1: Pobieranie i przetwarzanie zdjęcia - bez zmian) ...
        print("[1/6] Pobieranie docelowego zdjęcia profilowego...")
        response = requests.get(profile_pic_url)
        if response.status_code != 200:
            clients_table.update(record_id, {'LINK': 'BŁĄD - Nie można pobrać zdjęcia'})
            return
        target_image_hash = calculate_image_hash(response.content)
        if not target_image_hash:
            clients_table.update(record_id, {'LINK': 'BŁĄD - Nie można przetworzyć zdjęcia'})
            return
        print(f"      -> Sukces. Hash docelowy: {target_image_hash}")

        # --- Krok 2: Uruchomienie przeglądarki ---
        print("[2/6] Inicjalizacja przeglądarki...")
        driver = initialize_driver_and_login()
        if not driver:
            clients_table.update(record_id, {'LINK': 'BŁĄD - Inicjalizacja przeglądarki nieudana'})
            return
        print("      -> Sukces. Przeglądarka gotowa.")
        
        # --- Zrzut ekranu #1: Po zalogowaniu ---
        driver.save_screenshot(os.path.join(SCREENSHOTS_DIR, "1_po_zalogowaniu.png"))
        print("      -> ZROBIONO ZRZUT EKRANU: 1_po_zalogowaniu.png")

        # --- Krok 3: Wyszukanie frazy na Facebooku ---
        search_name = f"{first_name} {last_name}"
        print(f"[3/6] Wyszukiwanie frazy: '{search_name}'...")
        wait = WebDriverWait(driver, 20)
        driver.get("https://www.facebook.com")
        time.sleep(3)
        
        search_input = wait.until(EC.element_to_be_clickable((By.XPATH, "//input[@aria-label='Szukaj na Facebooku']")))
        search_input.click(); search_input.clear(); time.sleep(0.5)
        search_input.send_keys(search_name)
        time.sleep(1)
        search_input.send_keys(Keys.RETURN)
        print("      -> Sukces. Wysłano zapytanie.")
        time.sleep(3) # Dajmy chwilę na załadowanie wyników

        # --- Zrzut ekranu #2: Po wyszukaniu frazy ---
        driver.save_screenshot(os.path.join(SCREENSHOTS_DIR, "2_po_wyszukaniu.png"))
        print("      -> ZROBIONO ZRZUT EKRANU: 2_po_wyszukaniu.png")
        
        # --- Krok 4: Przejście do filtra "Osoby" ---
        print("[4/6] Przechodzenie do filtra 'Osoby'...")
        people_filter_xpath = "//a[contains(@href, '/search/people/')]"
        people_filter_button = wait.until(EC.element_to_be_clickable((By.XPATH, people_filter_xpath)))
        people_filter_button.click()
        print("      -> Sukces. Przechodzę na stronę wyników dla osób.")
        time.sleep(5)

        # --- Zrzut ekranu #3: Po przejściu do filtra "Osoby" ---
        driver.save_screenshot(os.path.join(SCREENSHOTS_DIR, "3_po_filtrowaniu_osob.png"))
        print("      -> ZROBIONO ZRZUT EKRANU: 3_po_filtrowaniu_osob.png")
        
        # --- Krok 5: Pobranie wszystkich wyników i ich analiza ---
        print("[5/6] Analiza wyników wyszukiwania...")
        css_selector = 'a[role="link"] image'
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, css_selector)))
        all_image_elements = driver.find_elements(By.CSS_SELECTOR, css_selector)
        print(f"      -> Znaleziono {len(all_image_elements)} potencjalnych profili.")

        
        if not all_image_elements:
            print("!!! OSTRZEŻENIE: Brak wyników na stronie.")
            clients_table.update(record_id, {'LINK': f'BŁĄD - BRAK WYNIKÓW DLA {search_name}'})
            return

        found_match = False
        for i, image_element in enumerate(all_image_elements):
            print(f"      -> Przetwarzam profil {i+1}/{len(all_image_elements)}...")
            try:
                profile_link_element = image_element.find_element(By.XPATH, "./ancestor::a[1]")
                profile_link = profile_link_element.get_attribute('href')
                image_url = image_element.get_attribute('xlink:href')
                if not profile_link or not image_url:
                    print(f"         - Pominięto: Brak linku lub URL zdjęcia.")
                    continue
                
                response = requests.get(image_url)
                if response.status_code != 200:
                    print(f"         - Pominięto: Nie udało się pobrać zdjęcia z URL.")
                    continue
                
                scanned_image_hash = calculate_image_hash(response.content)
                if not scanned_image_hash:
                    print(f"         - Pominięto: Nie udało się przetworzyć zdjęcia z wyniku.")
                    continue
                    
                hash_diff = target_image_hash - scanned_image_hash
                print(f"         - Hash zdjęcia z wyniku: {scanned_image_hash} (Różnica: {hash_diff})")
                
                if hash_diff <= HASH_DIFFERENCE_THRESHOLD:
                    print("\n!!! ZNALEZIONO PASUJĄCY PROFIL !!!")
                    print(f"      -> Link: {profile_link}")
                    clients_table.update(record_id, {'LINK': profile_link})
                    print("--- WYSZUKIWARKA: Pomyślnie zaktualizowano LINK w Airtable. ---")
                    found_match = True
                    break # Zakończ pętlę po znalezieniu
            except Exception as e:
                print(f"         - Wystąpił błąd podczas analizy tego profilu: {e}")
                continue
        
        if not found_match:
            print("!!! OSTRZEŻENIE: Przejrzano wszystkie wyniki, nie znaleziono pasującego zdjęcia.")
            clients_table.update(record_id, {'LINK': f'BŁĄD - ZDJĘCIE NIE PASUJE DLA {search_name}'})

    except TimeoutException:
        print("!!! BŁĄD KRYTYCZNY: TimeoutException. Strona ładowała się zbyt długo lub nie znaleziono elementu.")
        clients_table.update(record_id, {'LINK': 'BŁĄD - TIMEOUT WYSZUKIWANIA'})
    except Exception as e:
        print("!!! BŁĄD KRYTYCZNY: Niespodziewany błąd w głównej logice wyszukiwarki.")
        traceback.print_exc()
        clients_table.update(record_id, {'LINK': 'BŁĄD - KRYTYCZNY WYJĄTEK WYSZUKIWANIA'})
    finally:
        # --- Krok 6: Zamykanie przeglądarki ---
        if driver:
            print("[6/6] Zamykanie przeglądarki...")
            driver.quit()
            print("      -> Sukces. Przeglądarka została zamknięta.")
        print("="*60)
        print(f"--- WYSZUKIWARKA: Zakończono zadanie dla klienta '{first_name} {last_name}' ---")
        print("="*60 + "\n")

def send_messenger_confirmation(psid, message_text, page_access_token):
    """Wysyła wiadomość potwierdzającą na Messengerze."""
    if not all([psid, message_text, page_access_token]):
        print("!!! MESSENGER: Błąd wysyłania - brak PSID, treści lub tokenu.")
        return

    params = {"access_token": page_access_token}
    payload = {
        "recipient": {"id": psid},
        "message": {"text": message_text},
        "messaging_type": "MESSAGE_TAG",
        "tag": "POST_PURCHASE_UPDATE"
    }
    
    try:
        print(f"--- MESSENGER: Próba wysłania potwierdzenia do PSID {psid}...")
        r = requests.post("https://graph.facebook.com/v19.0/me/messages", params=params, json=payload, timeout=30)
        r.raise_for_status()
        print(f"--- MESSENGER: Pomyślnie wysłano potwierdzenie do {psid}.")
    except requests.exceptions.RequestException as e:
        print(f"!!! MESSENGER: Błąd podczas wysyłania wiadomości do {psid}: {e}")
        print(f"    Odpowiedź serwera: {e.response.text if e.response else 'Brak'}")

def check_and_cancel_unpaid_lessons():
    """To zadanie jest uruchamiane w tle, aby ZMIENIĆ STATUS nieopłaconych lekcji."""
    
    warsaw_tz = pytz.timezone('Europe/Warsaw')
    current_local_time = datetime.now(warsaw_tz)
    
    # Zmieniamy print na logging.debug, aby był domyślnie ukryty
    logging.debug(f"[{current_local_time.strftime('%Y-%m-%d %H:%M:%S')}] Uruchamiam zadanie sprawdzania nieopłaconych lekcji...")
    
    try:
        formula = f"AND({{Opłacona}} != 1, IS_AFTER(DATETIME_PARSE(CONCATENATE({{Data}}, ' ', {{Godzina}})), NOW()), {{Status}} = 'Oczekuje na płatność')"
        
        potential_lessons = reservations_table.all(formula=formula)
        
        if not potential_lessons:
            logging.debug(f"[{current_local_time.strftime('%Y-%m-%d %H:%M:%S')}] Nie znaleziono przyszłych, nieopłaconych lekcji.")
            return

        logging.debug(f"Znaleziono {len(potential_lessons)} przyszłych, nieopłaconych lekcji. Sprawdzam terminy płatności...")
        
        lessons_to_cancel = []
        
        for lesson in potential_lessons:
            fields = lesson.get('fields', {})
            lesson_date_str = fields.get('Data')
            lesson_time_str = fields.get('Godzina')

            if not lesson_date_str or not lesson_time_str:
                continue

            lesson_datetime_naive = datetime.strptime(f"{lesson_date_str} {lesson_time_str}", "%Y-%m-%d %H:%M")
            lesson_datetime_aware = warsaw_tz.localize(lesson_datetime_naive)
            
            payment_deadline = lesson_datetime_aware - timedelta(hours=12)
            
            if current_local_time > payment_deadline:
                lessons_to_cancel.append(lesson)
                # Ten log jest ważny, więc zostaje jako INFO
                logging.info(f"Lekcja (ID: {lesson['id']}) z {lesson_date_str} o {lesson_time_str} zakwalifikowana do anulowania. Termin płatności: {payment_deadline.strftime('%Y-%m-%d %H:%M:%S')}")

        if not lessons_to_cancel:
            logging.debug(f"[{current_local_time.strftime('%Y-%m-%d %H:%M:%S')}] Żadna z lekcji nie przekroczyła terminu płatności.")
            return

        # Te logi również są ważne, więc zostają jako INFO
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
        # Błędy są zawsze krytyczne
        logging.error(f"!!! BŁĄD w zadaniu anulowania lekcji: {e}", exc_info=True)

def parse_time_range(time_range_str):
    try:
        if not time_range_str or '-' not in time_range_str: return None, None
        start_str, end_str = time_range_str.split('-')
        start_time = datetime.strptime(start_str.strip(), '%H:%M').time()
        end_time = datetime.strptime(end_str.strip(), '%H:%M').time()
        return start_time, end_time
    except ValueError: return None, None

def generate_teams_meeting_link(meeting_subject):
    token_url = f"https://login.microsoftonline.com/{MS_TENANT_ID}/oauth2/v2.0/token"
    token_data = {'grant_type': 'client_credentials', 'client_id': MS_CLIENT_ID, 'client_secret': MS_CLIENT_SECRET, 'scope': 'https://graph.microsoft.com/.default'}
    token_r = requests.post(token_url, data=token_data)
    if token_r.status_code != 200: return None
    access_token = token_r.json().get('access_token')
    if not access_token: return None
    meetings_url = f"https://graph.microsoft.com/v1.0/users/{MEETING_ORGANIZER_USER_ID}/onlineMeetings"
    headers = {'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'}
    start_time = datetime.utcnow() + timedelta(minutes=5)
    end_time = start_time + timedelta(hours=1)
    meeting_payload = {"subject": meeting_subject, "startDateTime": start_time.strftime('%Y-%m-%dT%H:%M:%SZ'), "endDateTime": end_time.strftime('%Y-%m-%dT%H:%M:%SZ'), "lobbyBypassSettings": {"scope": "everyone"}, "allowedPresenters": "everyone"}
    meeting_r = requests.post(meetings_url, headers=headers, data=json.dumps(meeting_payload))
    if meeting_r.status_code == 201: return meeting_r.json().get('joinUrl')
    return None

def find_reservation_by_token(token):
    if not token: return None
    return reservations_table.first(formula=f"{{ManagementToken}} = '{token}'")

def is_cancellation_allowed(record):
    fields = record.get('fields', {})
    lesson_date_str = fields.get('Data')
    lesson_time_str = fields.get('Godzina')
    if not lesson_date_str or not lesson_time_str: return False
    lesson_datetime = datetime.strptime(f"{lesson_date_str} {lesson_time_str}", "%Y-%m-%d %H:%M")
    return (lesson_datetime - datetime.now()) > timedelta(hours=12)

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

@app.route('/api/mark-lesson-as-paid', methods=['POST'])
def mark_lesson_as_paid():
    """Endpoint do symulacji płatności - zaznacza checkbox i zmienia status."""
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
            "Opłacona": True,
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
                'name': rec['fields'].get('Imię', 'Uczeń'),
                'link': rec['fields'].get('LINK') # <-- Pobieramy link
            }
            for rec in all_clients_records if 'ClientID' in rec.get('fields', {})
        }

        formula = f"AND({{Korepetytor}} = '{tutor_name}', IS_AFTER({{Data}}, DATEADD(TODAY(), -1, 'days')))"
        lessons_records = reservations_table.all(formula=formula)

        upcoming_lessons = []
        for record in lessons_records:
            fields = record.get('fields', {})
            status = fields.get('Status')
            if status in ['Niedostępny', 'Dostępny']:
                continue

            client_id = fields.get('Klient')
            client_info = clients_map.get(client_id, {})
            
            lesson_data = {
                'date': fields.get('Data'),
                'time': fields.get('Godzina'),
                'studentName': client_info.get('name', 'Brak danych'),
                'studentContactLink': client_info.get('link'), # <-- Dodajemy link do danych
                'subject': fields.get('Przedmiot'),
                'schoolType': fields.get('TypSzkoły'),
                'schoolLevel': fields.get('Poziom'),
                'schoolClass': fields.get('Klasa'),
                'teamsLink': fields.get('TeamsLink')
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
        all_tutors_templates = tutors_table.all()
        master_time_slots = set()

        for template in all_tutors_templates:
            fields = template.get('fields', {})
            for day_column in WEEKDAY_MAP.values():
                time_range_str = fields.get(day_column)
                if not time_range_str:
                    continue

                start_time, end_time = parse_time_range(time_range_str)
                if not start_time or not end_time:
                    continue
                
                # Używamy fikcyjnej daty, bo interesują nas tylko godziny
                dummy_date = datetime.now().date()
                current_slot_datetime = datetime.combine(dummy_date, start_time)
                end_datetime = datetime.combine(dummy_date, end_time)

                while current_slot_datetime < end_datetime:
                    if (current_slot_datetime + timedelta(minutes=60)) > end_datetime:
                        break
                    
                    master_time_slots.add(current_slot_datetime.strftime('%H:%M'))
                    current_slot_datetime += timedelta(minutes=70)
        
        # Sortuj godziny i zwróć jako listę
        sorted_slots = sorted(list(master_time_slots))
        return jsonify(sorted_slots)
        
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
            fields = record_to_reschedule.get('fields', {})
            psid = fields.get('Klient')
            
            reservations_table.update(record_to_reschedule['id'], {"Status": "Przeniesiona"})
            
            # --- DODANO POWIADOMIENIE ---
            if MESSENGER_PAGE_TOKEN and psid:
                dashboard_link = f"https://zakręcone-korepetycje.pl/moje-lekcje.html?clientID={psid}"
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
            return jsonify({"message": "Stały termin na ten dzień został oznaczony jako 'Przeniesiony'."})

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
        if not tutor_record or tutor_record['fields'].get('Imię i Nazwisko') != tutor_name:
            abort(403, "Brak uprawnień.")
        
        new_available_slot = {
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
    return jsonify({"firstName": client_record['fields'].get('Imię'), "lastName": client_record['fields'].get('Nazwisko')})

@app.route('/api/get-tutor-schedule')
def get_tutor_schedule():
    tutor_id = request.args.get('tutorID')
    if not tutor_id: abort(400, "Brak identyfikatora korepetytora.")
    tutor_record = tutors_table.first(formula=f"{{TutorID}} = '{tutor_id.strip()}'")
    if not tutor_record: abort(404, "Nie znaleziono korepetytora.")
    fields = tutor_record.get('fields', {})
    return jsonify({
        "Imię i Nazwisko": fields.get("Imię i Nazwisko"), "Poniedziałek": fields.get("Poniedziałek", ""),"Wtorek": fields.get("Wtorek", ""),
        "Środa": fields.get("Środa", ""), "Czwartek": fields.get("Czwartek", ""),"Piątek": fields.get("Piątek", ""),
        "Sobota": fields.get("Sobota", ""), "Niedziela": fields.get("Niedziela", "")
    })

@app.route('/api/update-tutor-schedule', methods=['POST'])
def update_tutor_schedule():
    data = request.json
    tutor_id = data.get('tutorID')
    new_schedule = data.get('schedule')
    if not tutor_id or not new_schedule: abort(400, "Brak wymaganych danych.")
    tutor_record = tutors_table.first(formula=f"{{TutorID}} = '{tutor_id.strip()}'")
    if not tutor_record: abort(404, "Nie znaleziono korepetytora.")
    fields_to_update = {day: time_range for day, time_range in new_schedule.items() if time_range is not None}
    tutors_table.update(tutor_record['id'], fields_to_update)
    return jsonify({"message": "Grafik został pomyślnie zaktualizowany."})

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

        # Weryfikacja korepetytora (bez zmian)
        tutor_record = tutors_table.first(formula=f"{{TutorID}} = '{tutor_id.strip()}'")
        if not tutor_record or tutor_record['fields'].get('Imię i Nazwisko') != tutor_name:
            abort(403, "Brak uprawnień.")
        
        # ### NOWA, ULEPSZONA LOGIKA ###
        # Sprawdzamy, czy istnieje JAKAKOLWIEK rezerwacja na ten termin (zwykła lub blokada)
        formula = f"AND({{Korepetytor}} = '{tutor_name}', DATETIME_FORMAT({{Data}}, 'YYYY-MM-DD') = '{date}', {{Godzina}} = '{time}')"
        existing_reservation = reservations_table.first(formula=formula)

        if existing_reservation:
            # Jeśli coś istnieje - usuwamy to (odblokowujemy lub odwołujemy lekcję)
            # W przyszłości można dodać walidację, czy to nie jest lekcja z uczniem
            reservations_table.delete(existing_reservation['id'])
            return jsonify({"message": "Termin został zwolniony."})
        else:
            # Jeśli nic nie istnieje - tworzymy blokadę (robimy sobie wolne)
            new_block = {
                "Korepetytor": tutor_name,
                "Data": date,
                "Godzina": time,
                "Typ": "Jednorazowa",
                "Status": "Niedostępny"
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
        subject = request.args.get('subject')
        tutor_name_filter = request.args.get('tutorName')

        all_tutors_templates = tutors_table.all()
        filtered_tutors = []

        # ... (sekcja filtrowania korepetytorów pozostaje bez zmian) ...
        if tutor_name_filter:
            found_tutor = next((t for t in all_tutors_templates if t.get('fields', {}).get('Imię i Nazwisko') == tutor_name_filter), None)
            if found_tutor: filtered_tutors.append(found_tutor)
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
                if all(tag in fields.get('PoziomNauczania', []) for tag in required_level_tags) and subject in fields.get('Przedmioty', []):
                    filtered_tutors.append(tutor)
        
        # ... (sekcja zbierania informacji o zajętych slotach pozostaje bez zmian) ...
        booked_slots = {}
        all_clients = {rec['fields'].get('ClientID'): rec['fields'] for rec in clients_table.all() if 'ClientID' in rec.get('fields', {})}
        formula_reservations = f"AND(IS_AFTER({{Data}}, DATETIME_PARSE('{start_date - timedelta(days=1)}', 'YYYY-MM-DD')), IS_BEFORE({{Data}}, DATETIME_PARSE('{end_date}', 'YYYY-MM-DD')))"
        reservations = reservations_table.all(formula=formula_reservations)
        
        for record in reservations:
            fields = record.get('fields', {})
            key = (fields.get('Korepetytor'), fields.get('Data'), fields.get('Godzina'))
            status = fields.get('Status')
            if status != 'Dostępny':
                student_name = all_clients.get(fields.get('Klient'), {}).get('Imię', 'Uczeń')
                client_info = all_clients.get(fields.get('Klient'), {})
                student_name = client_info.get('Imię', 'Uczeń')
                
                booked_slots[key] = {
                    "status": "booked_lesson" if status not in ['Niedostępny', 'Przeniesiona'] else ('blocked_by_tutor' if status == 'Niedostępny' else 'rescheduled_by_tutor'),
                    "studentName": student_name, 
                    "studentContactLink": client_info.get('LINK'), # <-- DODAJ TĘ LINIĘ
                    "subject": fields.get('Przedmiot'), "schoolType": fields.get('TypSzkoły'),
                    "schoolLevel": fields.get('Poziom'), "schoolClass": fields.get('Klasa'), "teamsLink": fields.get('TeamsLink')
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
                            student_name = all_clients.get(client_uuid, {}).get('Imię', 'Uczeń')
                            booked_slots[key] = {
                                "status": "cyclic_reserved", "studentName": f"{student_name} (Cykliczne)",
                                "subject": fields.get('Przedmiot'), "schoolType": fields.get('TypSzkoły'),
                                "schoolLevel": fields.get('Poziom'), "schoolClass": fields.get('Klasa')
                            }
            except ValueError: pass
        
        # Stała "główna" siatka godzin dla wszystkich
        master_start_time = dt_time(8, 0)
        master_end_time = dt_time(22, 0) # Siatka generowana do tej godziny

        # Generujemy wszystkie możliwe sloty na podstawie szablonów i filtrujemy je
        available_slots = []
        for template in filtered_tutors:
            fields = template.get('fields', {})
            tutor_name = fields.get('Imię i Nazwisko')
            if not tutor_name: continue
            
            for day_offset in range(7):
                current_date = start_date + timedelta(days=day_offset)
                time_range_str = fields.get(WEEKDAY_MAP[current_date.weekday()])
                if not time_range_str: continue
                
                # Godziny pracy korepetytora w tym dniu
                start_work_time, end_work_time = parse_time_range(time_range_str)
                if not start_work_time or not end_work_time: continue
                
                # Zaczynamy iterację od początku stałej siatki
                current_slot_datetime = datetime.combine(current_date, master_start_time)
                end_datetime_limit = datetime.combine(current_date, master_end_time)

                while current_slot_datetime < end_datetime_limit:
                    current_time_only = current_slot_datetime.time()
                    
                    # Sprawdź, czy aktualny slot z "głównej" siatki mieści się w godzinach pracy korepetytora
                    # Warunek: slot musi się zacząć i skończyć (po 60 min) w ramach godzin pracy
                    if start_work_time <= current_time_only and \
                       (current_slot_datetime + timedelta(minutes=60)) <= datetime.combine(current_date, end_work_time):
                        
                        slot_time_str = current_slot_datetime.strftime('%H:%M')
                        current_date_str = current_slot_datetime.strftime('%Y-%m-%d')
                        key = (tutor_name, current_date_str, slot_time_str)

                        # Sprawdź, czy nie jest zablokowany (dla listy wolnych terminów)
                        if key not in booked_slots:
                            available_slots.append({
                                'tutor': tutor_name,
                                'date': current_date_str,
                                'time': slot_time_str,
                                'status': 'available'
                            })
                    
                    # Zawsze przesuwaj się o 70 minut w ramach "głównej" siatki
                    current_slot_datetime += timedelta(minutes=70)
        
        # Dodaj jednorazowe dostępne terminy (one nie muszą pasować do siatki)
        for record in reservations:
            fields = record.get('fields', {})
            if fields.get('Status') == 'Dostępny':
                available_slots.append({
                    "tutor": fields.get('Korepetytor'), "date": fields.get('Data'),
                    "time": fields.get('Godzina'), "status": "available"
                })
            
        if tutor_name_filter:
            # ### TUTAJ NASTĄPIŁA KLUCZOWA ZMIANA ###
            # Dla panelu korepetytora budujemy PEŁNY grafik, używając tej samej logiki "głównej siatki"
            final_schedule = []
            # Zakładamy, że w filtered_tutors jest tylko jeden korepetytor
            for template in filtered_tutors:
                fields = template.get('fields', {})
                tutor_name = fields.get('Imię i Nazwisko')
                if not tutor_name: continue
                for day_offset in range(7):
                    current_date = start_date + timedelta(days=day_offset)
                    time_range_str = fields.get(WEEKDAY_MAP[current_date.weekday()])
                    if not time_range_str: continue
                    start_work_time, end_work_time = parse_time_range(time_range_str)
                    if not start_work_time or not end_work_time: continue
                    
                    current_slot_datetime = datetime.combine(current_date, master_start_time)
                    end_datetime_limit = datetime.combine(current_date, master_end_time)
                    
                    while current_slot_datetime < end_datetime_limit:
                        current_time_only = current_slot_datetime.time()

                        # Sprawdzamy, czy slot z "głównej siatki" mieści się w godzinach pracy
                        if start_work_time <= current_time_only and \
                           (current_slot_datetime + timedelta(minutes=60)) <= datetime.combine(current_date, end_work_time):

                            slot_time_str = current_slot_datetime.strftime('%H:%M')
                            current_date_str = current_slot_datetime.strftime('%Y-%m-%d')
                            key = (tutor_name, current_date_str, slot_time_str)
                            
                            slot_info = {'tutor': tutor_name, 'date': current_date_str, 'time': slot_time_str}
                            if key in booked_slots:
                                slot_info.update(booked_slots[key])
                            else:
                                slot_info['status'] = 'available'
                            
                            final_schedule.append(slot_info)

                        # Zawsze przesuwamy się w ramach tej samej siatki
                        current_slot_datetime += timedelta(minutes=70)
            return jsonify(final_schedule)
        else:
            # Dla stron rezerwacji zwracamy tylko listę wolnych slotów
            last_fetched_schedule = available_slots
            return jsonify(available_slots)

    except Exception as e:
        traceback.print_exc()
        abort(500, "Wewnętrzny błąd serwera.")

@app.route('/api/create-reservation', methods=['POST'])
def create_reservation():
    try:
        # ... (cały początek funkcji aż do `reservations_table.create` jest bez zmian) ...
        data = request.json
        is_test_lesson = 'isOneTime' not in data
        is_cyclic = not data.get('isOneTime', False) if not is_test_lesson else False
        
        client_uuid = data.get('clientID') # To jest PSID
        if not client_uuid: abort(400, "Brak ClientID.")
        
        client_record = clients_table.first(formula=f"{{ClientID}} = '{client_uuid.strip()}'")
        if not client_record: abort(404, "Klient nie istnieje.")
        
        first_name_from_form = data.get('firstName')
        last_name_from_form = data.get('lastName')
        
        client_update_data = {}
        if first_name_from_form: client_update_data['Imię'] = first_name_from_form
        if last_name_from_form: client_update_data['Nazwisko'] = last_name_from_form

        if client_update_data:
            clients_table.update(client_record['id'], client_update_data)
        
        first_name = first_name_from_form or client_record['fields'].get('Imię')
        
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
                tutor_name = fields.get('Imię i Nazwisko')
                required_level_tags = []
                if school_type_for_search == 'szkola_podstawowa': required_level_tags = LEVEL_MAPPING.get(school_type_for_search, [])
                elif (school_type_for_search in ['liceum', 'technikum']) and school_level_for_search:
                    key_podstawa = f"{school_type_for_search}_podstawowy"
                    required_level_tags = LEVEL_MAPPING.get(key_podstawa, [])
                    if school_level_for_search == 'rozszerzony':
                        key_rozszerzenie = f"{school_type_for_search}_rozszerzony"
                        required_level_tags.extend(LEVEL_MAPPING.get(key_rozszerzenie, []))
                teaches_this_level = all(tag in fields.get('PoziomNauczania', []) for tag in required_level_tags)
                teaches_this_subject = subject_for_search in fields.get('Przedmioty', [])
                if teaches_this_level and teaches_this_subject:
                    day_of_week_name = WEEKDAY_MAP[start_date_for_search.weekday()]
                    time_range_str = fields.get(day_of_week_name)
                    if time_range_str:
                        start_work, end_work = parse_time_range(time_range_str)
                        selected_time_obj = datetime.strptime(data['selectedTime'], '%H:%M').time()
                        if start_work and end_work and start_work <= selected_time_obj < end_work:
                            available_tutors_for_slot.append(tutor_name)
            if not available_tutors_for_slot:
                abort(500, "Brak dostępnych korepetytorów.")
            tutor_for_reservation = available_tutors_for_slot[0]

        extra_info = {
            "TypSzkoły": data.get('schoolType'), "Poziom": data.get('schoolLevel'), "Klasa": data.get('schoolClass')
        }

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

            # --- DODANO POWIADOMIENIE ---
            if MESSENGER_PAGE_TOKEN:
                psid = client_uuid.strip()
                dashboard_link = f"https://zakręcone-korepetycje.pl/moje-lekcje.html?clientID={psid}"
                message_to_send = (
                    f"Dziękujemy! Twój stały termin na {data['subject']} w każdy {day_of_week_name} o {data['selectedTime']} został pomyślnie zarezerwowany.\n\n"
                    f"Pamiętaj, aby potwierdzać każdą nadchodzącą lekcję w swoim panelu klienta:\n{dashboard_link}"
                )
                send_messenger_confirmation(psid, message_to_send, MESSENGER_PAGE_TOKEN)
            # --- KONIEC DODAWANIA ---

            return jsonify({"message": "Stały termin został pomyślnie zarezerwowany.", "clientID": client_uuid, "isCyclic": True})

        else: # Lekcja jednorazowa lub testowa
            management_token = str(uuid.uuid4())
            teams_link = generate_teams_meeting_link(f"Korepetycje: {data['subject']} dla {first_name}")
            if not teams_link: abort(500, "Nie udało się wygenerować linku Teams.")

            new_one_time_reservation = {
                "Klient": client_uuid.strip(), "Korepetytor": tutor_for_reservation,
                "Data": data['selectedDate'], "Godzina": data['selectedTime'],
                "Przedmiot": data.get('subject'), "ManagementToken": management_token,
                "Typ": "Jednorazowa", "Status": "Oczekuje na płatność", "TeamsLink": teams_link
            }
            new_one_time_reservation.update(extra_info)
            reservations_table.create(new_one_time_reservation)
            if is_test_lesson:
                client_fields = client_record.get('fields', {})
                # Pobieramy dane z odpowiednich kolumn
                first_name_client = client_fields.get('ImięKlienta')
                last_name_client = client_fields.get('NazwiskoKlienta')
                profile_pic_client = client_fields.get('Zdjęcie')
    
                if all([first_name_client, last_name_client, profile_pic_client]):
                    # Uruchom proces wyszukiwania w osobnym wątku, aby nie blokować odpowiedzi
                    search_thread = threading.Thread(
                        target=find_profile_and_update_airtable,
                        args=(client_record['id'], first_name_client, last_name_client, profile_pic_client)
                    )
                    search_thread.start()
                    print(f"--- INFO: Uruchomiono w tle wyszukiwarkę profilu dla {first_name_client} {last_name_client} ---")
                else:
                    print("--- OSTRZEŻENIE: Brak pełnych danych klienta (Imię/Nazwisko/Zdjęcie) do uruchomienia wyszukiwarki.")

            # --- NOWA, UPROSZCZONA LOGIKA WYSYŁANIA POWIADOMIEŃ ---
            if MESSENGER_PAGE_TOKEN:
                psid = client_uuid.strip()
                dashboard_link = f"https://zakręcone-korepetycje.pl/moje-lekcje.html?clientID={psid}"
                
                message_to_send = (
                    f"Dziękujemy za rezerwację!\n\n"
                    f"Twoja lekcja testowa z przedmiotu '{data['subject']}' została pomyślnie umówiona na dzień "
                    f"{data['selectedDate']} o godzinie {data['selectedTime']}.\n\n"
                    f"Możesz zarządzać wszystkimi swoimi lekcjami w osobistym panelu klienta pod adresem:\n{dashboard_link}"
                )
                send_messenger_confirmation(psid, message_to_send, MESSENGER_PAGE_TOKEN)
            else:
                print("!!! OSTRZEŻENIE: Nie wysłano wiadomości na Messengerze - brak tokena.")
            # --- KONIEC NOWEJ LOGIKI ---
            
            return jsonify({
                "teamsUrl": teams_link, "managementToken": management_token,
                "clientID": client_uuid, "isCyclic": False, "isTest": is_test_lesson
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
        first_name = client_record['fields'].get('Imię')

        day_num = list(WEEKDAY_MAP.keys())[list(WEEKDAY_MAP.values()).index(day_name)]
        today = datetime.now().date()
        days_ahead = day_num - today.weekday()
        if days_ahead <= 0: 
            days_ahead += 7
        next_lesson_date = today + timedelta(days=days_ahead)
        next_lesson_date_str = next_lesson_date.strftime('%Y-%m-%d')

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

        new_confirmed_lesson = {
            "Klient": client_uuid,
            "Korepetytor": tutor,
            "Data": next_lesson_date_str,
            "Godzina": lesson_time,
            "Przedmiot": subject,
            "ManagementToken": str(uuid.uuid4()),
            "Typ": "Cykliczna",
            "Status": "Oczekuje na płatność",
            "TeamsLink": teams_link,
            "TypSzkoły": fields.get('TypSzkoły'),
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

        # --- DODANO POWIADOMIENIE ---
        if MESSENGER_PAGE_TOKEN:
            psid = client_uuid.strip()
            dashboard_link = f"https://zakręcone-korepetycje.pl/moje-lekcje.html?clientID={psid}"
            message_to_send = (
                f"Potwierdzono! Twoja nadchodząca lekcja z przedmiotu '{subject}' została potwierdzona na dzień {next_lesson_date_str} o {lesson_time}.\n\n"
                f"Prosimy o opłacenie jej najpóźniej 12 godzin przed rozpoczęciem. Możesz zarządzać swoimi lekcjami tutaj:\n{dashboard_link}"
            )
            send_messenger_confirmation(psid, message_to_send, MESSENGER_PAGE_TOKEN)
        # --- KONIEC DODAWANIA ---
        
        return jsonify({
            "message": f"Najbliższa lekcja w dniu {next_lesson_date_str} została potwierdzona.", 
            "teamsUrl": teams_link
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
            abort(400, "Brak identyfikatora klienta.")
        
        client_id = client_id.strip()
        
        client_record = clients_table.first(formula=f"{{ClientID}} = '{client_id}'")
        if not client_record: 
            abort(404, "Nie znaleziono klienta.")
        client_name = client_record['fields'].get('Imię', 'Uczniu')

        all_tutors_records = tutors_table.all()
        tutor_links_map = {
            tutor['fields'].get('Imię i Nazwisko'): tutor['fields'].get('LINK')
            for tutor in all_tutors_records if 'Imię i Nazwisko' in tutor.get('fields', {})
        }

        all_reservations = reservations_table.all(formula=f"{{Klient}} = '{client_id}'")
        
        upcoming = []
        past = []
        for record in all_reservations:
            fields = record.get('fields', {})
            if 'Data' not in fields or 'Godzina' not in fields: 
                continue
            
            lesson_datetime = datetime.strptime(f"{fields['Data']} {fields['Godzina']}", "%Y-%m-%d %H:%M")
            status = fields.get('Status', 'N/A')
            
            lesson_data = {
                "date": fields.get('Data'),
                "time": fields.get('Godzina'),
                "tutor": fields.get('Korepetytor', 'N/A'),
                "subject": fields.get('Przedmiot', 'N/A'),
                "managementToken": fields.get('ManagementToken'),
                "status": status,
                "teamsLink": fields.get('TeamsLink'),
                "tutorContactLink": tutor_links_map.get(fields.get('Korepetytor')),
                "isPaid": fields.get('Opłacona', False),
                # === KLUCZOWA POPRAWKA JEST TUTAJ ===
                "Typ": fields.get('Typ')
                # === KONIEC POPRAWKI ===
            }
            
            inactive_statuses = ['Anulowana (brak płatności)', 'Przeniesiona (zakończona)']
            if lesson_datetime < datetime.now() or status in inactive_statuses:
                past.append(lesson_data)
            else:
                upcoming.append(lesson_data)
        
        upcoming.sort(key=lambda x: datetime.strptime(f"{x['date']} {x['time']}", "%Y-%m-%d %H:%M"))
        past.sort(key=lambda x: datetime.strptime(f"{x['date']} {x['time']}", "%Y-%m-%d %H:%M"), reverse=True)
        
        cyclic_lessons = []
        cyclic_records = cyclic_reservations_table.all(formula=f"{{Klient_ID}} = '{client_id}'")
        
        today = datetime.now().date()
        start_of_week = today - timedelta(days=today.weekday())
        end_of_week = start_of_week + timedelta(days=6)

        for record in cyclic_records:
            fields = record.get('fields', {})
            is_next_lesson_confirmed_this_week = False
            for lesson in upcoming:
                lesson_date = datetime.strptime(lesson['date'], '%Y-%m-%d').date()
                if lesson.get('Typ') == 'Cykliczna' and start_of_week <= lesson_date <= end_of_week:
                    is_next_lesson_confirmed_this_week = True
                    break

            tutor_name = fields.get('Korepetytor')
            cyclic_lessons.append({
                "id": record['id'],
                "dayOfWeek": fields.get('DzienTygodnia'),
                "time": fields.get('Godzina'),
                "tutor": tutor_name,
                "subject": fields.get('Przedmiot'),
                "isNextLessonConfirmed": is_next_lesson_confirmed_this_week,
                "tutorContactLink": tutor_links_map.get(tutor_name)
            })

        return jsonify({
            "clientName": client_name,
            "cyclicLessons": cyclic_lessons,
            "upcomingLessons": upcoming,
            "pastLessons": past
        })
    except Exception as e:
        traceback.print_exc()
        abort(500, "Wystąpił błąd podczas pobierania danych panelu klienta.")

@app.route('/api/get-reservation-details')
def get_reservation_details():
    try:
        token = request.args.get('token')
        record = find_reservation_by_token(token)
        if not record: 
            abort(404, "Nie znaleziono rezerwacji o podanym identyfikatorze.")
        
        fields = record.get('fields', {})
        
        client_uuid = fields.get('Klient')
        student_name = "N/A"
        
        if client_uuid:
            client_record = clients_table.first(formula=f"{{ClientID}} = '{client_uuid}'")
            if client_record:
                student_name = client_record.get('fields', {}).get('Imię', 'N/A')

        tutor_name = fields.get('Korepetytor')
        tutor_contact_link = None
        if tutor_name:
            tutor_record = tutors_table.first(formula=f"{{Imię i Nazwisko}} = '{tutor_name}'")
            if tutor_record:
                tutor_contact_link = tutor_record.get('fields', {}).get('LINK')

        return jsonify({
            "date": fields.get('Data'), 
            "time": fields.get('Godzina'), 
            "tutor": tutor_name,
            "student": student_name, 
            "isCancellationAllowed": is_cancellation_allowed(record),
            "clientID": client_uuid,
            "tutorContactLink": tutor_contact_link # Dodajemy link do odpowiedzi
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
        
        reservations_table.delete(record['id'])
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
        
        if not is_cancellation_allowed(original_record) and original_fields.get('Status') != 'Przeniesiona':
            abort(403, "Nie można zmienić terminu rezerwacji. Pozostało mniej niż 12 godzin.")

        tutor = original_fields.get('Korepetytor')
        
        formula_check = f"AND({{Korepetytor}} = '{tutor}', DATETIME_FORMAT({{Data}}, 'YYYY-MM-DD') = '{new_date}', {{Godzina}} = '{new_time}')"
        if reservations_table.first(formula=formula_check):
            abort(409, "Wybrany termin jest już zajęty. Proszę wybrać inny.")
        
        new_date_obj = datetime.strptime(new_date, '%Y-%m-%d').date()
        day_of_week_name = WEEKDAY_MAP[new_date_obj.weekday()]
        cyclic_check_formula = f"AND({{Korepetytor}} = '{tutor}', {{DzienTygodnia}} = '{day_of_week_name}', {{Godzina}} = '{new_time}', {{Aktywna}}=1)"
        if cyclic_reservations_table.first(formula=cyclic_check_formula):
            abort(409, "Wybrany termin jest zajęty przez rezerwację stałą. Proszę wybrać inny.")
            
        was_paid = original_fields.get('Opłacona', False)
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
            "Opłacona": was_paid,
            "ManagementToken": str(uuid.uuid4()),
            "TypSzkoły": original_fields.get('TypSzkoły'),
            "Poziom": original_fields.get('Poziom'),
            "Klasa": original_fields.get('Klasa'),
            "TeamsLink": original_fields.get('TeamsLink')
        }
        reservations_table.create(new_reservation_data)

        reservations_table.update(original_record['id'], {"Status": "Przeniesiona (zakończona)"})
        
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

if __name__ == '__main__':
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=check_and_cancel_unpaid_lessons, trigger="interval", minutes=1)
    scheduler.start()
    # Zarejestruj funkcję, która zamknie scheduler przy wyjściu z aplikacji
    atexit.register(lambda: scheduler.shutdown())
    app.run(port=5000, debug=True)
