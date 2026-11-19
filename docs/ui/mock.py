"""Mock of an Instax Wide song card: stylised colour front with a QR "stamp" and postmark."""
import sys, math
import cv2, numpy as np, qrcode
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1260, 840
SERIF = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"
SANS = "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc"

def font(path, size):
    try: return ImageFont.truetype(path, size, index=2)   # SC face in the collection
    except Exception: return ImageFont.truetype(path, size)

def cover(bgr):
    h, w = bgr.shape[:2]; s = max(W / w, H / h)
    r = cv2.resize(bgr, (math.ceil(w * s), math.ceil(h * s)), interpolation=cv2.INTER_LANCZOS4)
    y, x = (r.shape[0] - H) // 2, (r.shape[1] - W) // 2
    return r[y:y + H, x:x + W]

def film(b):  # "original": warm, slightly faded film look
    f = b.astype(np.float32) / 255
    f = 0.06 + 0.9 * f; f[..., 2] *= 1.05; f[..., 0] *= 0.93
    return np.clip(f * 255, 0, 255).astype(np.uint8)

def xieyi(b):  # watercolour-like
    s = cv2.stylization(b, sigma_s=80, sigma_r=0.45)
    paper = np.full_like(s, (225, 238, 246)); return cv2.addWeighted(s, 0.85, paper, 0.15, 0)

def comic(b):
    smooth = cv2.bilateralFilter(b, 9, 80, 80)
    z = (smooth // 48) * 48 + 24
    g = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)
    edges = cv2.adaptiveThreshold(cv2.medianBlur(g, 7), 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 9, 4)
    return cv2.bitwise_and(z, z, mask=edges)

def ink(b):
    g = cv2.cvtColor(cv2.edgePreservingFilter(b, flags=1, sigma_s=60, sigma_r=0.4), cv2.COLOR_BGR2GRAY)
    g = cv2.normalize(g, None, 20, 245, cv2.NORM_MINMAX)
    _, sketch = cv2.pencilSketch(b, sigma_s=40, sigma_r=0.08, shade_factor=0.04)
    sk = cv2.cvtColor(sketch, cv2.COLOR_BGR2GRAY)
    m = np.minimum(g, sk).astype(np.float32) / 255
    paper = np.array([214, 232, 240], np.float32) / 255  # BGR warm paper
    out = m[..., None] * paper[None, None, :]
    return (out * 255).astype(np.uint8)

STYLES = {"original": film, "xieyi": xieyi, "comic": comic, "ink": ink}

def stamp(url, city, date):
    S = 250
    st = Image.new("RGBA", (S, S + 30), (0, 0, 0, 0))
    d = ImageDraw.Draw(st)
    d.rectangle([0, 0, S - 1, S + 29], fill=(250, 246, 236, 255))
    r = 9  # perforations
    for x in range(r, S, 2 * r + 4):
        for y in (0, S + 29): d.ellipse([x - r, y - r, x + r, y + r], fill=(0, 0, 0, 0))
    for y in range(r, S + 30, 2 * r + 4):
        for x in (0, S - 1): d.ellipse([x - r, y - r, x + r, y + r], fill=(0, 0, 0, 0))
    q = qrcode.QRCode(border=1, box_size=1, error_correction=qrcode.constants.ERROR_CORRECT_M)
    q.add_data(url); q.make(fit=True)
    qi = q.make_image(fill_color=(52, 34, 22), back_color=(250, 246, 236)).convert("RGB")
    qi = qi.resize((190, 190), Image.NEAREST)
    st.paste(qi, ((S - 190) // 2, 26))
    d.text((S // 2, S + 4), "扫码听歌", font=font(SANS, 22), fill=(110, 70, 40), anchor="mm")
    return st

def postmark(city, date):
    P = 210
    pm = Image.new("RGBA", (P, P), (0, 0, 0, 0)); d = ImageDraw.Draw(pm)
    c = (120, 40, 30, 190)
    d.ellipse([6, 6, P - 6, P - 6], outline=c, width=5); d.ellipse([28, 28, P - 28, P - 28], outline=c, width=2)
    d.text((P // 2, P // 2 - 18), city, font=font(SERIF, 36), fill=c, anchor="mm")
    d.text((P // 2, P // 2 + 24), date, font=font(SANS, 22), fill=c, anchor="mm")
    for i in range(4):
        y = P // 2 - 30 + i * 20; d.line([(P - 4, y), (P + 120, y)], fill=c, width=3)
    return pm.rotate(-12, resample=Image.BICUBIC, expand=True)

def card(photo, style, title, line, city, date, url):
    b = cover(cv2.imread(photo))
    img = Image.fromarray(cv2.cvtColor(STYLES[style](b), cv2.COLOR_BGR2RGB)).convert("RGBA")
    shade = Image.new("L", (W, H), 0); sd = ImageDraw.Draw(shade)
    for y in range(H - 260, H): sd.line([(0, y), (W, y)], fill=int(170 * (y - (H - 260)) / 260))
    img = Image.composite(Image.new("RGBA", (W, H), (20, 12, 6, 255)), img, shade)
    d = ImageDraw.Draw(img)
    d.text((56, H - 150), title, font=font(SERIF, 76), fill=(250, 244, 230))
    d.text((60, H - 60), line, font=font(SANS, 30), fill=(235, 222, 200))
    img.alpha_composite(stamp(url, city, date), (W - 290, 40))
    pm = postmark(city, date); img.alpha_composite(pm, (W - 470, 205))
    return img.convert("RGB")

if __name__ == "__main__":
    out = sys.argv[1]; photos = sys.argv[2:]
    tiles = []
    for ph in photos:
        for st in STYLES:
            tiles.append(card(ph, st, "海边的傍晚", "海风把傍晚吹进歌里", "厦门", "2026.11.19", "https://fretcase.app/s/OXRpsZs7"))
    tw, th = W // 2, H // 2; cols = 4; rows = math.ceil(len(tiles) / cols)
    sheet = Image.new("RGB", (cols * (tw + 16) + 16, rows * (th + 16) + 16), (60, 42, 30))
    for i, t in enumerate(tiles):
        sheet.paste(t.resize((tw, th), Image.LANCZOS), (16 + (i % cols) * (tw + 16), 16 + (i // cols) * (th + 16)))
    sheet.save(out); tiles[2].save(out.replace(".png", "-full.png"))
    print(sheet.size)
