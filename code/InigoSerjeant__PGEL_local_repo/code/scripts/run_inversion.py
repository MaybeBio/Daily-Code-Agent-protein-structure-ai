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


def make_deterministic(seed=0):
    torch.manual_seed(seed)
    np.random.seed(seed)
    random.seed(seed)


@hydra.main(version_base=None, config_path="../config/inference", config_name="base")
def main(conf: HydraConfig) -> None:
    log = logging.getLogger(__name__)
    conf.inference.deterministic = True
    if conf.inference.deterministic:
        make_deterministic()

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

    # None for first seen model
    msa_prev = None
    pair_prev = None
    state_prev = None
    roi_indices = range(10, 26) # use for motif scaffolding
    #roi_indices = range(8, 24) # uncomment for partial diffusion
    #roi_indices = range(99, 115) # uncomment for partial diffusion in cdr3
    for i_des in range(design_startnum, design_startnum + sampler.inf_conf.num_designs):
        if conf.inference.deterministic:
            make_deterministic(i_des)

        start_time = time.time()
        out_prefix = f"{sampler.inf_conf.output_prefix}_{i_des}"
        log.info(f"Making design {out_prefix}")
        if sampler.inf_conf.cautious and os.path.exists(out_prefix + ".pdb"):
            log.info(
                f"(cautious mode) Skipping this design because {out_prefix}.pdb already exists."
            )
            continue

        x_init, seq_init = sampler.sample_init()
        denoised_xyz_stack = []
        px0_xyz_stack = []
        seq_stack = []
        plddt_stack = []

        x_t = torch.clone(x_init)
        seq_t = torch.clone(seq_init)

        # Passing embeddings of previous iteration
        if msa_prev is not None:
            # Adapt embeddings to new sequence
            if msa_prev.shape[1] > seq_t.shape[0]:
                msa_prev = msa_prev[:, :seq_t.shape[0],:]
                pair_prev = pair_prev[:, :seq_t.shape[0], :seq_t.shape[0],:]
                state_prev = state_prev[:, :seq_t.shape[0],:]
            elif msa_prev.shape[1] < seq_t.shape[0]:
                msa_padding = torch.zeros((msa_prev.shape[0], seq_t.shape[0]-msa_prev.shape[1], msa_prev.shape[-1]), device=sampler.device)
                msa_prev = torch.cat((msa_prev, msa_padding), dim=1)

                pair_padding = torch.zeros((pair_prev.shape[0], seq_t.shape[0], seq_t.shape[0], pair_prev.shape[-1]), device=sampler.device)
                pair_padding[:, :pair_prev.shape[1], :pair_prev.shape[1], :] = pair_prev
                pair_prev = torch.clone(pair_padding)

                state_padding = torch.zeros((state_prev.shape[0], seq_t.shape[0]-state_prev.shape[1], state_prev.shape[-1]), device=sampler.device)
                state_prev = torch.cat((state_prev, state_padding), dim=1)
            # Masks
            mask_msa = torch.zeros_like(msa_prev, dtype=torch.bool) 
            mask_pair = torch.zeros_like(pair_prev, dtype=torch.bool)
            mask_state = torch.zeros_like(state_prev, dtype=torch.bool)

            mask_msa[:,roi_indices,:] = True
            mask_pair[:,roi_indices[0]:roi_indices[-1]+1,roi_indices[0]:roi_indices[-1]+1,:] = True
            mask_state[:,roi_indices,:] = True

            # We set to zero all the values that do not correspond to the region of interest (RF initialisation)
            msa_prev[~mask_msa] = 0
            pair_prev[~mask_pair] = 0
            state_prev[~mask_state] = 0

            #msa_prev = None
            #pair_prev = None
            #state_prev = None
            
        # Loop over number of reverse diffusion time steps.
        for t in range(int(sampler.t_step_input), sampler.inf_conf.final_step - 1, -1):
            #px0, x_t, seq_t, plddt = sampler.sample_step(
            #    t=t, x_t=x_t, seq_init=seq_t, final_step=sampler.inf_conf.final_step
            #)
            final_step = sampler.inf_conf.final_step
            msa_masked, msa_full, seq_in, xt_in, idx_pdb, t1d, t2d, xyz_t, alpha_t = sampler._preprocess(seq_t, x_t, t)

            if state_prev is not None:
                print(state_prev[:,roi_indices,:])

            if conf.inference.model_runner == 'default':
                N,L = msa_masked.shape[:2]
            else:
                B,N,L = xyz_t.shape[:3]

            ##################################
            ######## Str Self Cond ###########
            ##################################

            if conf.inference.model_runner == 'SelfConditioning':
                if (t < sampler.diffuser.T) and (t != sampler.diffuser_conf.partial_T):   
                    zeros = torch.zeros(B,1,L,24,3).float().to(xyz_t.device)
                    xyz_t = torch.cat((sampler.prev_pred.unsqueeze(1),zeros), dim=-2) # [B,T,L,27,3]
                    t2d_44   = xyz_to_t2d(xyz_t) # [B,T,L,L,44]
                else:
                    xyz_t = torch.zeros_like(xyz_t)
                    t2d_44   = torch.zeros_like(t2d[...,:44])
                # No effect if t2d is only dim 44
                t2d[...,:44] = t2d_44

            if sampler.symmetry is not None:
                idx_pdb, sampler.chain_idx = sampler.symmetry.res_idx_procesing(res_idx=idx_pdb)

            ####################
            ### Forward Pass ###
            ####################

            with torch.no_grad():
                msprev, pprev, px0, sprev, alpha, logits, plddt = sampler.model(msa_masked,
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
                                    motif_mask=sampler.diffusion_mask.squeeze().to(sampler.device))
            # Storing embeddings only if final step
            if t == final_step:
                msa_prev = msprev
                pair_prev = pprev
                state_prev = sprev
                #torch.save(pair_prev, f'pair_{i_des}_partial_cdr3.pt')
                #torch.save(state_prev, f'state_{i_des}_partial_cdr3.pt')

            if conf.inference.model_runner == 'SelfConditioning':
                sampler.prev_pred = torch.clone(px0)

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
                        diffusion_mask=sampler.mask_str.squeeze(),
                        align_motif=sampler.inf_conf.align_motif,
                        include_motif_sidechains=sampler.preprocess_conf.motif_sidechain_input,
                    )
                    sampler._log.info(
                            f'Timestep {t}, input to next step: { seq2chars(torch.argmax(seq_t_1, dim=-1).tolist())}')
                else:
                    x_t_1 = torch.clone(px0).to(x_t.device)
                    px0 = px0.to(x_t.device)

            #####################
            ### Get next pose ###
            #####################

            if conf.inference.model_runner == 'default':
                if t > final_step:
                    seq_t_1 = nn.one_hot(seq_t.to(torch.int64),num_classes=22).to(sampler.device)
                    x_t_1, px0 = sampler.denoiser.get_next_pose(
                        xt=x_t,
                        px0=px0,
                        t=t,
                        diffusion_mask=sampler.mask_str.squeeze(),
                        align_motif=sampler.inf_conf.align_motif,
                    )
                else:
                    x_t_1 = torch.clone(px0).to(x_t.device)
                    seq_t_1 = torch.clone(seq_t)
                    px0 = px0.to(x_t.device)

            if sampler.symmetry is not None:
                x_t_1, seq_t_1 = sampler.symmetry.apply_symmetry(x_t_1, seq_t_1)

            x_t = torch.clone(x_t_1)
            seq_t = torch.clone(seq_t_1)

            px0_xyz_stack.append(px0)
            denoised_xyz_stack.append(x_t)
            seq_stack.append(seq_t)
            plddt_stack.append(plddt[0])  # remove singleton leading dimension

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
        writepdb(
            out,
            denoised_xyz_stack[0, :, :4],
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
        with open(f"{out_prefix}.trb", "wb") as f_out:
            pickle.dump(trb, f_out)

        if sampler.inf_conf.write_trajectory:
            # trajectory pdbs
            traj_prefix = (
                os.path.dirname(out_prefix) + "/traj/" + os.path.basename(out_prefix)
            )
            os.makedirs(os.path.dirname(traj_prefix), exist_ok=True)

            out = f"{traj_prefix}_Xt-1_traj.pdb"
            writepdb_multi(
                out,
                denoised_xyz_stack,
                bfacts,
                final_seq.squeeze(),
                use_hydrogens=False,
                backbone_only=False,
                chain_ids=sampler.chain_idx,
            )

            out = f"{traj_prefix}_pX0_traj.pdb"
            writepdb_multi(
                out,
                px0_xyz_stack,
                bfacts,
                final_seq.squeeze(),
                use_hydrogens=False,
                backbone_only=False,
                chain_ids=sampler.chain_idx,
            )

        log.info(f"Finished design in {(time.time()-start_time)/60:.2f} minutes")


if __name__ == "__main__":
    main()
