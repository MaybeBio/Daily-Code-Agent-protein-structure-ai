#!/usr/bin/env python

# Copyright AstraZeneca UK Ltd. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Inversion script.

To run with base.yaml as the config,

> python run_inversion.py

Adapted from run_inference.py (RFdiffusion) by Kevin Michalewicz (Imperial/UBA)

"""

import re
import os, time, pickle
import torch
from omegaconf import OmegaConf
import hydra
import logging
from rfdiffusion.util import writepdb_multi, writepdb
from rfdiffusion.inference import utils as iu
from rfdiffusion.chemical import seq2chars
from rfdiffusion.kinematics import get_init_xyz, xyz_to_t2d
from hydra.core.hydra_config import HydraConfig
import numpy as np
import torch.nn.functional as nn
import random
import glob
from adabelief_pytorch import AdaBelief
import sys

def make_deterministic(seed=0):
    torch.manual_seed(seed)
    np.random.seed(seed)
    random.seed(seed)


def tensors_are_finite(*tensors):
    return all(torch.isfinite(tensor).all().item() for tensor in tensors)


@hydra.main(version_base=None, config_path="../config/inference", config_name="base")
def main(conf: HydraConfig) -> None:
    log = logging.getLogger(__name__)
    conf.inference.deterministic = False
    if conf.inference.deterministic:
        print('Deterministic?')
        #make_deterministic()

    # Check for available GPU and print result of check
    if torch.cuda.is_available():
        device_name = torch.cuda.get_device_name(torch.cuda.current_device())
        log.info(f"Found GPU with device_name {device_name}. Will run RFdiffusion on {device_name}")
    else:
        log.info("////////////////////////////////////////////////")
        log.info("///// NO GPU DETECTED! Falling back to CPU /////")
        log.info("////////////////////////////////////////////////")

    # Initialize sampler and target/contig.
    sampler = iu.sampler_selector(conf)

    # Loop over number of designs to sample.
    design_startnum = sampler.inf_conf.design_startnum 
    if sampler.inf_conf.design_startnum == -1:
        existing = glob.glob(sampler.inf_conf.output_prefix + "*.pdb")
        indices = [-1]
        for e in existing:
            print(e)
            m = re.match(".*_(\d+)\.pdb$", e)
            print(m)
            if not m:
                continue
            m = m.groups()[0]
            indices.append(int(m))
        design_startnum = max(indices) + 1
    inverse_ms = True # False
    loss_fn = torch.nn.MSELoss()
    loss_fn_2 = torch.nn.MSELoss()
    x_init, seq_init = sampler.sample_init(inverse_ms=inverse_ms)
    original_roi_indices = sampler.mappings['con_ref_idx0'] 
    # original_roi_indices = sampler.mappings['complex_con_ref_idx0'] 
    len_roi_indices = len(original_roi_indices)
    pdb_coords = sampler.target_feats['xyz_27'] - torch.nanmean(
        sampler.target_feats['xyz_27'][original_roi_indices, :4, :], dim=(0, 1)
    ).view(1, 1, 3)

    # Initialise the msa, pair, and state embeddings
    if sampler.inf_conf.inversion_train:
        msa_prev = torch.zeros((1, len_roi_indices, 256), device=sampler.device, requires_grad=True)
        pair_prev = torch.zeros((1, len_roi_indices, len_roi_indices, 128), device=sampler.device, requires_grad=True)
        state_prev = torch.zeros((1, len_roi_indices, 64), device=sampler.device, requires_grad=True)
    else:
        msa_prev = torch.load(f'learnt_embeddings/msa_{sampler.inf_conf.input_pdb[11:-4]}.pt')
        state_prev = torch.load(f'learnt_embeddings/state_{sampler.inf_conf.input_pdb[11:-4]}.pt')
        pair_prev = torch.load(f'learnt_embeddings/pair_{sampler.inf_conf.input_pdb[11:-4]}.pt')
    loss_list = []  

    successful_designs = 0
    i_des = design_startnum
    while successful_designs < sampler.inf_conf.num_designs:
        if sampler.inf_conf.inversion_train:
            design_embeddings = (
                msa_prev.detach().clone(),
                pair_prev.detach().clone(),
                state_prev.detach().clone(),
            )

        #if conf.inference.deterministic:
            #make_deterministic(i_des)
        
        if not sampler.inf_conf.inversion_train:		
            g = torch.Generator(device='cpu').manual_seed(i_des)
            random_rate = (torch.randint(0, 21, (1,), generator=g) * 0.05).item()
            row_masking = bool(torch.randint(0, 2, (), generator=g))
        else:
            random_rate = 0
            row_masking = True

        start_time = time.time()
        #out_prefix = f"{sampler.inf_conf.input_pdb[11:-4]}_{sampler.inf_conf.output_prefix}_{i_des}"
        out_prefix = f"{sampler.inf_conf.input_pdb[11:-4]}_{sampler.inf_conf.output_prefix}_{i_des}"
        log.info(f"Making design {out_prefix} with random rate {random_rate} and {'row' if row_masking else 'column'} masking")
        if sampler.inf_conf.cautious and os.path.exists(out_prefix + ".pdb"):
            log.info(
                f"(cautious mode) Skipping this design because {out_prefix}.pdb already exists."
            )
            i_des += 1
            continue
        x_init, seq_init = sampler.sample_init(inverse_ms=inverse_ms)
        if not sampler.inf_conf.inversion_train:
            msa_prev = torch.load(f'learnt_embeddings/msa_{sampler.inf_conf.input_pdb[11:-4]}.pt')
            state_prev = torch.load(f'learnt_embeddings/state_{sampler.inf_conf.input_pdb[11:-4]}.pt')
            pair_prev = torch.load(f'learnt_embeddings/pair_{sampler.inf_conf.input_pdb[11:-4]}.pt')
        if i_des != design_startnum and sampler.inf_conf.inversion_train:
            x_init, seq_init = sampler.sample_init(inverse_ms=inverse_ms)
            prev_roi_indices = torch.clone(roi_indices)
        else:
            prev_roi_indices = torch.arange(len_roi_indices)
        
        roi_indices = sampler.mask_seq.nonzero()[:, 1]
        print("mask_seq shape:", sampler.mask_seq.shape)
        print("Number of True:", sampler.mask_seq.sum().item())
        print("Number of False:", (~sampler.mask_seq.bool()).sum().item())

        print("True indices:",
        sampler.mask_seq.squeeze().nonzero().squeeze().tolist())
        #if conf.inference.mutation_pos:
        #    seq_init[roi_indices[conf.inference.mutation_pos[0]], -1] = 1
        #    seq_init[roi_indices[conf.inference.mutation_pos[0]], :-1] = 0
            
        denoised_xyz_stack = []
        px0_xyz_stack = []
        seq_stack = []
        plddt_stack = []

        x_t = torch.clone(x_init).detach()
        seq_t = torch.clone(seq_init).detach()

        msa_prev = msa_prev.detach()
        pair_prev = pair_prev.detach()
        state_prev = state_prev.detach()
        
        msa_prev_ = torch.zeros((msa_prev.shape[0], seq_t.shape[0], msa_prev.shape[-1]), device=sampler.device)
        pair_prev_ = torch.zeros((pair_prev.shape[0], seq_t.shape[0], seq_t.shape[0], pair_prev.shape[-1]), device=sampler.device)
        state_prev_ = torch.zeros((state_prev.shape[0], seq_t.shape[0], state_prev.shape[-1]), device=sampler.device)

        msa_prev_[:, roi_indices,:] = msa_prev[:, prev_roi_indices,:] 
        pair_prev_[:, roi_indices, roi_indices, :] = pair_prev[:, prev_roi_indices, prev_roi_indices, :] 
        #pair_prev_[:, roi_indices.reshape(-1,1), roi_indices.reshape(1,-1), :] = pair_prev[:, prev_roi_indices.reshape(-1,1), prev_roi_indices.reshape(1,-1), :]
        state_prev_[:, roi_indices,:] = state_prev[:, prev_roi_indices,:]

        msa_prev = torch.clone(msa_prev_).clone().detach()
        pair_prev = torch.clone(pair_prev_).clone().detach()
        state_prev = torch.clone(state_prev_).clone().detach()

        if sampler.inf_conf.inversion_train:
            msa_prev.requires_grad_(True)
            pair_prev.requires_grad_(True)
            state_prev.requires_grad_(True)
            optimiser = torch.optim.SGD([msa_prev, pair_prev, state_prev], lr=4e-4, momentum=0.9)

        for param in sampler.model.parameters():
            param.requires_grad = False
        print(f'Rate is: {random_rate}')
        print("ROI length:", len(sampler.mappings['con_ref_idx0']))
        print("MSA:", msa_prev.shape)
        print("Pair:", pair_prev.shape)
        print("State:", state_prev.shape)
        sampler.prev_pred = None
        sample_failed = False
        failure_reason = ""
        loss_list_start = len(loss_list)
        # Loop over number of reverse diffusion time steps.
        for t in range(int(sampler.t_step_input), sampler.inf_conf.final_step - 1, -1):
            final_step = sampler.inf_conf.final_step
            msa_masked, msa_full, seq_in, xt_in, idx_pdb, t1d, t2d, xyz_t, alpha_t = sampler._preprocess(seq_t, x_t, t, inverse_ms=inverse_ms)
            if conf.inference.model_runner == 'default':
                N,L = msa_masked.shape[:2]
            else:
                B,N,L = xyz_t.shape[:3]
            
            xyz_t.detach_()
            msa_masked = msa_masked.detach()
            msa_full = msa_full.detach()
            seq_in = seq_in.detach()
            xt_in = xt_in.detach()
            idx_pdb = idx_pdb.detach()
            t1d = t1d.detach()
            t2d = t2d.detach()
            alpha_t = alpha_t.detach()
            ##################################
            ######## Str Self Cond ###########
            ##################################

            if conf.inference.model_runner == 'SelfConditioning':
                if (
                    (t < sampler.diffuser.T)
                    and (t != sampler.diffuser_conf.partial_T)
                    and sampler.prev_pred is not None
                ):
                    zeros = torch.zeros(B,1,L,24,3).float().to(xyz_t.device)
                    xyz_t = torch.cat((sampler.prev_pred.unsqueeze(1),zeros), dim=-2) # [B,T,L,27,3]
                    t2d_44   = xyz_to_t2d(xyz_t) # [B,T,L,L,44]
                else:
                    xyz_t = torch.zeros_like(xyz_t)
                    t2d_44   = torch.zeros_like(t2d[...,:44])
                # No effect if t2d is only dim 44
                t2d[...,:44] = t2d_44

            t2d_44.detach_()
            xyz_t.detach_()
            t2d = t2d.detach()
            if 'zeros' in locals():
                zeros = zeros.detach()

            if sampler.symmetry is not None:
                idx_pdb, sampler.chain_idx = sampler.symmetry.res_idx_procesing(res_idx=idx_pdb)

            ####################
            ### Forward Pass ###
            ####################



            _, _, px0, _, alpha, logits, plddt = sampler.model(msa_masked,
                                msa_full,
                                seq_in,
                                xt_in,
                                idx_pdb,
                                t1d=t1d,
                                t2d=t2d,
                                xyz_t=xyz_t,
                                alpha_t=alpha_t,
                                msa_prev=msa_prev,
                                pair_prev=pair_prev,
                                state_prev=state_prev,
                                t=torch.tensor(t),
                                return_infer=True,
                                motif_mask=sampler.mask_seq.squeeze(0), #sampler.diffusion_mask.squeeze().to(sampler.device),
                                k=random_rate,
                                inverse_ms=inverse_ms, seed=i_des, row_masking=row_masking,
                                use_checkpoint=True)

            if not tensors_are_finite(px0, alpha, logits, plddt):
                sample_failed = True
                failure_reason = f"non-finite model output at timestep {t}"
                break

            alpha = alpha.detach()
            logits = logits.detach()
            plddt = plddt.detach()
            log.info(f'pLDDT: {plddt.mean()}')
            print(plddt[0,roi_indices])
            log.info(f'pLDDT motif: {plddt[0,roi_indices].mean()}')
            log.info(f'pLDDT motif min: {plddt[0,roi_indices].min()}')
            if conf.inference.model_runner == 'SelfConditioning':
                sampler.prev_pred = torch.clone(px0).detach()

            # prediction of X0 
            _, px0  = sampler.allatom(torch.argmax(seq_in, dim=-1), px0, alpha)
            px0    = px0.squeeze()[:,:14]
            ###########################
            ### Generate Next Input ###
            ###########################

            if conf.inference.model_runner == 'SelfConditioning':
                seq_t_1 = torch.clone(seq_init)
                if t > final_step:
                    x_t_1, px0 = sampler.denoiser.get_next_pose(
                        xt=x_t,
                        px0=px0,
                        t=t,
                        pdb_coords=pdb_coords.detach(),
                        diffusion_mask=sampler.mask_str.squeeze(),
                        align_motif=sampler.inf_conf.align_motif,
                        include_motif_sidechains=sampler.preprocess_conf.motif_sidechain_input,
                        fix_motif=False,
                        original_roi_indices=original_roi_indices,
                        training=sampler.inf_conf.inversion_train,
                        inverse_ms=inverse_ms,
                    )
                    x_t_1 = x_t_1.detach()
                    sampler._log.info(
                            f'Timestep {t}, input to next step: { seq2chars(torch.argmax(seq_t_1, dim=-1).tolist())}')
                else:
                    x_t_1 = torch.clone(px0).to(x_t.device)
                    px0 = px0.to(x_t.device)

            if not tensors_are_finite(px0[:, :3], x_t_1[:, :3]):
                sample_failed = True
                failure_reason = f"non-finite backbone coordinates at timestep {t}"
                break

            if sampler.symmetry is not None:
                x_t_1, seq_t_1 = sampler.symmetry.apply_symmetry(x_t_1, seq_t_1)

            x_t_1 = x_t_1.detach()
            seq_t_1 = seq_t_1.detach()
            x_t = torch.clone(x_t_1)
            seq_t = torch.clone(seq_t_1).detach()

            px0_xyz_stack.append(torch.clone(px0).detach())
            denoised_xyz_stack.append(x_t)
            seq_stack.append(seq_t)
            plddt_stack.append(plddt[0].detach())  # remove singleton leading dimension


            # Optimising embeddings
            if not inverse_ms or not sampler.inf_conf.inversion_train:
                loss = loss_fn(px0[roi_indices,:4,:].to(sampler.device), pdb_coords[original_roi_indices,:4,:].detach().to(sampler.device)) 
            if inverse_ms and sampler.inf_conf.inversion_train:
                loss = 0.0 * loss_fn(px0[:, :4, :], pdb_coords[:, :4, :]) # pre-alignment penalisation, whole structures
                scaffold_indices = [i for i in range(pdb_coords.shape[0]) if i not in original_roi_indices]
                pdb_coords = pdb_coords.to(px0.device)

                # Extract coordinates
                pred_scaf = px0[scaffold_indices, :4, :].reshape(-1, 3)
                true_scaf = pdb_coords[scaffold_indices, :4, :].reshape(-1, 3)
                pred_roi_3d = px0[roi_indices, :4, :]  # shape: [L, 4, 3]
                true_roi_3d = pdb_coords[original_roi_indices, :4, :]  # same

                # Flattened versions for alignment only
                pred_roi_flat = pred_roi_3d.reshape(-1, 3)
                true_roi_flat = true_roi_3d.reshape(-1, 3)

                # Align predicted ROI using scaffold alignment
                pred_roi_aligned_flat = pred_roi_flat # testing 05/08/2025 (R @ pred_roi_flat.T).T + _t
                pred_roi_aligned = pred_roi_aligned_flat.reshape_as(pred_roi_3d)                 

                # RMSD loss (post-alignment)
                loss += 0.1 * loss_fn(pred_roi_aligned_flat, true_roi_flat) +  0.1 * loss_fn(pred_scaf, true_scaf) 

                # Optionally prevent gradient updates for scaffold atoms (if training full model)
                # testing 05/08/2025 with torch.no_grad():
                # testing 05/08/2025    px0[scaffold_indices, :14, :] = pdb_coords[scaffold_indices, :14, :]
                pred_ca = pred_roi_aligned[:, 1, :]  # [N, 3]
                true_ca = true_roi_3d[:, 1, :]          # [N, 3]

                dmat_pred = torch.cdist(pred_ca, pred_ca)  # [N, N]
                dmat_true = torch.cdist(true_ca, true_ca)  # [N, N]

                # You can also mask this to include only local distances (optional)
                loss += 0.025 * loss_fn(dmat_pred, dmat_true)  # Cα–Cα shape regularisation

                def compute_backbone_torsions(coords):
                    """
                    Compute phi and psi backbone torsion angles from coordinates.
                    Args:
                        coords: [L, 4, 3] tensor (N, CA, C, O) per residue.
                    Returns:
                        phi: [L-2] tensor
                        psi: [L-2] tensor
                    """
                    N, CA, C = coords[:-1, 0], coords[:-1, 1], coords[:-1, 2]
                    N_next = coords[1:, 0]
                    CA_next = coords[1:, 1]
                    C_prev = coords[:-2, 2]
                    N_mid = coords[1:-1, 0]
                    CA_mid = coords[1:-1, 1]
                    C_mid = coords[1:-1, 2]
                    N_next2 = coords[2:, 0]

                    def torsion(p0, p1, p2, p3):
                        b0 = -1.0 * (p1 - p0)
                        b1 = p2 - p1
                        b2 = p3 - p2
                        b1 = b1 / torch.norm(b1, dim=-1, keepdim=True)
                        v = b0 - (b0 * b1).sum(-1, keepdim=True) * b1
                        w = b2 - (b2 * b1).sum(-1, keepdim=True) * b1
                        x = (v * w).sum(-1)
                        y = torch.cross(b1, v, dim=-1) * w
                        y = y.sum(-1)
                        return torch.atan2(y, x)

                    phi = torsion(C_prev, N_mid, CA_mid, C_mid)
                    psi = torsion(N_mid, CA_mid, C_mid, N_next2)
                    return phi, psi

                def torsion_angle_loss(pred_coords, true_coords):
                    """
                    Compute torsion loss based on phi and psi angles.
                    Args:
                        pred_coords, true_coords: [L, 4, 3] tensors
                    Returns:
                        scalar loss
                    """
                    phi_pred, psi_pred = compute_backbone_torsions(pred_coords)
                    phi_true, psi_true = compute_backbone_torsions(true_coords)

                    loss_phi = torch.mean(1.0 - torch.cos(phi_pred - phi_true))
                    loss_psi = torch.mean(1.0 - torch.cos(psi_pred - psi_true))
                    return loss_phi + loss_psi                
                torsion_loss = torsion_angle_loss(px0[roi_indices, :4, :], pdb_coords[original_roi_indices, :4, :])
                loss += 0.2 * torsion_loss 

            if not tensors_are_finite(loss):
                sample_failed = True
                failure_reason = f"non-finite loss at timestep {t}"
                break

            loss_list.append(loss.item())
            if sampler.inf_conf.inversion_train:
                optimiser.zero_grad()
                loss.backward()
                optimiser.step()
            if t == 1 and sampler.inf_conf.inversion_train:
                torch.save(state_prev[:, roi_indices, :], f'learnt_embeddings/state_{sampler.inf_conf.input_pdb[11:-4]}.pt')
                torch.save(pair_prev[:, roi_indices.reshape(-1,1), roi_indices, :], f'learnt_embeddings/pair_{sampler.inf_conf.input_pdb[11:-4]}.pt')
                torch.save(msa_prev[:, roi_indices, :], f'learnt_embeddings/msa_{sampler.inf_conf.input_pdb[11:-4]}.pt')
                print(loss_list)

            torch.cuda.empty_cache()
            px0.detach_()
            
            print(f'Timestep {t}, loss: {loss.item()}')

        if sample_failed:
            del loss_list[loss_list_start:]
            if sampler.inf_conf.inversion_train:
                msa_prev, pair_prev, state_prev = (
                    embedding.detach().clone() for embedding in design_embeddings
                )
            log.warning(
                f"Discarding design {out_prefix} after {failure_reason}; "
                "generating a replacement sample"
            )
            i_des += 1
            continue

        # Flip order for better visualization in pymol
        denoised_xyz_stack = torch.stack(denoised_xyz_stack)
        denoised_xyz_stack = torch.flip(
            denoised_xyz_stack,
            [
                0,
            ],
        )
        px0_xyz_stack = torch.stack(px0_xyz_stack)
        px0_xyz_stack = torch.flip(
            px0_xyz_stack,
            [
                0,
            ],
        )

        # For logging -- don't flip
        plddt_stack = torch.stack(plddt_stack)

        # Save outputs
        os.makedirs(os.path.dirname(out_prefix), exist_ok=True)
        final_seq = seq_stack[-1]

        # Output glycines, except for motif region
        final_seq = torch.where(
            torch.argmax(seq_init, dim=-1) == 21, 7, torch.argmax(seq_init, dim=-1)
        )  # 7 is glycine

        bfacts = torch.ones_like(final_seq.squeeze())
        # make bfact=0 for diffused coordinates
        bfacts[torch.where(torch.argmax(seq_init, dim=-1) == 21, True, False)] = 0
        # pX0 last step
        out = f"{out_prefix}.pdb"

        # Now don't output sidechains
        if not inverse_ms:
            writepdb(
                out,
                denoised_xyz_stack[0, :, :4],
                final_seq,
                sampler.binderlen,
                chain_idx=sampler.chain_idx,
                bfacts=bfacts,
            )
        else:
            writepdb(
                out,
                denoised_xyz_stack[0, :, :14],
                final_seq,
                sampler.binderlen,
                chain_idx=sampler.chain_idx,
                bfacts=bfacts,
            )

        # run metadata
        trb = dict(
            config=OmegaConf.to_container(sampler._conf, resolve=True),
            plddt=plddt_stack.cpu().numpy(),
            device=torch.cuda.get_device_name(torch.cuda.current_device())
            if torch.cuda.is_available()
            else "CPU",
            time=time.time() - start_time,
        )
        if hasattr(sampler, "contig_map"):
            for key, value in sampler.contig_map.get_mappings().items():
                trb[key] = value
        log.info(f"Finished design in {(time.time()-start_time)/60:.2f} minutes")
        i_des += 1
        successful_designs += 1
        log.info(
            f"Completed {successful_designs}/{sampler.inf_conf.num_designs} "
            "successful designs"
        )


if __name__ == "__main__":
    main()