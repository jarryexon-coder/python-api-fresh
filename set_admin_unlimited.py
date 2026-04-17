import firebase_admin
from firebase_admin import credentials, firestore
import os

# Initialize Firebase – use your actual service account JSON or environment variable
cred = credentials.Certificate("path/to/your/serviceAccountKey.json")  # or use os.getenv("FIREBASE_SERVICE_ACCOUNT")
firebase_admin.initialize_app(cred)

db = firestore.client()

admin_email = "your-admin-email@example.com"  # CHANGE THIS
users = db.collection('users').where('email', '==', admin_email).limit(1).stream()

updated = False
for user in users:
    db.collection('users').document(user.id).update({
        'unlimited_credits': True,
        'role': 'admin'
    })
    print(f"✅ Updated user {user.id} ({admin_email}) with unlimited_credits=True")
    updated = True

if not updated:
    print(f"❌ No user found with email {admin_email}")
