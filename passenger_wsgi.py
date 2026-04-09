import sys, os

# Setup path
sys.path.insert(0, os.path.dirname(__file__))

# Import the Flask app
from app import app as application

# Passenger requires 'application' to be defined
if __name__ == "__main__":
    application.run()
