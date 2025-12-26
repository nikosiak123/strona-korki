#!/usr/bin/env python3
"""
Skrypt do walidacji i naprawy danych w bazie SQLite.
Sprawdza wszystkie tabele i naprawia znalezione problemy.

Uruchom: python validate_and_fix_data.py
"""

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from database import DatabaseTable, init_database

class DatabaseValidator:
    def __init__(self):
        self.issues_found = 0
        self.issues_fixed = 0
        self.report = []

    def log(self, message, level="INFO"):
        """Loguje wiadomość."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.report.append(f"[{timestamp}] {level}: {message}")
        print(f"[{timestamp}] {level}: {message}")

    def validate_tutors(self):
        """Waliduje i naprawia dane korepetytorów."""
        self.log("Sprawdzam tabelę Korepetytorzy...")

        tutors_table = DatabaseTable('Korepetytorzy')
        tutors = tutors_table.all()

        for record in tutors:
            fields = record['fields']
            record_id = record['id']
            tutor_name = fields.get('ImieNazwisko', 'Nieznany')

            # Sprawdź wymagane pola
            required_fields = ['TutorID', 'ImieNazwisko']
            for field in required_fields:
                if not fields.get(field):
                    self.log(f"✗ Korepetytor {tutor_name} (ID: {record_id}): Brak pola {field}", "ERROR")
                    self.issues_found += 1

            # Sprawdź format list
            list_fields = ['PoziomNauczania', 'Przedmioty']
            for field in list_fields:
                value = fields.get(field, [])
                if isinstance(value, str):
                    try:
                        # Spróbuj sparsować jako JSON
                        parsed = json.loads(value)
                        if not isinstance(parsed, list):
                            parsed = [value]  # Zamień na listę
                        fields[field] = json.dumps(parsed)
                        tutors_table.update(record_id, {field: json.dumps(parsed)})
                        self.log(f"✓ Naprawiono {field} dla {tutor_name}: {parsed}")
                        self.issues_fixed += 1
                    except json.JSONDecodeError:
                        # Jeśli nie JSON, zamień na listę
                        fields[field] = json.dumps([value])
                        tutors_table.update(record_id, {field: json.dumps([value])})
                        self.log(f"✓ Przekonwertowano {field} na listę dla {tutor_name}")
                        self.issues_fixed += 1
                elif not isinstance(value, list):
                    # Zamień na listę
                    fields[field] = json.dumps([str(value)])
                    tutors_table.update(record_id, {field: json.dumps([str(value)])})
                    self.log(f"✓ Przekonwertowano {field} na listę dla {tutor_name}")
                    self.issues_fixed += 1

            # Sprawdź limit godzin
            limit = fields.get('LimitGodzinTygodniowo')
            if limit is not None and not isinstance(limit, int):
                try:
                    new_limit = int(limit)
                    tutors_table.update(record_id, {'LimitGodzinTygodniowo': new_limit})
                    self.log(f"✓ Przekonwertowano limit godzin na int dla {tutor_name}: {new_limit}")
                    self.issues_fixed += 1
                except ValueError:
                    tutors_table.update(record_id, {'LimitGodzinTygodniowo': None})
                    self.log(f"✓ Usunięto nieprawidłowy limit godzin dla {tutor_name}")
                    self.issues_fixed += 1

    def validate_clients(self):
        """Waliduje i naprawia dane klientów."""
        self.log("Sprawdzam tabelę Klienci...")

        clients_table = DatabaseTable('Klienci')
        clients = clients_table.all()

        for record in clients:
            fields = record['fields']
            record_id = record['id']
            client_name = f"{fields.get('Imie', 'Nieznany')} {fields.get('Nazwisko', 'Nieznany')}"

            # Sprawdź wymagane pola
            required_fields = ['ClientID']
            for field in required_fields:
                if not fields.get(field):
                    self.log(f"✗ Klient {client_name} (ID: {record_id}): Brak pola {field}", "ERROR")
                    self.issues_found += 1

            # Sprawdź wolną kwotę
            wolna_kwota = fields.get('wolna_kwota', 0)
            if not isinstance(wolna_kwota, int):
                try:
                    new_kwota = int(float(wolna_kwota))
                    clients_table.update(record_id, {'wolna_kwota': new_kwota})
                    self.log(f"✓ Przekonwertowano wolną kwotę na int dla {client_name}: {new_kwota}")
                    self.issues_fixed += 1
                except (ValueError, TypeError):
                    clients_table.update(record_id, {'wolna_kwota': 0})
                    self.log(f"✓ Ustawiono domyślną wolną kwotę dla {client_name}")
                    self.issues_fixed += 1

    def validate_reservations(self):
        """Waliduje i naprawia dane rezerwacji."""
        self.log("Sprawdzam tabelę Rezerwacje...")

        reservations_table = DatabaseTable('Rezerwacje')
        reservations = reservations_table.all()

        for record in reservations:
            fields = record['fields']
            record_id = record['id']
            reservation_info = f"{fields.get('Data', 'Brak daty')} {fields.get('Godzina', 'Brak godziny')}"

            # Sprawdź wymagane pola
            required_fields = ['Klient', 'Korepetytor', 'Data', 'Godzina']
            for field in required_fields:
                if not fields.get(field):
                    self.log(f"✗ Rezerwacja {reservation_info} (ID: {record_id}): Brak pola {field}", "ERROR")
                    self.issues_found += 1

            # Sprawdź format boolean
            bool_fields = ['Oplacona', 'JestTestowa']
            for field in bool_fields:
                value = fields.get(field, False)
                if isinstance(value, int):
                    # Już jest int, OK
                    continue
                elif isinstance(value, str):
                    # Spróbuj przekonwertować
                    new_value = value.lower() in ('true', '1', 'yes')
                    reservations_table.update(record_id, {field: 1 if new_value else 0})
                    self.log(f"✓ Przekonwertowano {field} na boolean dla rezerwacji {reservation_info}")
                    self.issues_fixed += 1
                elif not isinstance(value, bool):
                    new_value = bool(value)
                    reservations_table.update(record_id, {field: 1 if new_value else 0})
                    self.log(f"✓ Przekonwertowano {field} na boolean dla rezerwacji {reservation_info}")
                    self.issues_fixed += 1

    def validate_cyclic_reservations(self):
        """Waliduje i naprawia dane stałych rezerwacji."""
        self.log("Sprawdzam tabelę StaleRezerwacje...")

        cyclic_table = DatabaseTable('StaleRezerwacje')
        cyclic = cyclic_table.all()

        for record in cyclic:
            fields = record['fields']
            record_id = record['id']
            cyclic_info = f"{fields.get('DzienTygodnia', 'Brak dnia')} {fields.get('Godzina', 'Brak godziny')}"

            # Sprawdź wymagane pola
            required_fields = ['Klient_ID', 'Korepetytor', 'DzienTygodnia', 'Godzina']
            for field in required_fields:
                if not fields.get(field):
                    self.log(f"✗ Stała rezerwacja {cyclic_info} (ID: {record_id}): Brak pola {field}", "ERROR")
                    self.issues_found += 1

            # Sprawdź Aktywna
            aktywna = fields.get('Aktywna', True)
            if not isinstance(aktywna, int):
                new_value = 1 if bool(aktywna) else 0
                cyclic_table.update(record_id, {'Aktywna': new_value})
                self.log(f"✓ Przekonwertowano Aktywna na int dla stałej rezerwacji {cyclic_info}")
                self.issues_fixed += 1

    def add_missing_data(self):
        """Dodaje brakujące dane testowe jeśli baza jest pusta."""
        self.log("Sprawdzam czy baza potrzebuje danych testowych...")

        tutors_table = DatabaseTable('Korepetytorzy')
        clients_table = DatabaseTable('Klienci')

        if len(tutors_table.all()) == 0:
            self.log("Baza nie ma korepetytorów - dodaję dane testowe...")

            # Dodaj testowego korepetytora
            tutors_table.create({
                'TutorID': 'tutor001',
                'ImieNazwisko': 'Jan Kowalski',
                'Poniedziałek': '08:00-16:00',
                'Wtorek': '08:00-16:00',
                'Środa': '08:00-16:00',
                'Czwartek': '08:00-16:00',
                'Piątek': '08:00-16:00',
                'Sobota': '10:00-14:00',
                'Niedziela': '',
                'Przedmioty': json.dumps(['Matematyka']),
                'PoziomNauczania': json.dumps(['liceum_podstawa']),
                'LINK': 'https://facebook.com/jan.kowalski',
                'LimitGodzinTygodniowo': 40,
                'Email': 'jan.kowalski@email.com'
            })
            self.log("✓ Dodano testowego korepetytora")
            self.issues_fixed += 1

        if len(clients_table.all()) == 0:
            self.log("Baza nie ma klientów - dodaję dane testowe...")

            # Dodaj testowego klienta
            clients_table.create({
                'ClientID': 'client001',
                'Imie': 'Anna',
                'Nazwisko': 'Nowak',
                'LINK': 'https://facebook.com/anna.nowak',
                'ImieKlienta': 'Anna',
                'NazwiskoKlienta': 'Nowak',
                'Zdjecie': 'https://example.com/photo.jpg',
                'wolna_kwota': 0
            })
            self.log("✓ Dodano testowego klienta")
            self.issues_fixed += 1

    def generate_report(self):
        """Generuje raport z walidacji."""
        self.log("=" * 50)
        self.log("RAPORT WALIDACJI BAZY DANYCH")
        self.log("=" * 50)
        self.log(f"Znalezionych problemów: {self.issues_found}")
        self.log(f"Naprawionych problemów: {self.issues_fixed}")
        self.log("=" * 50)

        if self.issues_found == 0 and self.issues_fixed == 0:
            self.log("✅ Baza danych jest w porządku!")
        elif self.issues_fixed > 0:
            self.log("✅ Problemy zostały naprawione!")
        else:
            self.log("⚠️ Znaleziono problemy, ale nie wszystkie zostały automatycznie naprawione.")

    def run_validation(self):
        """Uruchamia pełną walidację."""
        self.log("Rozpoczynam walidację bazy danych...")

        # Inicjalizuj bazę
        init_database()

        # Sprawdź czy baza istnieje
        if not os.path.exists('korki.db'):
            self.log("✗ Baza danych nie istnieje!", "ERROR")
            return

        # Waliduj wszystkie tabele
        self.validate_tutors()
        self.validate_clients()
        self.validate_reservations()
        self.validate_cyclic_reservations()

        # Dodaj brakujące dane jeśli potrzeba
        self.add_missing_data()

        # Generuj raport
        self.generate_report()

        # Zapisz raport do pliku
        with open('validation_report.txt', 'w', encoding='utf-8') as f:
            f.write('\n'.join(self.report))

        self.log("Raport zapisany do validation_report.txt")

def main():
    validator = DatabaseValidator()
    validator.run_validation()

if __name__ == '__main__':
    main()