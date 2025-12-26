#!/usr/bin/env python3
"""
Skrypt do eksportu danych z Airtable.
Wymaga klucza API Airtable i ID bazy.

Uruchom: python export_airtable.py
"""

import requests
import json
import os

# Konfiguracja Airtable - ZASTĄP SWOIMI DANYMI
AIRTABLE_API_KEY = 'YOUR_AIRTABLE_API_KEY'
AIRTABLE_BASE_ID = 'YOUR_AIRTABLE_BASE_ID'

TABLES = {
    'Korepetytorzy': 'YOUR_TABLE_ID',
    'Klienci': 'YOUR_TABLE_ID',
    'Rezerwacje': 'YOUR_TABLE_ID',
    'StaleRezerwacje': 'YOUR_TABLE_ID'
}

def export_table(table_name, table_id):
    """Eksportuje dane z jednej tabeli Airtable."""
    url = f'https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{table_id}'
    headers = {
        'Authorization': f'Bearer {AIRTABLE_API_KEY}'
    }

    records = []
    offset = None

    while True:
        params = {}
        if offset:
            params['offset'] = offset

        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()

        data = response.json()
        records.extend(data['records'])

        offset = data.get('offset')
        if not offset:
            break

    # Zapisz do pliku JSON
    filename = f'{table_name.lower()}_export.json'
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print(f"✓ Wyeksportowano {len(records)} rekordów z tabeli {table_name} do {filename}")
    return records

def main():
    print("Rozpoczynam eksport danych z Airtable...")

    if AIRTABLE_API_KEY == 'YOUR_AIRTABLE_API_KEY':
        print("❌ ZASTĄP AIRTABLE_API_KEY swoim kluczem API!")
        return

    if AIRTABLE_BASE_ID == 'YOUR_AIRTABLE_BASE_ID':
        print("❌ ZASTĄP AIRTABLE_BASE_ID swoim ID bazy!")
        return

    for table_name, table_id in TABLES.items():
        if table_id == 'YOUR_TABLE_ID':
            print(f"⚠️  Pomiń tabelę {table_name} - brak ID tabeli")
            continue

        try:
            export_table(table_name, table_id)
        except Exception as e:
            print(f"✗ Błąd eksportu tabeli {table_name}: {e}")

    print("Eksport zakończony!")

if __name__ == '__main__':
    main()