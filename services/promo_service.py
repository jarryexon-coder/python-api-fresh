import stripe
from models.promo import PromoCode, PromoReferral
from datetime import datetime
import random
import string
import stripe

def generate_promo_code(influencer_name):
    """Generate a unique promo code for an influencer"""
    # Create code from influencer name + random numbers
    base = influencer_name.upper().replace(' ', '')[:8]
    random_part = ''.join(random.choices(string.digits, k=4))
    code = f"{base}{random_part}"
    return code

def create_influencer_promo(influencer_id, influencer_name, discount_percent=10, 
                           commission_rate=10, max_uses=None):
    """Create a new promo code for an influencer"""
    code = generate_promo_code(influencer_name)
    
    # Create in Stripe
    stripe_coupon = stripe.Coupon.create(
        percent_off=discount_percent,
        duration='once',  # Applies to first payment only
        name=f"{influencer_name} Promo",
        max_redemptions=max_uses
    )
    
    promo = PromoCode(
        code=code,
        influencer_id=influencer_id,
        influencer_name=influencer_name,
        discount_percent=discount_percent,
        commission_rate=commission_rate,
        max_uses=max_uses
    )
    promo.stripe_coupon_id = stripe_coupon.id
    promo_codes_db[code] = promo
    
    return promo

def validate_promo_code(code):
    """Check if a promo code is valid"""
    code = code.upper()
    if code not in promo_codes_db:
        return {'valid': False, 'error': 'Invalid promo code'}
    
    promo = promo_codes_db[code]
    
    if not promo.active:
        return {'valid': False, 'error': 'Promo code expired'}
        
    if promo.expires_at and promo.expires_at < datetime.utcnow():
        return {'valid': False, 'error': 'Promo code expired'}
        
    if promo.max_uses and promo.uses >= promo.max_uses:
        return {'valid': False, 'error': 'Promo code max uses reached'}
    
    return {
        'valid': True,
        'discount_percent': promo.discount_percent,
        'commission_rate': promo.commission_rate,
        'influencer_name': promo.influencer_name
    }

def apply_promo_to_subscription(promo_code, user_id, subscription_id, amount_paid):
    """Record a successful referral from a promo code"""
    promo = promo_codes_db.get(promo_code.upper())
    if not promo:
        return {'success': False, 'error': 'Promo code not found'}
    
    promo.uses += 1
    
    referral = PromoReferral(
        promo_code_id=promo.id,
        user_id=user_id,
        subscription_id=subscription_id,
        amount_paid=amount_paid
    )
    
    referrals_db[referral.id] = referral
    promo.referrals.append(referral)
    
    return {
        'success': True,
        'referral_id': referral.id,
        'commission_earned': referral.commission_earned
    }

def get_influencer_stats(influencer_id):
    """Get stats for an influencer dashboard"""
    total_earned = 0
    total_referrals = 0
    active_subs = 0
    
    for promo in promo_codes_db.values():
        if promo.influencer_id == influencer_id:
            total_referrals += promo.uses
            for referral in promo.referrals:
                if referral.is_active:
                    active_subs += 1
                    total_earned += referral.commission_earned
    
    return {
        'total_earned': total_earned,
        'total_referrals': total_referrals,
        'active_subscriptions': active_subs,
        'promo_codes': [
            {
                'code': p.code,
                'uses': p.uses,
                'max_uses': p.max_uses,
                'created_at': p.created_at.isoformat()
            }
            for p in promo_codes_db.values()
            if p.influencer_id == influencer_id
        ]
    }

def process_recurring_commission(subscription_id, amount_paid):
    """Process monthly commission for active referrals"""
    for referral in referrals_db.values():
        if referral.subscription_id == subscription_id and referral.is_active:
            # Calculate commission (10% of recurring payment)
            commission = amount_paid * 0.10
            referral.commission_earned += commission
            
            # Here you would actually pay the influencer via Stripe Connect
            # or track for manual payout
            
            return {
                'success': True,
                'commission_amount': commission,
                'referral_id': referral.id
            }
    
    return {'success': False, 'error': 'No active referral found'}
