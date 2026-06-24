#!/usr/bin/env python3
import sys
import traceback

print("Starting test...", file=sys.stderr)

try:
    print("Importing openai...", file=sys.stderr)
    import openai
    print("✓ openai imported", file=sys.stderr)
    
    print("Importing base64...", file=sys.stderr)
    import base64
    print("✓ base64 imported", file=sys.stderr)
    
    print("Importing PIL...", file=sys.stderr)
    from PIL import ImageGrab
    print("✓ PIL imported", file=sys.stderr)
    
    print("Taking screenshot...", file=sys.stderr)
    img = ImageGrab.grab()
    print(f"✓ Screenshot grabbed: {img.size}", file=sys.stderr)
    
    img.save("screen.png")
    print("✓ Screenshot saved to screen.png", file=sys.stderr)
    
    print("\n=== SUCCESS: All operations completed ===\n")
    
except Exception as e:
    print(f"\n!!! ERROR: {type(e).__name__}: {e}", file=sys.stderr)
    traceback.print_exc()
    sys.exit(1)
