from typing import Optional

from core.base_strategy import BaseStrategy, Signal, MarketData


class SentimentStrategy(BaseStrategy):
    """
    News & Social Media Sentiment Strategy
    
    Uses sentiment analysis from news and social media.
    Buys on bullish sentiment, sells on bearish.
    """
    
    name = "sentiment"
    description = "Trade based on news and social media sentiment"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        config = config or {}
        self.min_confidence = self.config.get('min_sentiment_confidence', 0.7)
        self.contrarian = self.config.get('contrarian', False)  # Bet against extreme sentiment
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        sentiment = data.sentiment
        confidence = data.sentiment_confidence
        
        if confidence < self.min_confidence:
            return None
        
        if self.contrarian:
            # Contrarian: bet against extreme sentiment
            if sentiment == "bullish" and confidence > 0.8:
                return Signal(
                    strategy=self.name,
                    signal="down",
                    confidence=confidence * 0.8,
                    reason=f"Contrarian: Extreme bullish sentiment ({confidence:.1%})",
                    metadata={'sentiment': sentiment, 'confidence': confidence, 'contrarian': True}
                )
            elif sentiment == "bearish" and confidence > 0.8:
                return Signal(
                    strategy=self.name,
                    signal="up",
                    confidence=confidence * 0.8,
                    reason=f"Contrarian: Extreme bearish sentiment ({confidence:.1%})",
                    metadata={'sentiment': sentiment, 'confidence': confidence, 'contrarian': True}
                )
        else:
            # Trend following: follow sentiment
            if sentiment == "bullish":
                return Signal(
                    strategy=self.name,
                    signal="up",
                    confidence=confidence,
                    reason=f"Bullish sentiment ({confidence:.1%})",
                    metadata={'sentiment': sentiment, 'confidence': confidence, 'contrarian': False}
                )
            elif sentiment == "bearish":
                return Signal(
                    strategy=self.name,
                    signal="down",
                    confidence=confidence,
                    reason=f"Bearish sentiment ({confidence:.1%})",
                    metadata={'sentiment': sentiment, 'confidence': confidence, 'contrarian': False}
                )
        
        return None
