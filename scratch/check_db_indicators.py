from app import app
from models import RankingIndicator

with app.app_context():
    indicators = RankingIndicator.query.all()
    with open('scratch/db_indicators.txt', 'w', encoding='utf-8') as f:
        for i in indicators:
            f.write(f"{i.id}: {i.name}\n")
