#!/usr/bin/env python3
"""
Skrypt do importu danych z JSON (wyeksportowanych z Airtable) do SQLite.

Uruchom: python import_data.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from database import DatabaseTable, init_database

def import_table(table_name, json_file):
    """Importuje dane z pliku JSON do tabeli SQLite."""
    if not os.path.exists(json_file):
        print(f"✗ Plik {json_file} nie istnieje")
        return

    with open(json_file, 'r', encoding='utf-8') as f:
        records = json.load(f)

    table = DatabaseTable(table_name)
    imported = 0
    errors = 0

    for record in records:
        try:
            fields = record.get('fields', {})

            # Konwertuj pola specyficzne dla Airtable
            if table_name == 'Korepetytorzy':
                # Airtable może mieć listy w polach, SQLite przechowuje jako JSON
                for field in ['PoziomNauczania', 'Przedmioty']:
                    if field in fields and isinstance(fields[field], list):
                        fields[field] = json.dumps(fields[field])

            elif table_name == 'Rezerwacje':
                # Konwertuj boolean na int
                for field in ['Oplacona', 'JestTestowa']:
                    if field in fields:
                        fields[field] = 1 if fields[field] else 0

            table.create(fields)
            imported += 1

        except Exception as e:
            print(f"✗ Błąd importu rekordu {record.get('id')}: {e}")
            errors += 1

    print(f"✓ Zaimportowano {imported} rekordów do tabeli {table_name}")
    if errors > 0:
        print(f"⚠️  {errors} błędów podczas importu")

def main():
    print("Rozpoczynam import danych do SQLite...")

    init_database()

    # Importuj dane z plików JSON
    imports = [
        ('Korepetytorzy', 'korepetytorzy_export.json'),
        ('Klienci', 'klienci_export.json'),
        ('Rezerwacje', 'rezerwacje_export.json'),
        ('StaleRezerwacje', 'stalerezerwacje_export.json')
    ]

    for table_name, json_file in imports:
        try:
            import_table(table_name, json_file)
        except Exception as e:
            print(f"✗ Błąd importu tabeli {table_name}: {e}")

    print("Import zakończony!")

if __name__ == '__main__':
    main()