from PIL import Image
import os
import sys

def convert_png_to_ico(png_path, ico_path):
    try:
        img = Image.open(png_path)
        img.save(ico_path, format='ICO', sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])
        print(f"Successfully created {ico_path}")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python convert_icon.py <input.png> <output.ico>")
        sys.exit(1)
    convert_png_to_ico(sys.argv[1], sys.argv[2])
