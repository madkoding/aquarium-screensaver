"""Generates icon.ico (a little orange fish on blue water). Dev-only: needs Pillow."""
from PIL import Image, ImageDraw

S = 512
img = Image.new("RGB", (S, S))
px = img.load()
for y in range(S):                                  # water gradient
    for x in range(S):
        k = y / S
        px[x, y] = (int(20 + 10 * k), int(130 - 80 * k), int(190 - 80 * k))
d = ImageDraw.Draw(img)
d.polygon([(95, 256), (20, 170), (20, 342)], fill=(255, 130, 20))       # tail
d.ellipse([85, 160, 440, 352], fill=(255, 150, 30))                      # body
d.polygon([(190, 168), (260, 70), (320, 172)], fill=(235, 110, 15))     # dorsal fin
d.ellipse([360, 224, 400, 264], fill="white")
d.ellipse([374, 236, 394, 256], fill="black")
for cx, cy, r in ((120, 80, 14), (150, 40, 9), (90, 130, 8)):           # bubbles
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(220, 240, 255), width=4)
img.save("icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
