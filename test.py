import sys
import os
from pathlib import Path

# 1. Restore console output
sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__

# 2. Load .env explicitly
env_file = Path("C:/friday/.env")
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()
    print("✅ .env loaded")
else:
    print("❌ .env not found")

# 3. Try to import backend and print the full error
print("\nAttempting to import 'backend'...")
try:
    import backend
    print("✅ backend imported successfully")
except Exception as e:
    print(f"❌ Import failed: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\nBackend seems healthy.")