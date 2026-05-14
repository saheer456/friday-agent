"""
system.py
Handles system resource monitoring using psutil.
"""
import psutil
import time

BOOT_TIME = psutil.boot_time()

def get_stats() -> dict:
    """Returns current CPU%, RAM%, and uptime."""
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        ram = psutil.virtual_memory()
        uptime_seconds = int(time.time() - BOOT_TIME)
        
        hours = uptime_seconds // 3600
        minutes = (uptime_seconds % 3600) // 60
        
        return {
            "cpu_percent": cpu_percent,
            "ram_percent": ram.percent,
            "ram_used_gb": round(ram.used / (1024**3), 1),
            "ram_total_gb": round(ram.total / (1024**3), 1),
            "uptime_formatted": f"{hours}h {minutes}m"
        }
    except Exception as e:
        return {
            "cpu_percent": 0.0,
            "ram_percent": 0.0,
            "ram_used_gb": 0.0,
            "ram_total_gb": 0.0,
            "uptime_formatted": "0h 0m",
            "error": str(e)
        }
