from typing import Dict, List, Optional, Type
import importlib
import os
import glob

from .base_strategy import BaseStrategy, Signal, MarketData


class StrategyRegistry:
    """Registry for managing and loading strategies."""
    
    _strategies: Dict[str, Type[BaseStrategy]] = {}
    
    @classmethod
    def register(cls, strategy_class: Type[BaseStrategy]):
        """Register a strategy class."""
        cls._strategies[strategy_class.name] = strategy_class
        return strategy_class
    
    @classmethod
    def get(cls, name: str) -> Optional[Type[BaseStrategy]]:
        """Get strategy class by name."""
        return cls._strategies.get(name)
    
    @classmethod
    def list_strategies(cls) -> List[str]:
        """List all registered strategy names."""
        return list(cls._strategies.keys())
    
    @classmethod
    def create(cls, name: str, config: Dict = None) -> Optional[BaseStrategy]:
        """Create strategy instance by name."""
        strategy_class = cls.get(name)
        if strategy_class:
            return strategy_class(config)
        return None
    
    @classmethod
    def load_from_directory(cls, directory: str):
        """Auto-load all strategies from a directory."""
        # Find all Python files in strategies directory
        strategy_files = glob.glob(os.path.join(directory, "*.py"))
        
        for file_path in strategy_files:
            module_name = os.path.basename(file_path)[:-3]  # Remove .py
            if module_name.startswith('_'):
                continue
                
            try:
                # Import the module
                spec = importlib.util.spec_from_file_location(module_name, file_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                # Find strategy classes in the module
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (isinstance(attr, type) and 
                        issubclass(attr, BaseStrategy) and 
                        attr != BaseStrategy and
                        hasattr(attr, 'name')):
                        cls.register(attr)
                        print(f"Loaded strategy: {attr.name}")
                        
            except Exception as e:
                print(f"Error loading {module_name}: {e}")


class StrategyEngine:
    """Engine for running multiple strategies."""
    
    def __init__(self):
        self.strategies: Dict[str, BaseStrategy] = {}
        self.signals: List[Signal] = []
        
    def add_strategy(self, name: str, config: Dict = None):
        """Add a strategy to the engine."""
        strategy = StrategyRegistry.create(name, config)
        if strategy:
            self.strategies[name] = strategy
            print(f"Added strategy: {name}")
        else:
            print(f"Strategy not found: {name}")
    
    def remove_strategy(self, name: str):
        """Remove a strategy from the engine."""
        if name in self.strategies:
            del self.strategies[name]
    
    def run_all(self, data: MarketData) -> List[Signal]:
        """Run all strategies on market data."""
        signals = []
        
        for name, strategy in self.strategies.items():
            try:
                signal = strategy.generate_signal(data)
                if signal:
                    signals.append(signal)
            except Exception as e:
                print(f"Error in strategy {name}: {e}")
        
        self.signals.extend(signals)
        return signals
    
    def get_best_signal(self, data: MarketData) -> Optional[Signal]:
        """Get highest confidence signal from all strategies."""
        signals = self.run_all(data)
        
        if not signals:
            return None
        
        # Filter by minimum confidence
        valid_signals = [s for s in signals if s.confidence >= 0.6]
        
        if not valid_signals:
            return None
        
        return max(valid_signals, key=lambda s: s.confidence)
    
    def get_performance_report(self) -> Dict:
        """Get performance report for all strategies."""
        report = {}
        
        for name, strategy in self.strategies.items():
            report[name] = strategy.get_performance()
        
        return report
    
    def reset_all(self):
        """Reset all strategies."""
        for strategy in self.strategies.values():
            strategy.reset()
