"""Draws the app icon. Run once after changing it:  python packaging/make_icon.py

Writes src/v500capture/assets/icon.png (window icon, macOS app icon) and
packaging/icon.ico (Windows exe icon).
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
S = 1024


def draw() -> Image.Image:
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    # Scanner body
    d.rounded_rectangle((40, 40, S - 40, S - 40), radius=180, fill=(28, 72, 130))
    # Glass with a sample on it
    d.rounded_rectangle((150, 170, S - 150, S - 250), radius=40, fill=(222, 234, 246))
    d.ellipse((300, 300, 620, 620), fill=(96, 160, 72), outline=(40, 90, 40), width=18)
    # Glowing scan line
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(glow).rectangle((110, 470, S - 110, 530), fill=(120, 255, 170, 255))
    im.alpha_composite(glow.filter(ImageFilter.GaussianBlur(28)))
    d.rectangle((120, 488, S - 120, 512), fill=(235, 255, 240))
    # Clock badge: time-lapse
    cx, cy, r = S - 250, S - 250, 170
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255), outline=(28, 72, 130), width=26)
    d.line((cx, cy, cx, cy - 110), fill=(28, 72, 130), width=30)
    d.line((cx, cy, cx + 80, cy + 30), fill=(28, 72, 130), width=30)
    return im


def main() -> None:
    im = draw()
    png = ROOT / "src" / "v500capture" / "assets" / "icon.png"
    png.parent.mkdir(parents=True, exist_ok=True)
    im.resize((512, 512), Image.Resampling.LANCZOS).save(png)
    im.save(ROOT / "packaging" / "icon.ico",
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote", png, "and packaging/icon.ico")


if __name__ == "__main__":
    main()
