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

# This file has been modified from the original RFdiffusion project,
# Copyright (c) 2023 University of Washington, released under BSD 3-Clause.

# --- ORIGINAL LICENSE NOTICE ---
# Copyright (c) 2023 University of Washington
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#      * Redistributions of source code must retain the above copyright
#        notice, this list of conditions and the following disclaimer.
#      * Redistributions in binary form must reproduce the above copyright
#        notice, this list of conditions and the following disclaimer in the
#        documentation and/or other materials provided with the distribution.
#      * Neither the name of the [Organization] nor the
#        names of its contributors may be used used to endorse or promote products
#        derived from this software without specific prior written permission.

# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS “AS IS” 
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE 
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE 
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL 
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR 
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""
Inference script with masking.

To run with base.yaml as the config,

> python run_inference.py

To specify a different config,

> python run_inference.py --config-name symmetry

"""

import re
import os, time, pickle
import torch
from omegaconf import OmegaConf
import hydra
import logging
from rfdiffusion.util import writepdb_multi, writepdb
from rfdiffusion.inference import utils as iu
from hydra.core.hydra_config import HydraConfig
import numpy as np
import random
import glob


def make_deterministic(seed=0):
    torch.manual_seed(seed)
    np.random.seed(seed)
    random.seed(seed)


@hydra.main(version_base=None, config_path="../config/inference", config_name="base")
def main(conf: HydraConfig) -> None:
    log = logging.getLogger(__name__)
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
        
    inverse_ms = True
    for i_des in range(design_startnum, design_startnum + sampler.inf_conf.num_designs):
        if conf.inference.deterministic:
            make_deterministic(i_des)
        random_rate = 0.25
        start_time = time.time()
        out_prefix = f"{sampler.inf_conf.output_prefix}_{i_des}"
        log.info(f"Making design {out_prefix}")
        if sampler.inf_conf.cautious and os.path.exists(out_prefix + ".pdb"):
            log.info(
                f"(cautious mode) Skipping this design because {out_prefix}.pdb already exists."
            )
            continue

        x_init, seq_init = sampler.sample_init(inverse_ms=inverse_ms)
        original_roi_indices = sampler.mappings['con_ref_idx0'] 
        len_roi_indices = len(original_roi_indices)
        denoised_xyz_stack = []
        px0_xyz_stack = []
        seq_stack = []
        plddt_stack = []

        x_t = torch.clone(x_init)
        seq_t = torch.clone(seq_init)
        # Loop over number of reverse diffusion time steps.
        for t in range(int(sampler.t_step_input), sampler.inf_conf.final_step - 1, -1):
            if t == int(sampler.t_step_input) and i_des == design_startnum:
                pdb_coords = sampler.target_feats['xyz_27'] - torch.nanmean(sampler.target_feats['xyz_27'][original_roi_indices,:4,:], dim=(0,1)).view(1,1,3)
            px0, x_t, seq_t, plddt = sampler.sample_step(
                t=t, x_t=x_t, seq_init=seq_t, final_step=sampler.inf_conf.final_step, pdb_coords=pdb_coords, original_roi_indices=original_roi_indices, k=random_rate, inverse_ms=inverse_ms, seed=i_des,
            )
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
