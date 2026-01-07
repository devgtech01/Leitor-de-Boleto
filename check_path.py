import sys
print("EXECUTABLE:", sys.executable)
print("PATH:")
for p in sys.path:
    print(p)
