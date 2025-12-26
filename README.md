# Zakręcone Korepetycje - Platforma Rezerwacji

Polska platforma do rezerwacji lekcji korepetycji online z integracją Microsoft Teams i Facebook Messenger.

## 🔄 Zmiana: SQLite zamiast Airtable

**UWAGA**: Aplikacja została przeniesiona z Airtable na lokalną bazę danych SQLite.

### Główne zmiany:
- ✅ Lokalna baza danych SQLite (`korki.db`) zamiast Airtable
- ✅ Panel administracyjny do zarządzania danymi (`/baza-danych.html`)
- ✅ Zachowano pełną kompatybilność z istniejącym kodem
- ✅ Usunięto zależność od pyairtable

## 🚀 Szybki start

### 1. Instalacja zależności

```bash
# Utwórz wirtualne środowisko
python3 -m venv venv

# Aktywuj środowisko
source venv/bin/activate  # Linux/Mac
# lub
venv\Scripts\activate  # Windows

# Zainstaluj zależności
pip install -r requirements.txt
```

### 2. Migracja danych z Airtable do SQLite

Jeśli masz istniejące dane w Airtable, wykonaj migrację:

#### Krok 1: Eksport danych z Airtable
```bash
# Edytuj export_airtable.py i dodaj swoje klucze API
# Następnie uruchom eksport
python export_airtable.py
```

#### Krok 2: Import danych do SQLite
```bash
# Zaimportuj wyeksportowane dane
python import_data.py
```

#### Alternatywa: Ręczne dodanie danych
```bash
# Uruchom interaktywny shell Python
python3 -c "
from database import DatabaseTable
tutors = DatabaseTable('Korepetytorzy')
tutors.create({
    'TutorID': 'tutor001',
    'ImieNazwisko': 'Jan Kowalski',
    # ... pozostałe pola
})
"
```

### 3. Inicjalizacja bazy danych

Baza danych zostanie automatycznie utworzona przy pierwszym uruchomieniu. Opcjonalnie możesz dodać dane testowe:

```bash
python add_test_data.py
```

### 3. Uruchomienie aplikacji

```bash
# Development
python backend.py

# Production (z Gunicorn)
gunicorn --bind 0.0.0.0:8080 --workers 1 --threads 8 backend:app
```

### 4. Dostęp do panelu administracyjnego

1. Otwórz przeglądarkę: `http://localhost:5000/baza-danych.html`
2. Wpisz hasło: **szlafrok**
3. Zarządzaj danymi w bazie (dodawaj, edytuj, usuwaj rekordy)

## 📊 Struktura bazy danych

### Tabele:

1. **Klienci** - Dane klientów (ClientID, Imię, Nazwisko, LINK)
2. **Korepetytorzy** - Korepetytorzy i ich grafiki (TutorID, Imię i Nazwisko, godziny pracy)
3. **Rezerwacje** - Pojedyncze lekcje (Data, Godzina, Status, Typ, ManagementToken)
4. **StaleRezerwacje** - Rezerwacje cykliczne (DzienTygodnia, Godzina, Aktywna)

## 🔧 Panel administracyjny

### Funkcje:
- ✅ Przeglądanie wszystkich tabel
- ✅ Dodawanie nowych rekordów
- ✅ Edytowanie istniejących rekordów
- ✅ Usuwanie rekordów
- ✅ Autoryzacja hasłem (szlafrok)
- ✅ Responsywny interfejs

### Jak używać:

1. **Wybierz tabelę** - Kliknij na przycisk z nazwą tabeli
2. **Dodaj rekord** - Przycisk "+ Dodaj rekord"
3. **Edytuj** - Przycisk "Edytuj" przy każdym rekordzie
4. **Usuń** - Przycisk "Usuń" (z potwierdzeniem)

**UWAGA**: Przy edycji pól typu JSON (np. `Przedmioty`, `PoziomNauczania`) wpisuj w formacie:
```json
["Matematyka", "Fizyka"]
```

## 🐳 Docker

```bash
# Build
docker build -t strona-korki .

# Run
docker run -p 8080:8080 -v $(pwd)/korki.db:/app/korki.db strona-korki
```

## 📁 Struktura plików

```
strona-korki/
├── backend.py              # Główna aplikacja Flask
├── database.py             # Warstwa abstrakcji bazy danych SQLite
├── korki.db               # Baza danych SQLite (ignorowana w git)
├── add_test_data.py       # Skrypt do dodania danych testowych
├── baza-danych.html       # Panel administracyjny
├── index.html             # Strona główna
├── rezerwacja-testowa.html    # Rezerwacja lekcji testowej
├── rezerwacja-stala.html      # Rezerwacja stała
├── moje-lekcje.html          # Panel klienta
├── panel-korepetytora.html   # Panel korepetytora
├── edit.html                 # Edycja rezerwacji
├── script.js                 # Logika rezerwacji testowej
├── script-cykliczny.js       # Logika rezerwacji stałej
├── script-panel.js           # Logika panelu korepetytora
├── style.css                 # Style
├── requirements.txt          # Zależności Python
├── Dockerfile               # Konfiguracja Dockera
└── README.md               # Ten plik
```

## 🔑 API Endpoints

### Panel administracyjny:
- `POST /api/admin/login` - Logowanie (hasło: szlafrok)
- `POST /api/admin/logout` - Wylogowanie
- `GET /api/admin/check-auth` - Sprawdzenie autoryzacji
- `GET /api/admin/table/<nazwa>` - Pobierz dane z tabeli
- `POST /api/admin/table/<nazwa>/record` - Dodaj rekord
- `PUT /api/admin/table/<nazwa>/record/<id>` - Edytuj rekord
- `DELETE /api/admin/table/<nazwa>/record/<id>` - Usuń rekord

### Klient:
- `GET /api/verify-client?clientID={psid}` - Weryfikacja klienta
- `GET /api/get-schedule?startDate={date}&schoolType={type}&subject={subj}` - Dostępne terminy
- `POST /api/create-reservation` - Rezerwacja lekcji
- `GET /api/get-client-dashboard?clientID={psid}` - Panel klienta
- `POST /api/confirm-next-lesson` - Potwierdzenie lekcji cyklicznej
- `POST /api/cancel-cyclic-reservation` - Anulowanie rezerwacji cyklicznej
- `GET /api/get-reservation-details?token={token}` - Szczegóły rezerwacji
- `POST /api/cancel-reservation` - Anulowanie rezerwacji
- `POST /api/reschedule-reservation` - Przeniesienie terminu

### Korepetytor:
- `GET /api/get-tutor-schedule?tutorID={id}` - Grafik korepetytora
- `POST /api/update-tutor-schedule` - Aktualizacja grafiku
- `POST /api/block-single-slot` - Blokada/odblokowanie terminu
- `POST /api/add-one-time-slot` - Dodanie jednorazowego terminu

## ⚙️ Konfiguracja

### Zmiana hasła admina:

W pliku `backend.py` (linia ~49):
```python
ADMIN_PASSWORD = "szlafrok"
```

### Ścieżka do bazy danych:

W pliku `database.py` (linia 7):
```python
DB_PATH = os.path.join(os.path.dirname(__file__), 'korki.db')
```

## 🔒 Bezpieczeństwo

**OSTRZEŻENIE**: Obecna implementacja zawiera hardcodowane sekrety:
- Microsoft Client Secret
- Messenger Page Token
- Hasło admina

**Przed deploymentem produkcyjnym**:
1. Przenieś sekrety do zmiennych środowiskowych
2. Użyj silniejszego hasła admina
3. Włącz HTTPS
4. Skonfiguruj proper session management
5. Dodaj rate limiting

## 📝 Backup bazy danych

```bash
# Backup
cp korki.db korki_backup_$(date +%Y%m%d).db

# Restore
cp korki_backup_20241107.db korki.db
```

## 🐛 Debugowanie

### Sprawdź zawartość bazy:

```python
from database import DatabaseTable

# Lista wszystkich klientów
clients = DatabaseTable('Klienci')
for client in clients.all():
    print(client)

# Wyszukiwanie po formule
client = clients.first(formula="{ClientID} = '123456789'")
print(client)
```

### Logi:

Aplikacja loguje na poziomie DEBUG. Sprawdź terminal gdzie uruchomiono `backend.py`.

## 📚 Dokumentacja

Szczegółowa dokumentacja architektury znajduje się w `WARP.md`.

## 🆘 Wsparcie

W razie problemów:
1. Sprawdź logi w terminalu
2. Upewnij się, że baza danych istnieje (`korki.db`)
3. Sprawdź czy virtual environment jest aktywowane
4. Zrestartuj backend

## 📄 Licencja

Własnościowa - Zakręcone Korepetycje
# Test commit
