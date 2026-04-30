
import importlib.metadata, platform, sys
print(f"--- SYSTEM: {platform.node()} ---")
packages = sorted([f"{dist.metadata['Name']}=={dist.version}" for dist in importlib.metadata.distributions()])
for p in packages: print(p)
