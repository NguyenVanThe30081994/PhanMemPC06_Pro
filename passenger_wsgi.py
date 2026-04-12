import sys
import os

# Set UTF-8 encoding
os.environ['PYTHONIOENCODING'] = 'utf-8'

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

# Import WSGI app directly
from app import app as application

# Create callable for Passenger
application
