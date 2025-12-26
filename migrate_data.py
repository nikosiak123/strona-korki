#!/usr/bin/env python3
"""
Skrypt do migracji danych z Airtable do SQLite.
Uruchom: python migrate_data.py
"""

import json
import os
import sys

# Dodaj ścieżkę do projektu
sys.path.insert(0, os.path.dirname(__file__))

from database import DatabaseTable, init_database

def migrate_tutors():
    """Migracja danych korepetytorów."""
    print("Migracja tabeli Korepetytorzy...")

    tutors_table = DatabaseTable('Korepetytorzy')

    # Przykładowe dane - ZASTĄP SWOIMI RZECZYWISTYMI DANymi
    tutors_data = [
        {
            'TutorID': 'tutor001',
            'ImieNazwisko': 'Jan Kowalski',
            'Poniedziałek': '08:00-16:00',
            'Wtorek': '08:00-16:00',
            'Środa': '08:00-16:00',
            'Czwartek': '08:00-16:00',
            'Piątek': '08:00-16:00',
            'Sobota': '10:00-14:00',
            'Niedziela': '',
            'Przedmioty': 'Matematyka',
            'PoziomNauczania': 'liceum_podstawa',
            'LINK': 'https://example.com',
            'LimitGodzinTygodniowo': 40,
            'Email': 'jan.kowalski@example.com'
        },
        # Dodaj więcej korepetytorów...
    ]

    for tutor in tutors_data:
        try:
            tutors_table.create(tutor)
            print(f"✓ Dodano korepetytora: {tutor['ImieNazwisko']}")
        except Exception as e:
            print(f"✗ Błąd dodawania {tutor['ImieNazwisko']}: {e}")

def migrate_clients():
    """Migracja danych klientów."""
    print("Migracja tabeli Klienci...")

    clients_table = DatabaseTable('Klienci')

    # Przykładowe dane klientów
    clients_data = [
        {
            'ClientID': 'client001',
            'Imie': 'Anna',
            'Nazwisko': 'Nowak',
            'LINK': 'https://facebook.com/anna.nowak',
            'ImieKlienta': 'Anna',
            'NazwiskoKlienta': 'Nowak',
            'Zdjecie': 'https://example.com/photo.jpg',
            'wolna_kwota': 0
        },
        # Dodaj więcej klientów...
    ]

    for client in clients_data:
        try:
            clients_table.create(client)
            print(f"✓ Dodano klienta: {client['Imie']} {client['Nazwisko']}")
        except Exception as e:
            print(f"✗ Błąd dodawania {client['Imie']} {client['Nazwisko']}: {e}")

def migrate_reservations():
    """Migracja danych rezerwacji."""
    print("Migracja tabeli Rezerwacje...")

    reservations_table = DatabaseTable('Rezerwacje')

    # Przykładowe dane rezerwacji
    reservations_data = [
        {
            'Klient': 'client001',
            'Korepetytor': 'Jan Kowalski',
            'Data': '2025-12-30',
            'Godzina': '10:00',
            'Przedmiot': 'Matematyka',
            'Status': 'Oczekuje na płatność',
            'Typ': 'Jednorazowa',
            'JestTestowa': 0,
            'Oplacona': 0,
            'TypSzkoly': 'liceum',
            'Poziom': 'podstawowy',
            'Klasa': '3'
        },
        # Dodaj więcej rezerwacji...
    ]

    for reservation in reservations_data:
        try:
            reservations_table.create(reservation)
            print(f"✓ Dodano rezerwację: {reservation['Data']} {reservation['Godzina']}")
        except Exception as e:
            print(f"✗ Błąd dodawania rezerwacji: {e}")

def main():
    print("Rozpoczynam migrację danych z Airtable do SQLite...")

    # Inicjalizuj bazę danych
    init_database()

    # Migruj dane
    migrate_tutors()
    migrate_clients()
    migrate_reservations()

    print("Migracja zakończona!")

if __name__ == '__main__':
    main()