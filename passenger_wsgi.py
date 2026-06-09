import sys
import os
from env_loader import load_env_file

# Set UTF-8 encoding
os.environ['PYTHONIOENCODING'] = 'utf-8'
os.environ.setdefault('PC06_PASSENGER', '1')

# Add current directory to path
APP_ROOT = os.path.dirname(__file__)
sys.path.insert(0, APP_ROOT)

load_env_file(os.path.join(APP_ROOT, '.env'))

# Import WSGI app directly - simple and clean
from app import app as application
