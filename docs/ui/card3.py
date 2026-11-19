"""Song card for an Instax Wide print: stylised photo on top, a paper strip below with title, place, date and a QR code."""
import cv2, numpy as np, qrcode, mock
from PIL import Image, ImageDraw

W, H, STRIP = 1260, 840, 230
PAPER = (247, 241, 228); INK = (58, 40, 28); MUTED = (128, 104, 84)

def note_icon(size, color):
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    s = size / 100
    d.ellipse([18*s, 62*s, 48*s, 86*s], fill=color)                 # head
    d.rectangle([42*s, 14*s, 49*s, 74*s], fill=color)               # stem
    d.polygon([(49*s, 14*s), (80*s, 28*s), (80*s, 42*s), (49*s, 30*s)], fill=color)  # flag
    return im

def qr_with_note(url, px):
    q = qrcode.QRCode(border=0, box_size=10, error_correction=qrcode.constants.ERROR_CORRECT_H)
    q.add_data(url); q.make(fit=True)
    img = q.make_image(fill_color=INK, back_color=PAPER).convert("RGBA").resize((px, px), Image.NEAREST)
    hole = int(px * 0.24); c = (px - hole) // 2
    d = ImageDraw.Draw(img); d.rounded_rectangle([c, c, c + hole, c + hole], radius=hole // 5, fill=PAPER)
    ic = note_icon(int(hole * 0.86), INK + (255,)); img.alpha_composite(ic, (c + (hole - ic.width) // 2, c + (hole - ic.height) // 2))
    return img

def card(photo, style, title, line, place, url):
    ph_h = H - STRIP
    b = cv2.imread(photo); h, w = b.shape[:2]; s = max(W / w, ph_h / h)
    r = cv2.resize(b, (int(np.ceil(w * s)), int(np.ceil(h * s))), interpolation=cv2.INTER_LANCZOS4)
    y, x = (r.shape[0] - ph_h) // 2, (r.shape[1] - W) // 2
    r = mock.STYLES[style](r[y:y + ph_h, x:x + W])
    out = Image.new("RGB", (W, H), PAPER)
    out.paste(Image.fromarray(cv2.cvtColor(r, cv2.COLOR_BGR2RGB)), (0, 0))
    d = ImageDraw.Draw(out)
    d.text((48, ph_h + 34), title, font=mock.font(mock.SERIF, 64), fill=INK)
    d.text((50, ph_h + 120), line, font=mock.font(mock.SANS, 28), fill=MUTED)
    d.text((50, ph_h + 168), place, font=mock.font(mock.SANS, 24), fill=MUTED)
    qr = qr_with_note(url, 178); out.paste(qr, (W - 48 - 178, ph_h + 26), qr)
    return out

if __name__ == "__main__":
    for st in mock.STYLES:
        c = card("../cardtest/coffee.png", st, "海边的傍晚", "海风把傍晚吹进歌里", "厦门 · 2026.11.19", "https://fretcase.example/s/OXRpsZs7")
        c.save(f"q_card_{st}.jpg", quality=90); c.resize((330, 220), Image.LANCZOS).save(f"q_thumb_{st}.jpg", quality=88)
    print("ok")
