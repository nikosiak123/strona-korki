
import sys
import os

print(f"Original sys.path: {sys.path}")

# Simulate backend.py behavior
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../strona')))

print(f"Modified sys.path: {sys.path}")

try:
    import config
    print(f"Imported config from: {config.__file__}")
    if hasattr(config, 'DB_PATH'):
        print(f"config.DB_PATH: {config.DB_PATH}")
    else:
        print("config.DB_PATH not found")
except ImportError as e:
    print(f"ImportError: {e}")

try:
    import config_loader
    print(f"Imported config_loader from: {config_loader.__file__}")
    print(f"config_loader.DB_PATH: {config_loader.DB_PATH}")
except ImportError as e:
    print(f"ImportError for config_loader: {e}")
