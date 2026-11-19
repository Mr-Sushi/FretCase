"""Draw wiring.svg, the FretCase wiring diagram shown on the model page. Pins follow device/firmware/fretcase_controller/pins.h; run: python3 make_wiring.py"""
import html

W, H = 1600, 1110
FONT = "'PingFang SC','Hiragino Sans GB','Noto Sans CJK SC','Noto Sans SC','Microsoft YaHei',sans-serif"
C5, C33, CG, CSIG, CLED, CUSB, CPWR, CAUD, CAIR = '#c0392b', '#d97706', '#1f2328', '#2563a8', '#2f855a', '#6b7280', '#9b2c2c', '#6b46c1', '#7b8794'
out = []
def e(s): out.append(s)
def t(x, y, s, size=13, anchor='start', weight=400, fill='#1f2328'):
    e(f'<text x="{x}" y="{y}" font-size="{size}" text-anchor="{anchor}" font-weight="{weight}" fill="{fill}">{html.escape(s)}</text>')
def line(pts, color, w=1.6, dash=None):
    d = ' '.join(f'{x},{y}' for x, y in pts)
    da = f' stroke-dasharray="{dash}"' if dash else ''
    e(f'<polyline points="{d}" fill="none" stroke="{color}" stroke-width="{w}" stroke-linejoin="round" stroke-linecap="round"{da}/>')
def rect(x, y, w, h, fill='#ffffff', stroke='#1f2328', r=6, sw=1.4):
    e(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')
def dot(x, y, color, r=3):
    e(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{color}"/>')
def gnd(x, y):
    line([(x, y), (x, y + 8)], CG)
    for i, hw in enumerate((9, 6, 3)):
        line([(x - hw, y + 8 + i * 4), (x + hw, y + 8 + i * 4)], CG, 1.6)
def res(x, y, label, color):  # horizontal resistor box from x to x+46
    rect(x, y - 6, 46, 12, '#ffffff', color, 2, 1.4)
    t(x + 23, y - 10, label, 11, 'middle')

e(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="{FONT}">')
e(f'<rect width="{W}" height="{H}" fill="#fbf8f2"/>')

# legend
lx = 40
for color, name, dash, wdt in [(C5, '5 V', None, 2.4), (C33, '3.3 V', None, 2.4), (CG, '地 GND', None, 2.4), (CSIG, '控件信号', None, 2.4),
                               (CLED, '灯的数据', None, 2.4), (CUSB, 'USB 线', None, 5), (CPWR, '供电线', None, 5), (CAUD, '耳机音频', None, 2.4), (CAIR, '无线', '6 5', 2.4)]:
    line([(lx, 34), (lx + 30, 34)], color, wdt, dash); t(lx + 38, 39, name, 13); lx += 38 + 14 * len(name) + 40 if any(ord(ch) > 127 for ch in name) else 38 + 9 * len(name) + 36

# ---- Teensy ----
TX, TY, TW, TH = 600, 110, 180, 630
rect(TX, TY, TW, TH, '#e9f3ec', '#1f5c3a', 8, 2)
rect(TX + 70, TY - 12, 40, 14, '#c9ccd1', '#555', 2, 1)
t(TX + TW / 2, TY + 28, 'Teensy 4.1', 17, 'middle', 700, '#1f5c3a')
t(TX + TW / 2, TY + 46, '控制板', 13, 'middle', 400, '#1f5c3a')
left = []  # (y, pin, label)
y = 150 + 30
enc = [('0', '唱盘 A'), ('1', '唱盘 B'), ('2', '明暗 A'), ('3', '明暗 B'), ('4', '简繁 A'), ('5', '简繁 B'), ('6', '疏密 A'), ('7', '疏密 B'), ('8', '速度 A'), ('9', '速度 B')]
fad = [('14 / A0', '人声'), ('15 / A1', '旋律'), ('16 / A2', '吉他'), ('17 / A3', '贝斯'), ('18 / A4', '鼓'), ('19 / A5', '环境')]
keys = [('30', '采集'), ('31', '播放'), ('32', '撤销'), ('33', '换一个'), ('34', '人声键'), ('35', '旋律键'), ('36', '吉他键'), ('37', '贝斯键'), ('38', '鼓键'), ('39', '环境键')]
rows = {}
for grp, items in (('enc', enc), ('fad', fad), ('key', keys)):
    ys = []
    for pin, lab in items:
        ys.append(y); left.append((y, pin, lab)); y += 20
    rows[grp] = ys
    y += 20
for yy, pin, lab in left:
    line([(TX - 14, yy), (TX, yy)], '#1f5c3a', 2)
    t(TX + 10, yy + 4, pin, 12, 'start', 600, '#1f5c3a')

# right-side Teensy pins
RP = {'10': 190, '11': 230, '3.3V': 300, 'VUSB 5V': 340, 'GND': 380}
for lab, yy in RP.items():
    line([(TX + TW, yy), (TX + TW + 14, yy)], '#1f5c3a', 2)
    t(TX + TW - 10, yy + 4, lab, 12, 'end', 600, '#1f5c3a')

# ---- left: three groups ----
GX, GW = 330, 190
def group(ys, title, labels, color):
    y0, y1 = ys[0] - 22, ys[-1] + 14
    rect(GX, y0, GW, y1 - y0, '#ffffff', '#9aa5b1', 8, 1.2)
    t(GX + 12, y0 + 17, title, 13, 'start', 700)
    for yy, lab in zip(ys, labels):
        t(GX + GW - 10, yy + 4, lab, 12, 'end')
        line([(GX + GW, yy), (TX - 14, yy)], color, 1.6)
        dot(GX + GW, yy, color, 2.4)
group(rows['enc'], '编码器 ×5', [l for _, l in enc], CSIG)
group(rows['fad'], '推子 ×6', [l for _, l in fad], CSIG)
group(rows['key'], '按键 ×10', [l for _, l in keys], CSIG)

# details at far left
# encoder
ey = rows['enc'][0] + 30
e(f'<circle cx="120" cy="{ey}" r="22" fill="#ffffff" stroke="{CG}" stroke-width="1.6"/>')
t(120, ey + 5, 'EC', 13, 'middle', 700)
for dx, lab in ((-14, 'A'), (0, 'C'), (14, 'B')):
    line([(120 + dx, ey + 20), (120 + dx, ey + 40)], CG if lab == 'C' else CSIG, 1.6)
t(100, ey + 40, 'A', 12, 'end', 600, CSIG); t(140, ey + 40, 'B', 12, 'start', 600, CSIG)
gnd(120, ey + 40)
t(120, ey + 78, 'C', 12, 'middle', 600)
t(40, ey + 104, 'A、B 接 Teensy 引脚，', 12); t(40, ey + 122, '中间脚 C 接地；', 12); t(40, ey + 140, '编码器自带的按压开关不接。', 12)
# fader
fy = rows['fad'][0] + 40
line([(52, fy), (70, fy)], C33, 1.8); t(40, fy - 10, '3.3 V', 12, 'start', 600, C33)
rect(70, fy - 8, 110, 16, '#ffffff', CG, 2, 1.4)
line([(180, fy), (200, fy)], CG, 1.8); gnd(200, fy)
e(f'<polygon points="125,{fy + 9} 119,{fy + 19} 131,{fy + 19}" fill="{CSIG}"/>')
line([(125, fy + 19), (125, fy + 32), (250, fy + 32)], CSIG, 1.6); t(256, fy + 36, '引脚', 12, 'start', 400, CSIG)
t(40, fy + 58, '两端接 3.3 V 和地，推到顶的一端接 3.3 V；', 12); t(40, fy + 76, '滑片接引脚。不要接 5 V。', 12)
# key
ky = rows['key'][0] + 40
line([(60, ky), (100, ky)], CSIG, 1.6); t(40, ky - 10, '引脚', 12, 'start', 400, CSIG)
dot(100, ky, CG, 3); dot(150, ky, CG, 3)
line([(100, ky), (146, ky - 16)], CG, 1.8)
line([(150, ky), (190, ky)], CG, 1.6); gnd(190, ky)
t(40, ky + 50, '一脚接引脚，另一脚接地；', 12); t(40, ky + 68, 'Teensy 用内部上拉，按下读到低电平。', 12)
t(40, ky + 86, '机械轴插在 NeoKey 小板上：', 12); t(40, ky + 104, '用小板的 SW 和 GND 两个脚。', 12)

# ---- 74AHCT125, resistors, LEDs ----
LX = 860
rect(LX, 160, 140, 200, '#ffffff', CG, 6, 1.6)
t(LX + 70, 182, '74AHCT125', 14, 'middle', 700); t(LX + 70, 200, '电平转换 3.3 → 5 V', 11, 'middle')
for lab, yy in (('1A', 230), ('2A', 270)):
    t(LX + 8, yy + 4, lab, 12, 'start', 600)
for lab, yy in (('1Y', 230), ('2Y', 270), ('VCC', 300), ('GND', 318)):
    t(LX + 132, yy + 4, lab, 12, 'end', 600)
t(LX + 8, 340, '1OE–4OE 接地', 11); t(LX + 8, 354, '没用的 3A、4A 也接地', 11)
line([(TX + TW + 14, 190), (820, 190), (820, 230), (LX, 230)], CLED, 1.8)
line([(TX + TW + 14, 230), (810, 230), (810, 270), (LX, 270)], CLED, 1.8)
line([(LX + 140, 230), (1030, 230)], CLED, 1.8); res(1030, 230, '330 Ω', CLED)
line([(LX + 140, 270), (1030, 270)], CLED, 1.8); res(1030, 270, '330 Ω', CLED)
# ring
RCX, RCY, RR = 1260, 210, 58
e(f'<circle cx="{RCX}" cy="{RCY}" r="{RR + 12}" fill="#ffffff" stroke="#9aa5b1" stroke-width="1.2"/>')
import math
for i in range(16):
    a = -math.pi / 2 + i * 2 * math.pi / 16
    x, yy = RCX + RR * math.cos(a), RCY + RR * math.sin(a)
    e(f'<rect x="{x - 5:.1f}" y="{yy - 5:.1f}" width="10" height="10" rx="2" fill="#fde9b8" stroke="#b07a1a" stroke-width="1"/>')
t(RCX, RCY - 4, '灯环', 14, 'middle', 700); t(RCX, RCY + 14, '16 颗 WS2812B', 11, 'middle')
line([(1076, 230), (1120, 230), (1120, 128), (RCX, 128), (RCX, RCY - RR - 5)], CLED, 1.8)
e(f'<polygon points="{RCX - 4},{RCY - RR - 12} {RCX + 4},{RCY - RR - 12} {RCX},{RCY - RR - 5}" fill="{CLED}"/>')
t(RCX + 14, 124, 'DIN：最上面一颗，顺时针串', 11, 'start', 400, CLED)
# key chain
KX0, KY = 1112, 350
names = ['采集', '播放', '撤销', '换一个', '人声', '旋律', '吉他', '贝斯', '鼓', '环境']
for i, n in enumerate(names):
    x = KX0 + i * 44
    rect(x, KY - 14, 34, 28, '#fde9b8', '#b07a1a', 4, 1)
    t(x + 17, KY - 20, n, 11, 'middle')
    if i:
        line([(x - 10, KY), (x, KY)], CLED, 1.6)
line([(1076, 270), (1096, 270), (1096, KY), (KX0, KY)], CLED, 1.8)
t(KX0, KY + 32, '10 块 NeoKey 小板上的灯，按这个顺序串（DIN → DOUT）', 11, 'start', 400, CLED)

# 5 V and GND rails
R5, RG = 430, 452
line([(TX + TW + 14, 340), (840, 340), (840, R5), (1570, R5)], C5, 2.4)
line([(TX + TW + 14, 380), (830, 380), (830, RG), (1570, RG)], CG, 2.4)
t(852, R5 - 6, '5 V（来自 USB）', 12, 'start', 600, C5); t(852, RG + 18, '地（所有地线接在一起）', 12, 'start', 600, CG)
line([(LX + 140, 300), (1020, 300), (1020, R5)], C5, 1.6); dot(1020, R5, C5)
line([(LX + 140, 318), (1010, 318), (1010, RG)], CG, 1.6); dot(1010, RG, CG)
line([(1199, 244), (1104, 244), (1104, R5)], C5, 1.6); dot(1104, R5, C5)
line([(1203, 258), (1110, 258), (1110, RG)], CG, 1.6); dot(1110, RG, CG)
line([(1500, KY + 14), (1500, R5)], C5, 1.6); dot(1500, R5, C5)
line([(1516, KY + 14), (1516, RG)], CG, 1.6); dot(1516, RG, CG)
# capacitor across the rails
cx = 1150
line([(cx, R5), (cx, 437)], C5, 1.6); line([(cx - 9, 437), (cx + 9, 437)], CG, 2.2); line([(cx - 9, 445), (cx + 9, 445)], CG, 2.2); line([(cx, 445), (cx, RG)], CG, 1.6)
dot(cx, R5, C5); dot(cx, RG, CG)
t(cx + 14, 446, '1000 µF', 11)
# 3.3 V flag at the Teensy
line([(TX + TW + 14, 300), (806, 300)], C33, 1.8); t(810, 304, '3.3 V', 12, 'start', 600, C33); t(810, 318, '到推子', 11, 'start', 400, C33)

# ---- Raspberry Pi 5 ----
PXX, PYY, PWW, PHH = 1150, 560, 300, 190
rect(PXX, PYY, PWW, PHH, '#e8f2ea', '#2f7d4f', 8, 2)
t(PXX + PWW / 2, PYY + 30, 'Raspberry Pi 5', 17, 'middle', 700, '#2f7d4f')
t(PXX + PWW / 2, PYY + 50, '主机', 13, 'middle', 400, '#2f7d4f')
t(PXX + PWW - 10, PYY + 84, 'USB-A', 12, 'end', 600); t(PXX + PWW - 10, PYY + 124, 'USB-A', 12, 'end', 600)
t(PXX + 10, PYY + 154, 'USB-C 电源', 12, 'start', 600)
t(PXX + 46, PYY + 18, 'J2', 12, 'middle', 600); t(PXX + 150, PYY + 18, '', 12)
t(PXX + PWW / 2, PYY + PHH - 12, '蓝牙 · Wi-Fi', 12, 'middle', 400, '#2f7d4f')
# USB from Teensy
line([(TX + 90, TY - 12), (TX + 90, 70), (1585, 70), (1585, PYY + 80), (PXX + PWW, PYY + 80)], CUSB, 5)
t(1100, 62, 'USB：面板消息（MIDI）+ 给 Teensy 和灯供 5 V', 12, 'middle', 600, CUSB)
# GPS
rect(1470, PYY + 104, 104, 40, '#ffffff', CG, 6, 1.4); t(1522, PYY + 129, 'GPS（可选）', 12, 'middle', 600)
line([(1470, PYY + 120), (PXX + PWW, PYY + 120)], CUSB, 5)
# power button
BX, BY = 1196, 506
e(f'<circle cx="{BX}" cy="{BY}" r="15" fill="#f4efe4" stroke="{CG}" stroke-width="1.6"/>')
e(f'<circle cx="{BX}" cy="{BY}" r="9" fill="none" stroke="#f0b429" stroke-width="3"/>')
t(BX - 24, BY - 8, '电源键', 12, 'end', 600); t(BX - 24, BY + 9, '16 mm 带灯圈', 11, 'end')
line([(BX - 6, BY + 15), (BX - 6, PYY)], CG, 1.6); line([(BX + 6, BY + 15), (BX + 6, PYY)], CG, 1.6)
t(BX + 12, PYY - 6, '按键两脚 → J2 两个焊盘', 11)
line([(BX + 15, BY - 4), (1360, BY - 4), (1360, PYY)], C33, 1.6); t(1366, BY - 8, '灯圈 + → GPIO 1 号脚（3.3 V）', 11, 'start', 400, C33)
line([(BX + 15, BY + 4), (1340, BY + 4), (1340, PYY)], CG, 1.6); t(1366, BY + 18, '灯圈 − → GPIO 6 号脚（地）', 11, 'start', 400, CG)

# ---- bottom: power and audio ----
t(40, 812, '供电与音频', 16, 'start', 700)
rect(50, 880, 160, 50, '#ffffff', CG, 6, 1.4); t(130, 902, '箱侧 USB-C 充电口', 12, 'middle', 600); t(130, 920, '接 65 W 以上充电器', 11, 'middle')
AX, AY = 300, 840
rect(AX, AY, 260, 160, '#eceff2', '#26292d', 8, 2)
t(AX + 130, AY + 30, 'Anker 充电宝 A1695', 15, 'middle', 700); t(AX + 130, AY + 48, '25000 mAh / 90 Wh，边充边放', 11, 'middle')
t(AX + 10, AY + 69, 'USB-C 口（输入）', 12, 'start', 600)
t(AX + 250, AY + 89, '自带线 1', 12, 'end', 600); t(AX + 250, AY + 119, '自带线 2', 12, 'end', 600); t(AX + 250, AY + 149, 'USB-A', 12, 'end', 600)
line([(210, 905), (250, 905), (250, AY + 65), (AX, AY + 65)], CPWR, 5)
line([(AX + 260, AY + 85), (1120, AY + 85), (1120, PYY + 150), (PXX, PYY + 150)], CPWR, 5)
t(900, AY + 77, '5 V 3 A → Pi 5', 12, 'middle', 600, CPWR)
BKX = 640
rect(BKX, 940, 170, 50, '#ffffff', CG, 6, 1.4); t(BKX + 85, 962, 'Belkin 转接头', 12, 'middle', 600); t(BKX + 85, 980, 'USB-C 充电 + 3.5 mm', 11, 'middle')
line([(AX + 260, AY + 115), (600, AY + 115), (600, 955), (BKX, 955)], CPWR, 5)
rect(880, 940, 150, 50, '#ffffff', CG, 6, 1.4); t(955, 962, 'iPad 11 寸', 12, 'middle', 600); t(955, 980, '在箱盖里', 11, 'middle')
line([(BKX + 170, 965), (880, 965)], CPWR, 5)
# audio
rect(640, 1030, 270, 56, '#ffffff', CAUD, 6, 1.4); t(775, 1052, '10 kΩ 双联对数电位器（总音量）', 12, 'middle', 600, CAUD); t(775, 1070, '左右各一联：信号进一端，另一端接地，滑片出', 11, 'middle')
line([(BKX + 40, 990), (BKX + 40, 1030)], CAUD, 2.4)
t(BKX + 48, 1015, '3.5 mm 音频线', 11, 'start', 400, CAUD)
rect(940, 1030, 150, 56, '#ffffff', CAUD, 6, 1.4); t(1015, 1052, '箱侧耳机口', 12, 'middle', 600, CAUD); t(1015, 1070, '3.5 mm 面板延长线', 11, 'middle')
line([(910, 1058), (940, 1058)], CAUD, 2.4)
# instax
rect(1150, 940, 200, 56, '#ffffff', CG, 6, 1.4); t(1250, 962, 'Instax Link Wide', 12, 'middle', 600); t(1250, 980, '拍立得打印机', 11, 'middle')
line([(AX + 260, AY + 145), (580, AY + 145), (580, 1100), (1250, 1100), (1250, 996)], CPWR, 5)
t(1170, 1093, 'USB-A → 打印机补电', 11, 'middle', 600, CPWR)
# wireless
line([(1300, PYY + PHH), (1300, 940)], CAIR, 2.4, '6 5'); t(1308, 900, '蓝牙打印', 12, 'start', 600, CAIR)
line([(955, 940), (955, 640), (PXX, 640)], CAIR, 2.4, '6 5'); t(965, 632, 'Wi-Fi（同一个手机热点）', 12, 'start', 600, CAIR)

e('</svg>')
open(__import__('os').path.join(__import__('os').path.dirname(__import__('os').path.abspath(__file__)), 'wiring.svg'), 'w', encoding='utf-8').write('\n'.join(out) + '\n')
print('ok')
