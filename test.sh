# In Python console or temporary script
from firebase_admin import firestore
db = firestore.client()
admin_email = "your-admin-email@example.com"  # Replace
users = db.collection('users').where('email', '==', admin_email).limit(1).stream()
for user in users:
    db.collection('users').document(user.id).update({'unlimited_credits': True, 'role': 'admin'})
    print(f"Updated {user.id}")
