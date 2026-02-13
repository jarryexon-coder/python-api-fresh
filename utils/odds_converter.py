class OddsConverter:
    @staticmethod
    def american_to_decimal(american_odds):
        if american_odds > 0:
            return (american_odds / 100) + 1
        else:
            return (100 / abs(american_odds)) + 1
    
    @staticmethod
    def decimal_to_american(decimal_odds):
        if decimal_odds >= 2:
            return f"+{int((decimal_odds - 1) * 100)}"
        else:
            return f"-{int(100 / (decimal_odds - 1))}"
    
    @staticmethod
    def calculate_parlay_odds(legs_odds):
        """Calculate total parlay odds from individual legs"""
        decimal_odds = 1
        for odds in legs_odds:
            decimal_odds *= OddsConverter.american_to_decimal(odds)
        return OddsConverter.decimal_to_american(decimal_odds)
    
    @staticmethod
    def implied_probability(american_odds):
        """Calculate implied win probability"""
        if american_odds > 0:
            return 100 / (american_odds + 100)
        else:
            return abs(american_odds) / (abs(american_odds) + 100)
