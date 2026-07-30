"""
Global EcoInsight configuration.
"""

# ==============================
# Collection
# ==============================

COLLECTION_INTERVAL_SECONDS = 5


# ==============================
# Environmental Model
# ==============================

DEFAULT_CARBON_INTENSITY = 600         # tunisie 0.6 kg CO₂e/kWh = 600 g CO₂e/kWh

CPU_TDP_WATTS = 65 #Intel Core i5-12400

RAM_MAX_POWER_WATTS = 4

SSD_MAX_POWER_WATTS = 5

NETWORK_MAX_POWER_WATTS = 3


# ==============================
# Recommendation thresholds
# ==============================

IDLE_THRESHOLD_SECONDS = 15 * 60

HIGH_CPU_THRESHOLD = 80

HIGH_MEMORY_THRESHOLD = 85

HIGH_DISK_ACTIVITY_MBPS = 100