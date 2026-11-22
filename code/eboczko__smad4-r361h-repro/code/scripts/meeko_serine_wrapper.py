#!/home/rad/miniforge3/envs/vina/bin/python
import runpy
import sys
import meeko.polymer as polymer

original = polymer.ResidueTemplate.match
corrected = set()

def match(self, molecule):
    result, mapping = original(self, molecule)

    # This workflow deliberately supplies heavy atoms only.
    if any(a.GetAtomicNum() == 1 for a in molecule.GetAtoms()):
        return result, mapping

    raw = {}
    for atom in molecule.GetAtoms():
        info = atom.GetPDBResidueInfo()
        if info is None or info.GetResidueName().strip() != "SER":
            return result, mapping
        name = info.GetName().strip()
        if name in raw:
            return result, mapping
        raw[name] = atom.GetIdx()

    template = {
        self.atom_names[a.GetIdx()]: a.GetIdx()
        for a in self.mol.GetAtoms() if a.GetAtomicNum() != 1
    }
    if set(template) != set(raw):
        return result, mapping
    if result["heavy"]["missing"] or result["heavy"]["excess"]:
        return result, mapping

    named = {index: raw[name] for name, index in template.items()}
    for ti, ri in named.items():
        if self.mol.GetAtomWithIdx(ti).GetAtomicNum() != molecule.GetAtomWithIdx(ri).GetAtomicNum():
            return result, mapping

    # Validate every heavy-atom edge and non-edge.
    # Bond order is assigned by Meeko's chemical template.
    indices = list(named)
    for position, a in enumerate(indices):
        for b in indices[position+1:]:
            template_bond = self.mol.GetBondBetweenAtoms(a, b) is not None
            input_bond = molecule.GetBondBetweenAtoms(named[a], named[b]) is not None
            if template_bond != input_bond:
                return result, mapping

    if named != mapping:
        info = molecule.GetAtomWithIdx(0).GetPDBResidueInfo()
        key = (info.GetChainId(), info.GetResidueNumber())
        if key not in corrected:
            print(f"Validated SER mapping correction: {key}", flush=True)
            corrected.add(key)

    return result, named

polymer.ResidueTemplate.match = match
cli = "/home/rad/miniforge3/envs/vina/bin/mk_prepare_receptor.py"
sys.argv[0] = cli
runpy.run_path(cli, run_name="__main__")
