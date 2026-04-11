from app import app
from models import RankingIndicator

with app.app_context():
    indicators = RankingIndicator.query.all()
    for i in indicators:
        print(f"{i.id}: {i.name}")
