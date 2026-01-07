"""
FACEBOOK.py - Serwer dla statystyk komentarzy Facebook
Uruchomić na innej maszynie wirtualnej, aby udostępnić statystyki.
"""

import os
import sys
from flask import Flask, jsonify
from flask_cors import CORS

# Dodaj ścieżkę do katalogu ze skryptami
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../strona')))

# Import modułu statystyk
from database_stats import get_stats

app = Flask(__name__)
CORS(app)

@app.route('/api/facebook-stats', methods=['GET'])
def get_facebook_stats():
    """Zwraca statystyki komentarzy Facebook."""
    try:
        stats_data = get_stats()
        return jsonify(stats_data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/')
def index():
    """Prosta strona główna."""
    return "<h1>Serwer statystyk Facebook</h1><p>Endpoint: /api/facebook-stats</p>"

if __name__ == '__main__':
    # Uruchom serwer na porcie 5000 (można zmienić)
    print("--- Uruchamianie serwera FACEBOOK.py na porcie 5000 ---")
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)