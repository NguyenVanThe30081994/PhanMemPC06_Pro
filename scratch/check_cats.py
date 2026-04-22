import sys
import os
sys.path.append(os.path.abspath('.'))
from app import app
from models import db, CategoryGroup, CategoryItem
with app.app_context():
    groups = CategoryGroup.query.all()
    for g in groups:
        print(f"Group: {g.name}, Linked: {g.linked_modules}")
        for i in g.items:
            print(f"  - {i.name}")
