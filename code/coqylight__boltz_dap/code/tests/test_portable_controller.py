import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

import torch


specification = importlib.util.spec_from_file_location('portable_full60',
    Path(__file__).resolve().parents[1] / 'repro/full60_bf16.py')
control = importlib.util.module_from_spec(specification)
specification.loader.exec_module(control)


class PortableControllerTests(unittest.TestCase):
    def test_execution_adapters_track_and_restore_native_calls(self):
        class Pairformer(torch.nn.Module):
            def forward(self, value):
                return value

        trunk = ModuleType('dap_trunk')
        attention = ModuleType('dap_tri_att')
        cache = ModuleType('dap_cached_token_attention')
        pairformer = ModuleType('dap_pairformer')
        pairformer.DAPPairformerLayer = Pairformer
        layer = Pairformer()
        value = torch.zeros(1)

        def confidence():
            for index in range(8):
                layer(value)

        def cached(structure):
            structure._dap_cache_receipt = dict(closed=True, projection_precision='bf16-mixed')

        def sample(**keywords):
            step_idx = 0
            return torch.multinomial(torch.ones(1), 1)

        trunk.inject_dap_into_model = lambda model: model
        trunk.run_confidence_dap = confidence
        attention._mha_q_chunked_fused = lambda: value
        cache.run_cached_diffusion_sampling = cached
        original = trunk.inject_dap_into_model
        structure = SimpleNamespace(sample=sample, step_scale=1.5)
        model = SimpleNamespace(structure_module=structure)
        record = dict(trunk_layers=0, confidence_layers=0, confidence_calls=0,
            sampling_calls=0, resampling_events=0, fused_attention_calls=0,
            cache_receipts=[], peak_allocated_bytes=0, peak_reserved_bytes=0)
        modules = dict(dap_trunk=trunk, dap_tri_att=attention,
            dap_cached_token_attention=cache, dap_pairformer=pairformer)
        with patch.dict(sys.modules, modules), \
                patch.object(torch.backends.cuda, 'matmul', SimpleNamespace(allow_tf32=False)), \
                patch.object(torch.backends, 'cudnn', SimpleNamespace(allow_tf32=False)):
            with control.execution_checks(dict(dimensions=dict(tokens=240)), record):
                trunk.inject_dap_into_model(model)
                for index in range(256):
                    layer(value)
                for index in range(512):
                    attention._mha_q_chunked_fused()
                structure.sample(steering_args=control.STEERING, num_sampling_steps=200,
                    multiplicity=1, feats=dict(token_pad_mask=torch.ones(1, 240),
                        template_force=torch.zeros(1, dtype=torch.bool)))
                cache.run_cached_diffusion_sampling(structure)
                trunk.run_confidence_dap()
            control.validate_execution(record)
            self.assertIs(trunk.inject_dap_into_model, original)
            self.assertIs(trunk.run_confidence_dap, confidence)
            self.assertEqual(record['resampling_events'], 1)

    def test_node_gate_requires_all_current_job_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / 'admission').mkdir()
            args = SimpleNamespace(run=run, expected_sha='binding')
            for node in range(4):
                control.write_json(run / 'admission' / f'node_{node}.json',
                    dict(host=f'node{node}', node=node, binding_sha256='binding', job_id='current'))
            with patch.object(control, 'verify_run', return_value={}), \
                    patch.dict(os.environ, {'SLURM_JOB_ID': 'current'}):
                control.gate(args)
                self.assertTrue(json.loads((run / 'admission/node_gate.json').read_text())['passed'])
                changed = run / 'admission/node_2.json'
                record = json.loads(changed.read_text())
                changed.write_text(json.dumps(dict(record, job_id='stale')))
                with self.assertRaises(ValueError):
                    control.gate(args)


if __name__ == '__main__':
    unittest.main()