# Strategies package

# Base strategies
from strategies.news_volume_strategy import NewsVolumeStrategy, NewsVolumeStrategyConfig
from strategies.news_trend_strategy import NewsTrendStrategy, NewsTrendStrategyConfig

# Strategy subpackages (each has its own controller + runner)
# - strategies/volume_5pct/  - 5% volume, fixed 7-min exit
# - strategies/volume_10pct/ - 10% volume, fixed 7-min exit
# - strategies/trend/        - Trend-based entry/exit
