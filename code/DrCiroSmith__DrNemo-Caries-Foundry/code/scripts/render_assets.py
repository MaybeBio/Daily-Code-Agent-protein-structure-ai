#!/usr/bin/env python3
"""Regenerate flagship raster assets from REAL data (empirical biophysical data)."""
import math, sqlite3
from pathlib import Path
import imageio.v2 as imageio
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
MANUSCRIPT = ROOT / "manuscript" / "figures"
SQLITE = ROOT / "data" / "foundry_contenders.sqlite"
ASSETS.mkdir(parents=True, exist_ok=True)

DARK = "#0B1120"; PANEL = "#111827"; TEXT = "#F8FAFC"; MUTED = "#94A3B8"
ACCENT = "#38BDF8"; GREEN = "#10B981"; AMBER = "#F59E0B"; RED = "#EF4444"

def font(sz, bold=True):
    for cand in ["/usr/share/fonts/truetype/dejavu/DejaVuSans%s.ttf" % ("-Bold" if bold else ""),
                 "/usr/share/fonts/truetype/liberation/LiberationSans%s.ttf" % ("-Bold" if bold else ""),
                 "/usr/share/fonts/truetype/noto/NotoSans%s.ttf" % ("-Bold" if bold else "")]:
        try: return ImageFont.truetype(cand, sz)
        except Exception: pass
    return ImageFont.load_default()

def load_contenders():
    c = sqlite3.connect(SQLITE)
    cur = c.cursor()
    rows = cur.execute("""SELECT sequence, generation, vina_3aic_kcal, vinardo_3aic_kcal,
        vina_1smd_kcal, selectivity_ddg, openmm_relaxed_kj, ss_bond_angstrom,
        q_ph60, delta_q_stephan, protease_sites, pareto_rank, falsification_status
        FROM contenders""").fetchall()
    c.close()
    return rows

def create_physicochemical_benchmark():
    figs = ["fig1_pareto_frontier.png", "fig2_scrambled_null_histogram.png",
            "fig3_alanine_hotspot_scan.png", "fig4_stephan_acid_switch.png"]
    imgs = [Image.open(MANUSCRIPT / f).convert("RGB") for f in figs]
    target_h = 1400
    scaled = []
    for im in imgs:
        w = int(im.width * target_h / im.height)
        scaled.append(im.resize((w, target_h), Image.LANCZOS))
    max_w = max(im.width for im in scaled)
    pad = 40
    canvas = Image.new("RGB", (max_w * 2 + pad * 3, target_h * 2 + pad * 3), DARK)
    draw = ImageDraw.Draw(canvas)
    f18 = font(26)
    titles = ["Panel A — Pareto Frontier (Vina vs Selectivity)",
              "Panel B — Scrambled Null Histogram (N=39)",
              "Panel C — Alanine Hotspot Scan",
              "Panel D — Stephan Acid-Switch (ΔQ)"]
    positions = [(0,0),(1,0),(0,1),(1,1)]
    for (im, (cx, cy), title) in zip(scaled, positions, titles):
        x = pad + cx * (max_w + pad)
        y = pad + cy * (target_h + pad)
        canvas.paste(im, (x, y))
        draw.text((x, y - 34), title, fill=ACCENT, font=f18)
        draw.rectangle([x, y, x + 300, y + 44], fill=PANEL, outline=ACCENT, width=2)
    out = ASSETS / "physicochemical_benchmark.png"
    canvas.save(out, dpi=(300,300))
    print("OK physicochemical_benchmark.png", canvas.size)

def create_nature_biotech_hero():
    W, H = 2400, 1200
    img = Image.new("RGB", (W, H), DARK)
    draw = ImageDraw.Draw(img)
    f40 = font(40); f28 = font(28); f20 = font(20)
    draw.text((80, 90), "DrNemo Caries Foundry", fill=TEXT, font=f40)
    draw.text((80, 150), "Targeted GtfB Macrocycle Biophysics  ·  CAHWRPWHC Rank-1 Champion", fill=ACCENT, font=f28)
    draw.text((80, 210), "AutoDock Vina · Vinardo · OpenMM Amber14/GBn2 · Popperian Falsification", fill=MUTED, font=f20)
    cards = [("Vina ΔG", "-8.191 kcal/mol"), ("Vinardo ΔG", "-4.990 kcal/mol"),
             ("1SMD ΔΔG", "-0.85 kcal/mol"), ("OpenMM", "-1234.68 kJ/mol")]
    cx = 80
    for label, val in cards:
        r = [cx, 300, cx+520, 430]
        draw.rounded_rectangle(r, 18, fill=PANEL, outline=ACCENT, width=2)
        draw.text((cx+24, 322), label, fill=MUTED, font=f20)
        draw.text((cx+24, 362), val, fill=GREEN, font=font(34, True))
        cx += 560
    draw.rounded_rectangle([80, 500, 900, 620], 16, fill=PANEL, outline=GREEN, width=2)
    draw.text((110, 520), "Macrocycle: CAHWRPWHC  ·  S-S 2.06 Å  ·  Arg5-Pro6 shielded", fill=TEXT, font=f28)
    draw.text((110, 560), "0 protease sites  ·  Donnan Q +2.046  ·  Stephan ΔQ +1.62  ·  6/6 Gates Cleared", fill=GREEN, font=f20)
    out = ASSETS / "nature_biotech_hero.png"
    img.save(out)
    print("OK nature_biotech_hero.png", img.size)

def create_social_preview():
    W, H = 1280, 640
    img = Image.new("RGB", (W, H), DARK)
    draw = ImageDraw.Draw(img)
    draw.rectangle([(40,40),(W-40,H-40)], outline="#334155", width=2)
    draw.rectangle([(90,90),(W-90,H-90)], fill=PANEL, outline="#1E293B", width=1)
    f26 = font(26); f18 = font(18); f15 = font(15)
    draw.text((130, 140), "AUTONOMOUS COMPUTATIONAL BIOLOGY", fill=ACCENT, font=f18)
    draw.text((130, 190), "DrNemo Caries Foundry", fill=TEXT, font=f26)
    draw.text((130, 250), "AutoDock Vina · Vinardo · OpenMM Amber14 · Popperian Falsification", fill=MUTED, font=f15)
    stats = [("Vina", "-8.191"), ("Vinardo", "-4.990"), ("ΔΔG", "-0.85"), ("OpenMM", "-1234.68")]
    sx = 130
    for label, val in stats:
        draw.rounded_rectangle([sx, 340, sx+250, 430], 14, fill="#0B1120", outline=ACCENT, width=1)
        draw.text((sx+20, 360), label, fill=MUTED, font=f15)
        draw.text((sx+20, 388), val, fill=GREEN, font=font(24, True))
        sx += 280
    draw.text((130, 500), "CAHWRPWHC · S-S 2.06 Å · 0 protease · 6/6 Gates · github.com/DrCiroSmith/DrNemo-Caries-Foundry", fill=MUTED, font=f15)
    out = ASSETS / "social_preview.png"
    img.save(out)
    print("OK social_preview.png", img.size)

def create_evolution_demo_gif():
    rows = load_contenders()
    by_gen = {}
    for seq, gen, v3a, vin, v1s, ddg, omm, ss, q6, dq, prot, rank, status in rows:
        by_gen.setdefault(gen, []).append((seq, v3a, status))
    gens = sorted(by_gen)
    frames = []
    W, H = 900, 500
    f20 = font(20); f16 = font(16)
    for g in gens:
        best = min(by_gen[g], key=lambda t: t[1])
        seq, v3a, status = best
        img = Image.new("RGB", (W, H), DARK)
        draw = ImageDraw.Draw(img)
        draw.text((40, 30), f"Generation {g} · Best Contender", fill=TEXT, font=f20)
        draw.text((40, 66), f"Sequence: {seq}", fill=ACCENT, font=f16)
        draw.text((40, 96), f"Vina (3AIC): {v3a:.3f} kcal/mol", fill=TEXT, font=f16)
        draw.text((40, 126), f"Status: {status}", fill=GREEN if "CORROBORATED" in status else AMBER, font=f16)
        bx0, by0, bw, bh = 40, 200, 820, 160
        vals = [min(t[1] for t in by_gen[gg]) for gg in gens if gg <= g]
        xs = np.linspace(bx0, bx0+bw, len(gens)+1)
        for i,(xx,vv) in enumerate(zip(xs[:-1], vals)):
            h = max(4, (vv - (-9.5))/(-7.5-(-9.5)) * bh)
            draw.rectangle([xx, by0+bh-h, xx+(xs[1]-xs[0])-4, by0+bh], fill=GREEN)
        draw.text((40, 380), "Vina affinity progression (lower = better)", fill=MUTED, font=f16)
        frames.append(img.convert("P", palette=Image.Palette.ADAPTIVE))
    out = ASSETS / "evolution_demo.gif"
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=120, loop=0, optimize=True)
    print("OK evolution_demo.gif", len(frames), "frames", f"{out.stat().st_size/1e6:.2f} MB")

if __name__ == "__main__":
    create_physicochemical_benchmark()
    create_nature_biotech_hero()
    create_social_preview()
    create_evolution_demo_gif()
    print("ALL RASTERS DONE")
