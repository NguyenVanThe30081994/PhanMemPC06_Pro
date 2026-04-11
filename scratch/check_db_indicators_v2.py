import sys
import os
sys.path.append(os.getcwd())

from app import app
from models import RankingIndicator

with app.app_context():
    indicators = RankingIndicator.query.all()
    with open('scratch/db_indicators.txt', 'w', encoding='utf-8') as f:
        f.write(f"Found {len(indicators)} indicators\n")
        for i in indicators:
            f.write(f"{i.id}: {i.name}\n")
