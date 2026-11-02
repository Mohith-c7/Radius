from db import Database

def get_user(id: int):
    db = Database()
    user = db.query(id)
    return user

