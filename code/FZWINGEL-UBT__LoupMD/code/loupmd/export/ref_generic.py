#!/usr/bin/env python3
"""float64 reference executor of a generic .loup bundle (the algorithm src/generic.cu implements), with autograd
forces and stress. Validates an export against the MACE model it came from:

  python ref_generic.py MODEL [--elements Z,..] [--head H]

Prints energy / force / stress differences of the bundle executor against MACE float64 on rattled test cells.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "1")

import numpy as np  # noqa: E402
import torch  # noqa: E402
from e3nn import o3  # noqa: E402

from . import generic as eg  # noqa: E402
from .bundle import read_bundle  # noqa: E402

torch.set_default_dtype(torch.float64)


def spline_eval(coef, grid, r):
    """coef [P, I, Q, 4] float32, grid [[a, b, n]], r [E] float64 -> per-pair tables evaluated: returns a function
    of the pair index tensor."""
    iv = torch.zeros(r.shape, dtype=torch.long)
    t = torch.zeros_like(r)
    off = 0
    for k, (a, b, n) in enumerate(grid):
        n = int(n)
        scale = n / (b - a)
        mask = (r >= a) if k else torch.ones_like(r, dtype=torch.bool)
        u = torch.clamp((r - a) * scale, min=0)
        i = torch.clamp(torch.floor(u).long(), 0, n - 1)
        iv = torch.where(mask, off + i, iv)
        t = torch.where(mask, u - i.to(r.dtype), t)
        off += n
    return iv, t


class Reference:
    def __init__(self, bundle_path, model_path):
        self.meta, T = read_bundle(bundle_path)
        self.T = {k: torch.as_tensor(np.array(v)) for k, v in T.items()}
        self.S = int(self.meta["S"])
        self.Z = [int(z) for z in self.meta["Z"].split(",")]
        self.L = int(self.meta["n_layers"])
        self.r_max = float(self.T["r_max"][0])
        _, m32, _, mc32 = eg.load_models(model_path)
        from ._fastmace import sc_factored, sc_generated

        factor = sc_factored.factor
        merged_terms, shape_of = sc_generated.merged_terms, sc_generated.shape_of

        self.progs = []
        for t in range(self.L):
            sc32 = mc32.products[t].symmetric_contractions
            sh = shape_of(sc32)
            prog, feats, _ = factor(merged_terms(sc32.etp.polynomial), sh[0], sh[1], sh[2])
            assert eg.product_signature(prog, feats, sh) == self.meta[f"L{t}.prod_sig"]
            self.progs.append((prog, feats, sh))

    def m(self, t, key):
        return int(self.meta[f"L{t}.{key}"])

    def energy(self, pos, cell, species, snd, rcv, shifts_frac, pos_lr=None):
        T = self.T
        N = pos.shape[0]
        vec = pos[rcv] - pos[snd] + shifts_frac @ cell
        r = vec.norm(dim=1)
        keep = r < self.r_max
        snd, rcv, vec, r = snd[keep], rcv[keep], vec[keep], r[keep]
        v = vec[:, [1, 2, 0]] if int(self.meta["sh_permute"]) else vec
        Y = o3.spherical_harmonics(list(range(4)), v, normalize=True, normalization="component")  # [E, 16]
        Yl = {l: Y[:, l * l:(l + 1) * (l + 1)] for l in range(4)}
        pair = species[snd] * self.S + species[rcv]
        lo, hi = torch.minimum(species[snd], species[rcv]), torch.maximum(species[snd], species[rcv])
        pair_sym = lo * self.S - (lo * (lo - 1)) // 2 + (hi - lo)
        E = T["e0"][species].sum()
        h = {0: T["embedding"].double()[species][:, None, :]}
        hs = []
        for t in range(self.L):
            p = f"L{t}."
            kind = self.m(t, "kind")
            lx, Cx = self.m(t, "lmax_x"), self.m(t, "C_x")
            sc = None
            if self.m(t, "has_sc"):
                sc = {}
                for l in range(self.m(t, "lmax_out") + 1):
                    key = p + f"W_sc_{l}"
                    if key in T and l in h:
                        W = T[key].double()
                        Ws = W[species] if W.shape[0] > 1 else W[0][None].expand(N, -1, -1)
                        sc[l] = torch.einsum("nmc,ncd->nmd", h[l], Ws)
            x = {l: h[l] @ T[p + f"W_up_{l}"].double() for l in range(lx + 1)}
            iv, tt = spline_eval(None, T[p + "grid"].tolist(), r)
            coef = T[p + "spline"].double()  # [P, I, cols, 4]
            c = coef[pair_sym if int(self.meta.get(p + "pair_sym", "0")) else pair, iv]  # [E, cols, 4]
            tt_ = tt[:, None]
            R = c[..., 0] + tt_ * (c[..., 1] + tt_ * (c[..., 2] + tt_ * c[..., 3]))
            if int(self.meta.get(p + "first_hidden", "0")):
                J = int(self.meta[p + "J"])
                Jp = J - 1
                S0 = torch.zeros(N, 16, self.S, Jp)
                val = R[:, None, :Jp] * Y[:, :, None]  # [E, 16, J']
                S0.index_put_((rcv[:, None].expand(-1, 16), torch.arange(16)[None, :].expand(len(rcv), -1),
                               species[snd][:, None].expand(-1, 16)), val, accumulate=True)
                D = torch.zeros(N).index_add_(0, rcv, R[:, -1])
                msg = {}
                for l3 in range(4):
                    s0l = S0[:, l3 * l3:(l3 + 1) * (l3 + 1)].reshape(N, 2 * l3 + 1, self.S * Jp)
                    msg[l3] = s0l @ T[p + f"first_C0_{l3}"].double()
            else:
                paths = eg.conv_paths(lx)
                mids = {l3: [] for l3 in range(4)}
                for k, (l1, l2, l3) in enumerate(paths):
                    W3 = o3.wigner_3j(l1, l2, l3)
                    xe = x[l1][snd]  # [E, d1, C]
                    val = torch.einsum("ijk,eic,ej->ekc", W3, xe, Yl[l2]) * R[:, k * Cx:(k + 1) * Cx][:, None, :]
                    agg = torch.zeros(N, 2 * l3 + 1, Cx).index_add_(0, rcv, val)
                    mids[l3].append(agg)
                D = torch.zeros(N).index_add_(0, rcv, R[:, -1])
                msg = {l3: torch.cat(mids[l3], dim=2) @ T[p + f"W_lin_{l3}"].double() for l3 in range(4)}
            if kind in (2, 3):
                msg = {l: v_ / (D[:, None, None] + 1.0) for l, v_ in msg.items()}
            if kind == 4:
                a, b = T[p + "alpha_beta"].tolist()
                msg = {l: v_ / (D[:, None, None] * b + a) for l, v_ in msg.items()}
                for l in range(lx + 1):
                    msg[l] = msg[l] + x[l] @ T[p + f"W_res_{l}"].double()
                C = self.m(t, "gate_C")
                cs, cg = T[p + "gate_c"].tolist()
                s0 = msg[0]
                out = {0: cs * torch.nn.functional.silu(s0[:, :, :C])}
                for l in range(1, 4):
                    g = cg * torch.sigmoid(s0[:, :, l * C:(l + 1) * C])
                    out[l] = msg[l] * g
                msg = {l: out[l] @ T[p + f"W_2_{l}"].double() for l in range(4)}
            if kind in (0, 2):
                msg = {l: torch.einsum("nmc,ncd->nmd", msg[l], T[p + f"W_skip_msg_{l}"].double()[species])
                       for l in range(4)}
            # product
            prog, feats, sh = self.progs[t]
            xs = [msg[l][:, m, :] for l in range(4) for m in range(2 * l + 1)]
            vals = prog.evaluate(xs)

            def get(u):
                return xs[-1 - u] if u < 0 else vals[u]

            w = T[p + "prod_w"].double()
            wsel = w[species] if w.shape[0] > 1 else w[0][None].expand(N, -1, -1)
            lo = self.m(t, "lmax_out")
            ycomp = [torch.zeros(N, msg[0].shape[2]) for _ in range((lo + 1) ** 2)]
            for b_, f in enumerate(feats):
                for cidx, u in (f or {}).items():
                    if u is not None:
                        ycomp[cidx] = ycomp[cidx] + wsel[:, b_, :] * get(u)
            hn = {}
            for l in range(lo + 1):
                y = torch.stack(ycomp[l * l:(l + 1) * (l + 1)], dim=1)
                hn[l] = y @ T[p + f"W_p_{l}"].double()
                if sc is not None and l in sc:
                    hn[l] = hn[l] + sc[l]
            h = hn
            hs.append(h)
            ro = self.m(t, "readout")
            if ro == 0:
                E = E + (h[0][:, 0, :] @ T[p + "ro_w"].double()).sum()
            elif ro in (1, 2):
                ac = float(T[p + "ro_act_c"][0])
                hid = ac * torch.nn.functional.silu(h[0][:, 0, :] @ T[p + "ro_W1"].double() + T[p + "ro_b1"].double())
                if ro == 2:
                    hid = ac * torch.nn.functional.silu(hid @ T[p + "ro_Wm"].double() + T[p + "ro_bm"].double())
                E = E + (hid @ T[p + "ro_W2"].double()).sum()
        if int(self.meta.get("has_lr", "0")):
            # The k-space terms see the strained positions, cell, reciprocal cell and volume (MACE PR 1718, as
            # FastMACE; the installed PolarMACE hands them the unstrained geometry, so its stress lacks this part)
            E = E + self.lr_energy(hs, species, pos, cell)
        if int(self.meta["has_zbl"]):
            cz = T["zbl_c"].double()
            pz = float(T["zbl_p"][0])
            pr_s = species[snd] * self.S + species[rcv]
            rc, inv_a, pref = T["zbl_r_cut"].double()[pr_s], T["zbl_inv_a"].double()[pr_s], T["zbl_pref"].double()[pr_s]
            u = r * inv_a
            phi = cz[0] * torch.exp(-3.2 * u) + cz[1] * torch.exp(-0.9423 * u) + cz[2] * torch.exp(-0.4028 * u) \
                + cz[3] * torch.exp(-0.2016 * u)
            s = r / rc
            env = 1 - (pz + 1) * (pz + 2) / 2 * s ** pz + pz * (pz + 2) * s ** (pz + 1) - pz * (pz + 1) / 2 * s ** (pz + 2)
            env = torch.where(r < rc, env, torch.zeros_like(env))
            E = E + (pref / r * phi * env).sum()
        return E

    # ------------------------------------------------------------------------------------------- POLAR
    def kvectors(self, cell):
        """graph_longrange.compute_k_vectors_flat for one cell (rcell = 2 pi inv(cell^T)): the integer set from the
        cell's value, the vectors differentiable in the cell."""
        kc = float(self.T["LR.kcut"][0])
        c = cell.detach()
        rcell_d = 2 * np.pi * torch.linalg.inv(c.T)
        rcell = 2 * np.pi * torch.linalg.inv(cell.T)
        normed = c / c.norm(dim=-1, keepdim=True)
        dots = (rcell_d * normed).sum(-1)
        n1, n2, n3 = [int(np.ceil(kc / float(d))) for d in dots]
        pts = [(0, 0, 0)]
        pts += [(0, 0, k) for k in range(1, n3)]
        pts += [(0, j, k) for j in range(1, n2) for k in range(-n3, n3)]
        pts += [(i, j, k) for i in range(1, n1) for j in range(-n2, n2) for k in range(-n3, n3)]
        kv = torch.tensor(pts, dtype=torch.float64) @ rcell
        k2 = (kv * kv).sum(-1)
        keep = k2.detach() <= kc * kc
        keep[0] = True
        return kv[keep], k2[keep]

    def basis(self, kv, k2, which):
        """GTOBasis: [K, n_sigma, 4, 2] (real, imag) Fourier coefficients."""
        T = self.T
        sig = T["LR.sigma_d" if which == "d" else "LR.sigma_f"].double()
        cl = T["LR.cl_d" if which == "d" else "LR.cl_f"].double()  # [n_sigma, 2]
        p0, p1 = T[f"LR.pref0_{which}"].double(), T[f"LR.pref1_{which}"].double()
        km = torch.sqrt(k2.clamp_min(0))
        km = torch.where(torch.arange(len(k2)) == 0, torch.zeros_like(km), km)
        ex = torch.exp(-0.5 * (km * km)[:, None] * (sig * sig)[None, :])  # [K, ns]
        f0 = p0 * ex * cl[:, 0]
        f1 = p1 * km[:, None] * ex * cl[:, 1]
        kp = kv[:, [1, 2, 0]]
        n = kp.norm(dim=-1, keepdim=True).clamp_min(1e-30)
        y0 = 1.0 / np.sqrt(4 * np.pi)
        y1 = np.sqrt(3.0 / (4 * np.pi)) * kp / n  # [K, 3]
        out = torch.zeros(len(k2), len(sig), 4, 2)
        out[:, :, 0, 0] = f0 * y0
        out[:, :, 1:, 1] = -f1[:, :, None] * y1[:, None, :]
        return out

    def lr_energy(self, hs, species, pos, cell):
        T = self.T
        C = int(self.meta["LR.C"])
        lmax = int(self.meta["LR.lmax"])
        N = pos.shape[0]
        vol = torch.linalg.det(cell).abs()
        kv, k2 = self.kvectors(cell)
        K = len(k2)
        theta = kv @ pos.T  # [K, N]
        cs, sn = torch.cos(theta), torch.sin(theta)
        Bd = self.basis(kv, k2, "d")[:, 0]  # [K, 4, 2]
        Bf = self.basis(kv, k2, "f")        # [K, 2, 4, 2]
        kappa = torch.where(torch.arange(K) == 0, torch.zeros_like(k2), 1.0 / k2.clamp_min(1e-30))
        wproj = torch.ones(K)
        wproj[0] = 0.5
        FC = float(T["LR.field_const"][0])
        tp3 = (2 * np.pi) ** 3

        def density(q):  # q [N, 4] -> rho [K, 2]
            Cc, Ss = cs @ q, sn @ q
            rr = (Bd[..., 0] * Cc).sum(-1) + (Bd[..., 1] * Ss).sum(-1)
            ri = (Bd[..., 1] * Cc).sum(-1) - (Bd[..., 0] * Ss).sum(-1)
            return torch.stack([rr, ri], -1) * tp3 / vol

        def features(q):  # [N, 4] -> [N, 8] (permuted, minus self-interaction)
            rho = density(q)
            V = rho * (FC * kappa)[:, None]
            Pr = Bf[..., 0].reshape(K, 8)
            Pi = Bf[..., 1].reshape(K, 8)
            A = (V[:, :1] * Pr + V[:, 1:] * Pi) * wproj[:, None]
            B = (V[:, :1] * Pi - V[:, 1:] * Pr) * wproj[:, None]
            f = 2.0 * (cs.T @ A + sn.T @ B) / tp3  # [N, 8] in (sigma, m) order
            f = f[:, T["LR.feat_perm"].long()]
            si = T["LR.feat_si"].double() * q[:, T["LR.feat_si_idx"].long()]
            return f - si

        def eng_rows(hd):  # {l: [N, 2l+1, C]} -> [N, rows]
            return torch.cat([hd[l].reshape(N, -1) for l in range(lmax + 1)], dim=1)

        def per_l(x):  # [N, rows] -> {l: [N, 2l+1, C]}
            out, o = {}, 0
            for l in range(lmax + 1):
                d = 2 * l + 1
                out[l] = x[:, o:o + d * C].reshape(N, d, C)
                o += d * C
            return out

        def silu_c(x, c):
            return c * torch.nn.functional.silu(x)

        def mlp(x, prefix, n):
            for k in range(n):
                x = x @ T[f"{prefix}W{k}"].double() + T[f"{prefix}b{k}"].double()
                if k < n - 1:
                    x = torch.nn.functional.layer_norm(x, (x.shape[-1],), T[f"{prefix}g{k}"].double(),
                                                       T[f"{prefix}beta{k}"].double(), 1e-5)
                    x = torch.nn.functional.silu(x)
            return x

        # sources, mixer
        q = torch.zeros(N, 8)
        fm = {l: torch.zeros(N, 2 * l + 1, C) for l in range(lmax + 1)}
        for t, h in enumerate(hs):
            q = q + eng_rows(h) @ T[f"LR.src_{t}"].double()
            for l in range(lmax + 1):
                fm[l] = fm[l] + h[l] @ T[f"LR.mix_{t}_{l}"].double()
        hl = hs[-1]
        # fukui
        def fukui_norm_apply(q, fk, Q):  # q [N, 8], fk [N, 2] (normalised per channel), Q [2]
            q = q.clone()
            tot = q[:, [0, 4]].sum(0)
            q[:, 0] = q[:, 0] + fk[:, 0] * (Q[0] / 2 - tot[0])
            q[:, 4] = q[:, 4] + fk[:, 1] * (Q[1] / 2 - tot[1])
            return q

        def normed(fk):
            s = fk.sum(0)
            s = torch.where(s == 0, torch.ones_like(s), s)
            return fk / s

        ac = float(T["LR.fk_act"][0])
        x = silu_c(hl[0][:, 0, :] @ T["LR.fk_W1"].double(), ac)
        x = silu_c(x @ T["LR.fk_Wm"].double() + T["LR.fk_bm"].double(), ac)
        fk = x @ T["LR.fk_W2"].double() + T["LR.fk_b2"].double()
        Qp = torch.tensor([0.0, 0.0])  # neutral, singlet: Q +- (S - 1) = 0
        q = fukui_norm_apply(q, normed(fk), Qp)
        q0 = q.clone()
        norms = T["LR.feat_norms"].double()
        pot = None
        for i in range(int(self.meta["LR.n_rec"])):
            p = f"LR.u{i}."
            fa = features(q[:, :4]) / norms
            fb = features(q[:, 4:]) / norms
            pot = torch.cat([fa, fb], dim=1)  # [N, 16]
            mixed = per_l(pot @ T[p + "Wpot"].double() + q @ T[p + "Wq"].double())
            for l in range(lmax + 1):
                mixed[l] = mixed[l] + fm[l] @ T[p + f"Wnf_{l}"].double()
            inv = sum((fm[l] * (mixed[l] @ T[p + f"dot_{l}"].double().T)).sum(1) for l in range(lmax + 1))
            emb = T[p + "src_emb"].double()[species]
            nl = mlp(torch.cat([inv, emb], dim=1), p + "mlp_", int(self.meta[p + "mlp_n"]))
            new = {l: fm[l] * (nl @ T[p + f"tpo_{l}"].double().T)[:, None, :] for l in range(lmax + 1)}
            H = int(self.meta[p + "ro_H"])
            cs_, cg_ = T[p + "ro_gate"].tolist()

            def gate(s0, v1):  # s0 [N, 2H] (scalars, gates), v1 [N, 3, H]
                return cs_ * torch.nn.functional.silu(s0[:, :H]), cg_ * torch.sigmoid(s0[:, H:])[:, None, :] * v1

            s0 = new[0][:, 0, :] @ T[p + "ro_W1_0"].double()
            v1 = new[1] @ T[p + "ro_W1_1"].double() if lmax >= 1 else torch.zeros(N, 3, H)
            a0, a1 = gate(s0, v1)
            s0 = a0 @ T[p + "ro_Wm_0"].double() + T[p + "ro_bm"].double()
            v1 = a1 @ T[p + "ro_Wm_1"].double()
            a0, a1 = gate(s0, v1)
            flat = torch.cat([a0, a1.transpose(1, 2).reshape(N, 3 * H)], dim=1)  # mul_ir of 32x0e+32x1o
            out = flat @ T[p + "ro_W2"].double() + T[p + "ro_b2"].double()  # [N, 10]
            q = q + out[:, :8]
            q = fukui_norm_apply(q, normed(out[:, 8:10]), Qp)
        E = torch.zeros(())
        if int(self.meta["LR.add_le"]):
            qin = q + q0
            qu = per_l(qin @ T["LR.le_Wq"].double())
            vu = per_l(pot @ T["LR.le_Wv"].double())
            qu[0] = qu[0] + T["LR.le_bq"].double()
            vu[0] = vu[0] + T["LR.le_bv"].double()
            dq = sum((hl[l] * (qu[l] @ T[f"LR.le_dotq_{l}"].double().T)).sum(1) for l in range(lmax + 1))
            dv = sum((hl[l] * (vu[l] @ T[f"LR.le_dotv_{l}"].double().T)).sum(1) for l in range(lmax + 1))
            E = E + mlp(torch.cat([dq, dv], dim=1), "LR.le_mlp_", int(self.meta["LR.le_mlp_n"])).sum()
        qt = q[:, :4] + q[:, 4:]
        rho = density(qt)
        V = rho * (FC * kappa)[:, None]
        E = E + 0.5 * vol * (2.0 * (rho * V).sum()) / (2 * np.pi) ** 6
        return E

    def evaluate(self, atoms):
        from ase.neighborlist import neighbor_list

        torch.set_default_dtype(torch.float64)  # MACE's loaders may have reset it
        i, j, S = neighbor_list("ijS", atoms, self.r_max)
        species = torch.as_tensor([self.Z.index(int(z)) for z in atoms.get_atomic_numbers()])
        pos0 = torch.as_tensor(atoms.positions)
        cell0 = torch.as_tensor(atoms.cell.array)
        eps = torch.zeros(3, 3, requires_grad=True)
        pos_in = pos0.clone().requires_grad_(True)
        F = torch.eye(3) + 0.5 * (eps + eps.T)
        pos = pos_in @ F
        cell = cell0 @ F
        e = self.energy(pos, cell, species, torch.as_tensor(i), torch.as_tensor(j), torch.as_tensor(S, dtype=torch.float64),
                        pos_lr=pos_in)
        gpos, geps = torch.autograd.grad(e, (pos_in, eps))
        vol = abs(float(np.linalg.det(atoms.cell.array)))
        return float(e), (-gpos).numpy(), (geps / vol).numpy()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--elements", default="8,22,38")
    ap.add_argument("--head", default=None)
    ap.add_argument("--bundle", default=None)
    ap.add_argument("--cif", default=None, help="test structure (repeated to >= 12 A, rattled) instead of the cube")
    a = ap.parse_args()
    from ase import Atoms
    from mace.calculators import MACECalculator

    zs = [int(z) for z in a.elements.split(",")]
    bundle = a.bundle or f"/tmp/ref_generic_{Path(a.model).stem}_{'_'.join(map(str, zs))}.loup"
    if not os.path.exists(bundle):
        eg.export_model(a.model, zs, Path(bundle), a.head)
    ref = Reference(bundle, a.model)
    rng = np.random.default_rng(0)
    # a rattled cubic cell holding every element
    n = 3
    sym = [zs[k % len(zs)] for k in range(n ** 3 * 2)]
    lat = np.array([[ix, iy, iz] for ix in range(n) for iy in range(n) for iz in range(n)], float) * 2.6
    pos = np.concatenate([lat, lat + 1.3])
    at = Atoms(numbers=sym, positions=pos + rng.normal(0, 0.08, pos.shape), cell=np.eye(3) * n * 2.6, pbc=True)
    if os.environ.get("REF_WRAP"):
        at.wrap()
    if a.cif:
        from ase.io import read as ase_read

        at = ase_read(a.cif)
        at = at.repeat([max(1, int(np.ceil(12.0 / h))) for h in at.cell.cellpar()[:3]])
        at.positions += rng.normal(0, 0.05, at.positions.shape)
    kw = {"head": ref.meta["head"]} if ref.meta["head"] not in ("default", "Default") else {}
    calc = MACECalculator(model_paths=a.model, device="cpu", default_dtype="float64", **kw)
    at.calc = calc
    e_m, f_m, s_m = at.get_potential_energy(), at.get_forces(), at.get_stress(voigt=False)
    e_r, f_r, s_r = ref.evaluate(at)
    print(f"atoms {len(at)}: dE/atom {abs(e_r - e_m) / len(at) * 1e3:.3e} meV, dF {np.abs(f_r - f_m).max():.3e} eV/A, "
          f"dS {np.abs(s_r - s_m).max():.3e} eV/A3 (|F| max {np.abs(f_m).max():.2f})")


if __name__ == "__main__":
    main()
