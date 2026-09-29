"""Gera app/mudmap_studio/recursos/mudmap.ico (grãos minerais sobre fundo escuro)."""
from pathlib import Path

from PIL import Image, ImageDraw

DEST = Path(__file__).resolve().parent / "mudmap_studio" / "recursos"


def desenhar(s=512):
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    r = s * 0.2
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=r, fill=(28, 31, 35, 255))
    d.rounded_rectangle((s * .02, s * .02, s * .98, s * .98), radius=r * .9,
                        outline=(79, 181, 138, 255), width=max(2, s // 40))
    grãos = [((.18, .20, .56, .52), (47, 107, 87)), ((.50, .42, .86, .80), (63, 127, 95)),
             ((.20, .56, .46, .84), (242, 230, 168)), ((.58, .16, .80, .36), (217, 217, 217)),
             ((.40, .52, .54, .66), (156, 59, 46)), ((.66, .74, .78, .86), (90, 75, 107))]
    for (x0, y0, x1, y1), cor in grãos:
        d.ellipse((x0 * s, y0 * s, x1 * s, y1 * s), fill=(*cor, 255), outline=(15, 17, 20, 255),
                  width=max(1, s // 90))
    d.ellipse((s * .47, s * .47, s * .80, s * .80), outline=(255, 204, 63, 255), width=max(2, s // 28))
    d.line((s * .76, s * .76, s * .90, s * .90), fill=(255, 204, 63, 255), width=max(2, s // 22))
    return im


if __name__ == "__main__":
    DEST.mkdir(parents=True, exist_ok=True)
    im = desenhar()
    im.save(DEST / "mudmap.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    im.resize((256, 256), Image.LANCZOS).save(DEST / "mudmap.png")
    print("ícone:", DEST / "mudmap.ico")
