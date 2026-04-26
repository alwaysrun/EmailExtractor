import shutil
import sys
import os

print(f"sys.platform: {sys.platform}")
print(f"shutil.which('gemini'): {shutil.which('gemini')}")
print(f"shutil.which('gemini.cmd'): {shutil.which('gemini.cmd')}")
print(f"os.environ.get('PATH'): {os.environ.get('PATH')}")
