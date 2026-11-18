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

import torch
import torch.nn as nn
from rfdiffusion.Embeddings import MSA_emb, Extra_emb, Templ_emb, Recycling
from rfdiffusion.Track_module import IterativeSimulator
from rfdiffusion.AuxiliaryPredictor import DistanceNetwork, MaskedTokenNetwork, ExpResolvedNetwork, LDDTNetwork
from opt_einsum import contract as einsum

class RoseTTAFoldModule(nn.Module):
    def __init__(self, 
                 n_extra_block, 
                 n_main_block, 
                 n_ref_block,
                 d_msa,
                 d_msa_full,
                 d_pair,
                 d_templ,
                 n_head_msa,
                 n_head_pair,
                 n_head_templ,
                 d_hidden,
                 d_hidden_templ,
                 p_drop,
                 d_t1d,
                 d_t2d,
                 T, # total timesteps (used in timestep emb
                 use_motif_timestep, # Whether to have a distinct emb for motif
                 freeze_track_motif, # Whether to freeze updates to motif in track
                 SE3_param_full={'l0_in_features':32, 'l0_out_features':16, 'num_edge_features':32},
                 SE3_param_topk={'l0_in_features':32, 'l0_out_features':16, 'num_edge_features':32},
                 input_seq_onehot=False,     # For continuous vs. discrete sequence
                 ):

        super(RoseTTAFoldModule, self).__init__()

        self.freeze_track_motif = freeze_track_motif

        # Input Embeddings
        d_state = SE3_param_topk['l0_out_features']
        self.latent_emb = MSA_emb(d_msa=d_msa, d_pair=d_pair, d_state=d_state,
                p_drop=p_drop, input_seq_onehot=input_seq_onehot) # Allowed to take onehotseq
        self.full_emb = Extra_emb(d_msa=d_msa_full, d_init=25,
                p_drop=p_drop, input_seq_onehot=input_seq_onehot) # Allowed to take onehotseq
        self.templ_emb = Templ_emb(d_pair=d_pair, d_templ=d_templ, d_state=d_state,
                                   n_head=n_head_templ,
                                   d_hidden=d_hidden_templ, p_drop=0.25, d_t1d=d_t1d, d_t2d=d_t2d)


        # Update inputs with outputs from previous round
        self.recycle = Recycling(d_msa=d_msa, d_pair=d_pair, d_state=d_state)
        #
        self.simulator = IterativeSimulator(n_extra_block=n_extra_block,
                                            n_main_block=n_main_block,
                                            n_ref_block=n_ref_block,
                                            d_msa=d_msa, d_msa_full=d_msa_full,
                                            d_pair=d_pair, d_hidden=d_hidden,
                                            n_head_msa=n_head_msa,
                                            n_head_pair=n_head_pair,
                                            SE3_param_full=SE3_param_full,
                                            SE3_param_topk=SE3_param_topk,
                                            p_drop=p_drop)
        ##
        self.c6d_pred = DistanceNetwork(d_pair, p_drop=p_drop)
        self.aa_pred = MaskedTokenNetwork(d_msa)
        self.lddt_pred = LDDTNetwork(d_state)
       
        self.exp_pred = ExpResolvedNetwork(d_msa, d_state)

    def forward(self, msa_latent, msa_full, seq, xyz, idx, t,
                t1d=None, t2d=None, xyz_t=None, alpha_t=None,
                msa_prev=None, pair_prev=None, state_prev=None,
                return_raw=False, return_full=False, return_infer=False,
                use_checkpoint=False, motif_mask=None, i_cycle=None, n_cycle=None, k=None, inverse_ms=False, seed=0, row_masking=True):

        B, N, L = msa_latent.shape[:3]
        drop_rate = k
        if k != 0 or not row_masking:
            g = torch.Generator(device='cpu').manual_seed(seed)
        if not row_masking:
            p = int((1-drop_rate) * len((~motif_mask).nonzero())) # column masking
            perm = torch.randperm(len((~motif_mask).nonzero()), generator=g) # column masking
            r_cols = torch.take((~motif_mask).nonzero().squeeze().to('cpu'), perm[:p]) # column masking
            print(r_cols)
        elif k != 0 or not row_masking:
            r_rows_latent = torch.randperm(msa_latent.shape[-1], generator=g)[:int((1-drop_rate) * msa_latent.shape[-1])] # row masking
            r_rows_full = torch.randperm(msa_full.shape[-1], generator=g)[:int((1-drop_rate) * msa_full.shape[-1])] # row masking

        if k != 0 or not row_masking:
            msa_latent_mask = torch.zeros_like(msa_latent, dtype=bool).requires_grad_(False)
            msa_latent_mask[:, :, motif_mask, :] = 1 #modify for zero/random embeddings  
        if not row_masking and k != 0:
            msa_latent_mask[:, :,  sorted(r_cols), :] = 1 # column masking
        elif k != 0:
            msa_latent_mask[:, :,  (~motif_mask).nonzero(), r_rows_latent] = 1 # row masking
        if k != 0 or not row_masking:
            msa_full_mask = torch.zeros_like(msa_full, dtype=bool).requires_grad_(False)
            msa_full_mask[:, :, motif_mask, :] = 1 #modify for zero/random embeddings 
        if not row_masking:
            msa_full_mask[:, :, sorted(r_cols), :] = 1 # column masking
        elif k != 0:
            msa_full_mask[:, :, (~motif_mask).nonzero(), r_rows_full] = 1 # row masking
        #msa_latent[:, :, ~motif_mask, :] += 8 * torch.randn_like(msa_latent[:, :, ~motif_mask, :]).requires_grad_(False) 
        #msa_full[:, :, ~motif_mask, :] += 8 * torch.randn_like(msa_full[:, :, ~motif_mask, :]).requires_grad_(False) 


        # Get embeddings
        if k != 0:
            msa_latent, pair, state = self.latent_emb(msa_latent * msa_latent_mask, seq, idx)
            msa_full = self.full_emb(msa_full * msa_full_mask, seq, idx)

        else:
            msa_latent, pair, state = self.latent_emb(msa_latent, seq, idx)
            msa_full = self.full_emb(msa_full, seq, idx)
        roi_indices = motif_mask.nonzero()

        ############# DIM CONSERVATION STARTS HERE ################
        if not row_masking:
            p = int((1-drop_rate) * len((~motif_mask).nonzero())) # column masking
            perm = torch.randperm(len((~motif_mask).nonzero()), generator=g) # column masking
            r_cols = torch.take((~motif_mask).nonzero().squeeze().to('cpu'), perm[:p]) # column masking
            print(r_cols)
        elif k != 0:
            r_rows_latent = torch.randperm(msa_latent.shape[-1], generator=g)[:int((1-drop_rate) * msa_latent.shape[-1])] # row masking
            r_rows_full = torch.randperm(msa_full.shape[-1], generator=g)[:int((1-drop_rate) * msa_full.shape[-1])] # row masking

        if k != 0:
            msa_latent_mask = torch.zeros_like(msa_latent, dtype=bool).requires_grad_(False)
            msa_latent_mask[:, :, motif_mask, :] = 1 #modify for zero/random embeddings  
        if not row_masking and k != 0:
            msa_latent_mask[:, :,  sorted(r_cols), :] = 1 # column masking
        elif k != 0:
            msa_latent_mask[:, :,  (~motif_mask).nonzero(), r_rows_latent] = 1 # row masking
        if k != 0:
            msa_full_mask = torch.zeros_like(msa_full, dtype=bool).requires_grad_(False)
            msa_full_mask[:, :, motif_mask, :] = 1 #modify for zero/random embeddings 
        if not row_masking:
            msa_full_mask[:, :, sorted(r_cols), :] = 1 # column masking
        elif k != 0:
            msa_full_mask[:, :, (~motif_mask).nonzero(), r_rows_full] = 1 # row masking
        ############# DIM CONSERVATION ENDS HERE ################

        if msa_prev == None:
            msa_prev = torch.zeros_like(msa_latent[:,0])
            pair_prev = torch.zeros_like(pair)
            state_prev = torch.zeros_like(state)
        msa_mask = torch.zeros_like(msa_latent[:,0], dtype=bool).requires_grad_(False)
        pair_mask = torch.zeros_like(pair, dtype=bool).requires_grad_(False)
        state_mask = torch.zeros_like(state, dtype=bool).requires_grad_(False)
        t1d_mask = torch.zeros_like(t1d, dtype=bool).requires_grad_(False)
        t2d_mask = torch.zeros_like(t2d, dtype=bool).requires_grad_(False)
        alpha_t_mask = torch.zeros_like(alpha_t, dtype=bool).requires_grad_(False)
        xyz_t_mask = torch.zeros_like(xyz_t, dtype=bool).requires_grad_(False)
        xyz_mask = torch.zeros_like(xyz, dtype=bool).requires_grad_(False)
        t2d[:, :,  motif_mask,  motif_mask, -1] = 1
        t1d[:, :, motif_mask, 20] = 1
        msa_mask[:, motif_mask, :] = 1
        pair_mask[:, motif_mask, motif_mask, :] = 1
        #pair_mask[:, roi_indices.reshape(-1,1), roi_indices.reshape(1,-1), :] = 1
        state_mask[:, motif_mask, :] = 1
        t1d_mask[:, :, motif_mask, :-2] = 1
        t1d_mask[:, :, motif_mask, -1] = 1
        t1d_mask[:, :, motif_mask, -2] = 0
        alpha_t_mask[:, :, motif_mask, :] = 1
        xyz_t_mask[:, :, motif_mask, :, :] = 1
        xyz_mask[:, motif_mask, :, :] = 1

        msa_recycle, pair_recycle, state_recycle = self.recycle(seq, msa_prev * msa_mask, pair_prev * pair_mask, xyz * xyz_mask, state_prev * state_mask)
            
        pair_mask = torch.zeros_like(pair, dtype=bool).requires_grad_(False)
        pair_mask[:, roi_indices.reshape(-1,1), roi_indices.reshape(1,-1), :] = 1
        t2d_mask[:, :, roi_indices.reshape(-1,1), roi_indices.reshape(1,-1), :-1] = 1
        t2d_mask[:, :, roi_indices.reshape(-1,1), roi_indices.reshape(1,-1), -1] = 0

        msa_latent[:,0] = msa_latent[:,0] + msa_recycle.reshape(B,L,-1)
        pair = pair + pair_recycle
        #pair = (pair + torch.transpose(pair, 1, 2)) / 2
        state = state + state_recycle
        msa_recycle = msa_recycle.detach()
        pair_recycle = pair_recycle.detach()
        state_recycle = state_recycle.detach()
        msa_prev = msa_prev.detach()
        pair_prev = pair_prev.detach()
        state_prev = state_prev.detach()

        # Get timestep embedding (if using)
        if hasattr(self, 'timestep_embedder'):
            assert t is not None
            time_emb = self.timestep_embedder(L,t,motif_mask)
            n_tmpl = t1d.shape[1]
            t1d = torch.cat([t1d, time_emb[None,None,...].repeat(1,n_tmpl,1,1)], dim=-1)
        '''
        pair_noise = torch.randn_like(pair).requires_grad_(False)
        pair_noise_mask = torch.zeros_like(pair, dtype=bool).requires_grad_(False)
        pair_noise_mask[:, roi_indices.reshape(-1,1), ~roi_indices.reshape(1,-1), :] = 1
        pair_noise_mask[:, ~roi_indices.reshape(-1,1), roi_indices.reshape(1,-1), :] = 1
        pair_noise[:, roi_indices.reshape(-1,1), roi_indices.reshape(1,-1), :] = 2 * torch.randn(len(roi_indices), len(roi_indices), 128).to(pair_noise.device)
        state_noise = torch.randn_like(state).requires_grad_(False)
        state_noise[:, motif_mask, :] = 10 * torch.randn(len(roi_indices), 64).to(state_noise.device)
        state_noise_mask = torch.zeros_like(state, dtype=bool).requires_grad_(False)
        state_noise_mask[:, ~roi_indices, :] = 1
        #pair = pair + pair_noise * pair_noise_mask
        #state = state + state_noise * state_noise_mask
        '''
        # add template embedding
        #if inverse_ms:
        #    pair, state = self.templ_emb(t1d, t2d, alpha_t, xyz_t, pair, state, use_checkpoint=use_checkpoint)
        #else:
        pair_, state_ = self.templ_emb(t1d * (~t1d_mask), t2d * (~t2d_mask), alpha_t * (~alpha_t_mask), xyz_t * (~xyz_t_mask), pair * (~pair_mask), state * (~state_mask), use_checkpoint=use_checkpoint)
        pair[~pair_mask] = pair_[~pair_mask]
        state[~state_mask] = state_[~state_mask]
        if not row_masking:
            pair_mask_g = torch.zeros_like(pair, dtype=bool).requires_grad_(False)
            pair_mask_g[:, motif_mask, :, :] = 1 #modify for zero/random embeddings 
            pair_mask_g[:, :, motif_mask, :] = 1 #modify for zero/random embeddings 
            pair_mask_g[:, :,  sorted(r_cols), :] = 1 # column masking
            pair_mask_g[:, sorted(r_cols),  :, :] = 1 # column masking
        elif k != 0:
            pair_mask_g = torch.zeros_like(pair, dtype=bool).requires_grad_(False)
            r_rows_pair = torch.randperm(pair.shape[-1], generator=g)[:int((1-drop_rate) * pair.shape[-1])] # row masking
            pair_mask_g[:, motif_mask, :, :] = 1 #modify for zero/random embeddings 
            pair_mask_g[:, :, motif_mask, :] = 1 #modify for zero/random embeddings 
            pair_mask_g[:, :,  (~motif_mask).nonzero(), r_rows_pair] = 1 # row masking
            pair_mask_g[:, (~motif_mask).nonzero(), :, r_rows_pair] = 1 # row masking

        if not row_masking:
            state_mask_g = torch.zeros_like(state, dtype=bool).requires_grad_(False)
            state_mask_g[:, motif_mask, :] = 1 #modify for zero/random embeddings 
            state_mask_g[:, sorted(r_cols), :] = 1 # column masking
        elif k != 0:
            state_mask_g = torch.zeros_like(state, dtype=bool).requires_grad_(False)
            r_rows_state = torch.randperm(state.shape[-1], generator=g)[:int((1-drop_rate) * state.shape[-1])] # row masking
            state_mask_g[:, motif_mask, :] = 1 #modify for zero/random embeddings 
            state_mask_g[:, (~motif_mask).nonzero(), r_rows_state] = 1 # row masking
        # Predict coordinates from given inputs
        #is_frozen_residue = motif_mask if self.freeze_track_motif else torch.zeros_like(motif_mask).bool()
        '''
        drop_rate = 0
        #k = int((1-drop_rate) * len((~motif_mask).nonzero())) # column masking
        #perm = torch.randperm(len((~motif_mask).nonzero())) # column masking
        #r_cols = torch.take((~motif_mask).nonzero().squeeze().to('cpu'), perm[:k]) # column masking
        r_rows_latent = torch.randperm(pair.shape[-1])[:int((1-drop_rate) * pair.shape[-1])] # row masking
        r_rows_full = torch.randperm(state.shape[-1])[:int((1-drop_rate) * state.shape[-1])] # row masking

        pair_mask = torch.zeros_like(pair, dtype=bool).requires_grad_(False)
        pair_mask[:, motif_mask, motif_mask, :] = 1
        #msa_latent_mask[:, :,  r_cols, :] = 1 # column masking
        pair_mask[:, :, :, r_rows_latent] = 1 # row masking
        state_mask = torch.zeros_like(state, dtype=bool).requires_grad_(False)
        state_mask[:, motif_mask, :] = 1
        #msa_full_mask[:, :, r_cols, :] = 1 # column masking
        state_mask[:, (~motif_mask).nonzero(), r_rows_full] = 1 # row masking
        #msa_latent[:, :, ~motif_mask, :] += 6 * torch.randn_like(msa_latent[:, :, ~motif_mask, :]).requires_grad_(False) 
        #msa_full[:, :, ~motif_mask, :] += 6 * torch.randn_like(msa_full[:, :, ~motif_mask, :]).requires_grad_(False) 
        '''
        if inverse_ms:
            is_frozen_residue = ~motif_mask
        else:
            is_frozen_residue = torch.zeros_like(motif_mask).bool()
        if k != 0:
            msa_, pair_, R, T, alpha_s, state_ = self.simulator(seq, msa_latent * msa_latent_mask, msa_full * msa_full_mask, pair, xyz[:,:,:3],
                                                         state * state_mask_g, idx, use_checkpoint=use_checkpoint,
                                                         motif_mask=is_frozen_residue)
        else:
            msa_, pair_, R, T, alpha_s, state_ = self.simulator(seq, msa_latent, msa_full, pair, xyz[:,:,:3],
                                                         state, idx, use_checkpoint=use_checkpoint,
                                                         motif_mask=is_frozen_residue)
        
        msa_latent = msa_latent.detach()
        msa_full = msa_full.detach()
        msa_ = msa_.detach()
        pair_ = pair_.detach()
        state_ = state_.detach()
        alpha_s = alpha_s.detach()

        if return_raw:
            # get last structure
            xyz = einsum('bnij,bnaj->bnai', R[-1], xyz[:,:,:3]-xyz[:,:,1].unsqueeze(-2)) + T[-1].unsqueeze(-2)
            return msa[:,0], pair, xyz, state, alpha_s[-1]

        # predict masked amino acids
        logits_aa = self.aa_pred(msa_)
        logits_aa = logits_aa.detach()
        # Predict LDDT
        lddt = self.lddt_pred(state_)
        lddt = lddt.detach()


        if return_infer:
            # get last structure
            xyz = einsum('bnij,bnaj->bnai', R[-1], xyz[:,:,:3]-xyz[:,:,1].unsqueeze(-2)) + T[-1].unsqueeze(-2)
            R = R.detach()
            T = T.detach()
            # get scalar plddt
            nbin = lddt.shape[1]
            bin_step = 1.0 / nbin
            lddt_bins = torch.linspace(bin_step, 1.0, nbin, dtype=lddt.dtype, device=lddt.device)
            pred_lddt = nn.Softmax(dim=1)(lddt)
            pred_lddt = torch.sum(lddt_bins[None,:,None]*pred_lddt, dim=1)

            return msa_[:,0], pair_, xyz, state_, alpha_s[-1], logits_aa.permute(0,2,1), pred_lddt

        #
        # predict distogram & orientograms
        logits = self.c6d_pred(pair)
        
        # predict experimentally resolved or not
        logits_exp = self.exp_pred(msa[:,0], state)
        
        # get all intermediate bb structures
        xyz = einsum('rbnij,bnaj->rbnai', R, xyz[:,:,:3]-xyz[:,:,1].unsqueeze(-2)) + T.unsqueeze(-2)

        return logits, logits_aa, logits_exp, xyz, alpha_s, lddt
