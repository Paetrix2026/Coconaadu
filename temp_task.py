
import pkg_resources, platform, sys
print(f"--- SYSTEM: {platform.node()} ---")
print(f"Python: {sys.version.split()[0]}")
packages = sorted([f"{i.key}=={i.version}" for i in pkg_resources.working_set])
for p in packages: print(p)
