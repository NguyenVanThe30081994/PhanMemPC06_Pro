import sys
import os

# Set UTF-8 encoding
os.environ['PYTHONIOENCODING'] = 'utf-8'

# Add current directory to path
APP_ROOT = os.path.dirname(__file__)
sys.path.insert(0, APP_ROOT)


def load_env_file(env_path):
    """Load simple KEY=VALUE pairs from .env for Passenger hosting."""
    if not os.path.exists(env_path):
        return

    try:
        with open(env_path, 'r', encoding='utf-8') as env_file:
            for raw_line in env_file:
                line = raw_line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue

                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception as exc:
        print(f"Unable to load .env file: {exc}")


load_env_file(os.path.join(APP_ROOT, '.env'))

# Import WSGI app directly - simple and clean
from app import app as application
