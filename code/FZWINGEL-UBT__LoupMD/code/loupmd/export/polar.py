"""MACE-POLAR-1's long-range part for the generic bundle (export_generic calls export_lr for PolarMACE models).

Exported (prefix "LR."), every linear map probed from the float64 modules so all normalisations are numeric:
  per layer t: src_{t}_{l} [C, 2] (EnvironmentDependentSpinSourceBlock: node features -> 2 spins x (q, mu)),
               mix_{t}_{l} [C, C] (MultiLayerFeatureMixer)
  fukui readout (NonLinearBiasReadoutBlock -> 2): fk_W1 [C, H], fk_act, fk_Wm [H, H], fk_bm [H], fk_W2 [H, 2], fk_b2 [2]
  GTO constants: sigma (density), feature sigmas, k-space cutoff, field constant, feature normalisation, self-
  interaction constants of the features, the basis prefactors
  per SCF step i: the AgnosticEmbeddedOneBodyVariableUpdate (potential / node / charge embeddings, the two sparse uvu
  products as plain matrices, source embedding per species, the LayerNorm MLP, the gated readout)
  local electron energy (OneBodyMLPFieldReadout)

Small per-atom vectors use e3nn's flat mul_ir layouts: charges [N, 8] = (q_a, mu_a, q_b, mu_b) with mu in e3nn's
l = 1 component order, potential features [N, 16] = (field_a [8], field_b [8]) with field = (0e w1, 0e w2, 1o w1, 1o w2).
"""
from __future__ import annotations

import math

import numpy as np
import torch
from e3nn import o3

from . import generic as eg

F32 = lambda x: x.detach().to(torch.float32).numpy()  # noqa: E731


def flat_linear(fn, irreps_in, irreps_out):
    """(W [dim_in, dim_out], b [dim_out]) of an equivariant linear map in flat mul_ir layout (probed)."""
    din = o3.Irreps(irreps_in).dim
    with torch.no_grad():
        b = fn(torch.zeros(1, din, dtype=torch.float64))[0]
        W = fn(torch.eye(din, dtype=torch.float64)) - b
    return W, b


def mlp_layers(radial_mlp):
    """[(W [in, out], b [out], ln_gamma, ln_beta, eps) ...] of a MACE RadialMLP (Linear -> LayerNorm -> SiLU)*, Linear."""
    mods = list(radial_mlp.net.children())
    out, i = [], 0
    while i < len(mods):
        lin = mods[i]
        assert isinstance(lin, torch.nn.Linear)
        entry = dict(W=lin.weight.detach().double().T.contiguous(), b=lin.bias.detach().double())
        if i + 1 < len(mods) and isinstance(mods[i + 1], torch.nn.LayerNorm):
            ln = mods[i + 1]
            entry.update(g=ln.weight.detach().double(), beta=ln.bias.detach().double(), eps=float(ln.eps))
            assert isinstance(mods[i + 2], torch.nn.SiLU)
            i += 3
        else:
            i += 1
        out.append(entry)
    return out


def sparse_uvu(tp):
    """{l: M [C1, C2]} of a SparseUvuTensorProduct with 1-dim paths: mode 0 (l x l -> 0):
    out_u = sum_l sum_d x1[u, l, d] (x2_l[d, :] @ M_l^T)[u]; mode 1 (l x 0 -> l): out_l[u, d] = x1_l[u, d] (s @ M_l^T)[u]."""
    assert tp.layout == "mul_ir"
    assert bool((tp.output_mask == 1).all())
    out, modes = {}, set()
    for (i1s, i1e, i2s, i2e, os_, oe, ws, we, pw, mode, mul1, mul2, d1) in tp._path_meta:
        l = (d1 - 1) // 2
        w = tp.weight.detach().double()[ws:we].view(mul1, mul2)
        out[l] = pw * w / math.sqrt(d1)
        if d1 > 1:  # for 1-dim paths both forms are the same product x1[u] sum_v w[u, v] x2[v]
            modes.add(mode)
    assert len(modes) <= 1
    return out, (modes.pop() if modes else None)


def _put_mlp(T, prefix, layers):
    for k, e in enumerate(layers):
        T[f"{prefix}W{k}"] = F32(e["W"])
        T[f"{prefix}b{k}"] = F32(e["b"])
        if "g" in e:
            T[f"{prefix}g{k}"] = F32(e["g"])
            T[f"{prefix}beta{k}"] = F32(e["beta"])
            assert abs(e["eps"] - 1e-5) < 1e-12
    return len(layers)


@torch.no_grad()
def export_lr(m, cols, T, meta, hidden_irreps):
    hidden = o3.Irreps(hidden_irreps)
    C = eg.single_mul(hidden)
    lmax = eg.lmax_of(hidden)
    L = len(m.interactions)
    assert m.atomic_multipoles_max_l == 1 and m.field_feature_max_l == 1
    assert len(m.field_feature_widths) == 2
    assert not m.field_si and m.include_electrostatic_self_interaction
    assert not m.quadrupole_feature_corrections
    assert m.coulomb_energy.include_self_interaction
    charges = o3.Irreps(str(m.charges_irreps))
    assert charges == o3.Irreps("1x0e+1x1o+1x0e+1x1o"), charges
    pot = o3.Irreps(str(m.potential_irreps))
    assert pot.dim == 16, pot
    meta.update({"LR.n_rec": int(m.num_recursion_steps), "LR.add_le": int(bool(m.add_local_electron_energy)),
                 "LR.C": C, "LR.lmax": lmax})
    # per-layer sources and mixer
    for t in range(L):
        Ws, bs = flat_linear(m.lr_source_maps[t].linear, hidden, charges)
        assert bs.abs().max() == 0 and not m.lr_source_maps[t].zero_charges
        T[f"LR.src_{t}"] = to_engine_rows(Ws, hidden)  # [rows of engine layout, 8]
        mix = eg.probe_linear(m.layer_feature_mixer.linears[t], hidden, hidden)
        for l in range(lmax + 1):
            T[f"LR.mix_{t}_{l}"] = F32(mix[l][0])
    # fukui readout
    fk = m.fukui_source_map
    p1 = eg.probe_linear(fk.linear_1, hidden, fk.linear_1.irreps_out)
    T["LR.fk_W1"] = F32(p1[0][0])
    T["LR.fk_act"] = np.array([eg.act_constant(fk.non_linearity, torch.nn.functional.silu)])
    pm = eg.probe_linear(fk.linear_mid, fk.linear_mid.irreps_in, fk.linear_mid.irreps_out)
    T["LR.fk_Wm"] = F32(pm[0][0])
    T["LR.fk_bm"] = F32(pm[0][1])
    p2 = eg.probe_linear(fk.linear_2, fk.linear_2.irreps_in, fk.linear_2.irreps_out)
    T["LR.fk_W2"] = F32(p2[0][0])
    T["LR.fk_b2"] = F32(p2[0][1])
    # GTO constants
    epd = m.electric_potential_descriptor
    db, fb = epd.density_basis, epd.feature_basis
    assert db.sigmas == [float(m.atomic_multipoles_smearing_width)]
    T["LR.sigma_d"] = np.array(db.sigmas, np.float64)
    T["LR.sigma_f"] = np.array(fb.sigmas, np.float64)
    T["LR.kcut"] = np.array([float(m.kspace_cutoff)])
    from graph_longrange.utils import FIELD_CONSTANT

    T["LR.field_const"] = np.array([FIELD_CONSTANT])
    T["LR.feat_norms"] = m.field_feature_norms.double().numpy()
    si = epd.self_interaction_terms
    T["LR.feat_si"] = si.overlap_constants.double().numpy()
    T["LR.feat_si_idx"] = si.select_indices.numpy().astype(np.int32)
    T["LR.feat_perm"] = epd.output_permutation.numpy().astype(np.int32)
    T["LR.cl_d"] = db.cl_scale.double().numpy()  # [1, 2]
    T["LR.cl_f"] = fb.cl_scale.double().numpy()  # [2 sigmas, 2 l]
    for name, basis in (("d", db), ("f", fb)):
        rad = basis.radial_spline
        T[f"LR.pref0_{name}"] = rad.pref0.double().numpy()
        T[f"LR.pref1_{name}"] = rad.pref1.double().numpy()
    assert m.coulomb_energy.density_basis.sigmas == db.sigmas
    # SCF update blocks
    for i, u in enumerate(m.field_dependent_charges_maps):
        p = f"LR.u{i}."
        pe = u.potential_embedding
        Wp, bp = flat_linear(pe.potential_linear, pot, hidden)
        Wq, bq = flat_linear(pe.charge_embedding, charges, hidden)
        assert bp.abs().max() == 0 and bq.abs().max() == 0
        T[p + "Wpot"] = to_engine_cols(Wp, hidden)  # [16, rows]
        T[p + "Wq"] = to_engine_cols(Wq, hidden)    # [8, rows]
        nf = eg.probe_linear(pe.node_feats_linear, hidden, hidden)
        for l in range(lmax + 1):
            T[p + f"Wnf_{l}"] = F32(nf[l][0])
        dot, mode = sparse_uvu(u.dot_products)
        assert mode in (0, None)
        for l in range(lmax + 1):
            T[p + f"dot_{l}"] = F32(dot[l])
        tpo, mode = sparse_uvu(u.tp_out)
        assert mode in (1, None)
        for l in range(lmax + 1):
            T[p + f"tpo_{l}"] = F32(tpo[l])
        se = eg.probe_linear(u.source_embedding, o3.Irreps(f"{len(m.atomic_numbers)}x0e"), u.source_embedding.irreps_out)
        T[p + "src_emb"] = F32(se[0][0][cols])
        meta[p + "mlp_n"] = _put_mlp(T, p + "mlp_", mlp_layers(u.nonlinearity))
        r = u.readout
        r1 = eg.probe_linear(r.linear_1, hidden, r.linear_1.irreps_out)
        nl_irreps = o3.Irreps(str(r.linear_1.irreps_out))  # 64x0e+32x1o
        H = eg.per_l_mul(nl_irreps)[1]
        meta[p + "ro_H"] = H
        for l in range(lmax + 1):
            if l in r1:
                T[p + f"ro_W1_{l}"] = F32(r1[l][0])
        T[p + "ro_gate"] = np.array(eg.gate_constants(r.equivariant_nonlin, nl_irreps, H))
        rm = eg.probe_linear(r.linear_mid, r.linear_mid.irreps_in, r.linear_mid.irreps_out)
        T[p + "ro_Wm_0"] = F32(rm[0][0])
        T[p + "ro_bm"] = F32(rm[0][1])
        T[p + "ro_Wm_1"] = F32(rm[1][0])
        W2, b2 = flat_linear(r.linear_2, r.linear_2.irreps_in, r.linear_2.irreps_out)
        T[p + "ro_W2"] = F32(W2)  # [32x0e+32x1o flat (128), 10]
        T[p + "ro_b2"] = F32(b2)
    # local electron energy
    le = m.local_electron_energy
    Wq, bq = flat_linear(le.linear_up_q, charges, hidden)
    Wv, bv = flat_linear(le.linear_up_v, pot, hidden)
    T["LR.le_Wq"] = to_engine_cols(Wq, hidden)
    T["LR.le_bq"] = F32(bq[:C])
    T["LR.le_Wv"] = to_engine_cols(Wv, hidden)
    T["LR.le_bv"] = F32(bv[:C])
    assert (bq[C:].numel() == 0 or bq[C:].abs().max() == 0) and (bv[C:].numel() == 0 or bv[C:].abs().max() == 0)
    for name, tp in (("q", le.dot_products_q), ("v", le.dot_products_v)):
        d, mode = sparse_uvu(tp)
        assert mode in (0, None)
        for l in range(lmax + 1):
            T[f"LR.le_dot{name}_{l}"] = F32(d[l])
    meta["LR.le_mlp_n"] = _put_mlp(T, "LR.le_mlp_", mlp_layers(le.mlp))


def engine_rows(irreps):
    """Flat mul_ir index of every engine-layout row (l, m, c) in order (l ascending, then m, then c)."""
    idx = {}
    for mul, l, _, off in eg.blocks(irreps):
        for u in range(mul):
            for mm in range(2 * l + 1):
                idx.setdefault(l, {})[(mm, u)] = off + u * (2 * l + 1) + mm
    rows = []
    for l in sorted(idx):
        C = max(u for _, u in idx[l]) + 1
        for mm in range(2 * l + 1):
            for u in range(C):
                rows.append(idx[l][(mm, u)])
    return rows


def to_engine_rows(W, irreps):
    """[dim_in(mul_ir), k] -> [dim_in(engine order), k]"""
    return F32(W[engine_rows(irreps)])


def to_engine_cols(W, irreps):
    """[k, dim_out(mul_ir)] -> [k, dim_out(engine order)]"""
    return F32(W[:, engine_rows(irreps)])
