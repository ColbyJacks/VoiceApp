"""Draws voiceapp.ico: the same blue ring as the tray icon."""

from pathlib import Path

from PIL import Image, ImageDraw

img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.ellipse([16, 16, 240, 240], fill="#7289da")
d.ellipse([80, 80, 176, 176], fill="#ffffff")
img.save(Path(__file__).with_name("voiceapp.ico"), sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
