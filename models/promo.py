from datetime import datetime, timedelta
import uuid
import stripe

class PromoCode:
    def __init__(self, code, influencer_id, influencer_name, discount_percent=10, 
                 commission_rate=10, max_uses=None, expires_at=None):
        self.id = str(uuid.uuid4())
        self.code = code.upper()
        self.influencer_id = influencer_id
        self.influencer_name = influencer_name
        self.discount_percent = discount_percent  # % off first month
        self.commission_rate = commission_rate  # % ongoing commission
        self.created_at = datetime.utcnow()
        self.expires_at = expires_at or (datetime.utcnow() + timedelta(days=365))
        self.max_uses = max_uses
        self.uses = 0
        self.active = True
        self.referrals = []  # Track subscriptions from this code
        
class PromoReferral:
    def __init__(self, promo_code_id, user_id, subscription_id, amount_paid):
        self.id = str(uuid.uuid4())
        self.promo_code_id = promo_code_id
        self.user_id = user_id
        self.subscription_id = subscription_id
        self.amount_paid = amount_paid
        self.commission_earned = amount_paid * 0.10  # 10% commission
        self.created_at = datetime.utcnow()
        self.is_active = True
        
# In-memory storage (replace with database)
promo_codes_db = {}
referrals_db = {}
