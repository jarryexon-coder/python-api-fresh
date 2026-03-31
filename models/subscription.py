class Subscription:
    def __init__(self, user_id, plan_id, stripe_subscription_id, stripe_customer_id):
        self.user_id = user_id
        self.plan_id = plan_id
        self.stripe_subscription_id = stripe_subscription_id
        self.stripe_customer_id = stripe_customer_id
        self.status = 'active'
        self.current_period_start = None
        self.current_period_end = None
        self.cancel_at_period_end = False
