"""PCFF atom typing from EMC's pcff_templates.dat.

The goal is to assign the same types as EMC v9.4.4.
The behaviour below was established from EMC's field_debug output and from EMC-typed reference molecules.

Template language (one 'type:' block may hold several templates; each atom_test block applies to the template above it):
- '(>C(-H)(-*))' : the atom after '>' is the atom being typed; each nested group is a bonded neighbour.
  '[' ... ']' groups are treated exactly like '(' ... ')' (EMC compiles both to the same rule).
- Bonds: '-' single, '=' double, '#' triple, ':' aromatic, '~' any.
- Elements: a symbol, or '*' for any element. 'SI' in the file is read as Si.
- Atoms are numbered 1, 2, ... in order of appearance; atom_test:N applies to atom N.
  allowed_elements / disallowed_elements: restrict the element.
  aromaticity: AROMATIC / NON_AROMATIC.
  ring: PLANAR(n) or NON_PLANAR(n): the atom is in a ring of size n (planarity is not tested, as in EMC).
  formal_charge: n.
  mass_number: n (isotope).
  hybridization: SP / SP2 / SP3; not applied during typing, because EMC does not apply it (e.g. EMC types the central carbon of allene and the carbon of CO2 with the sp3 type 'c').
  hybridization_mismatches lists the atoms whose type matches only because this test is skipped, using RDKit's hybridization.

Matching:
- The typed atom must have exactly as many neighbours as its template lists (if the template lists any).
- Nested atoms need at least the listed neighbours, not counting the atom they were reached from.
- Neighbours are matched one-to-one with backtracking.
  EMC matches greedily without backtracking; the two agree whenever a match does not depend on the neighbour order.

Precedence (the 'precedence:' tree at the end of the file):
- Starting below the root '?', the first child (in file order) whose templates match is selected, and the search continues among its children.
- The type is the last selected node.
  Consequence (EMC behaviour): only the first top-level occurrence of a type is ever reached, e.g. '(c(c1(...)))' comes before '(c(c2 ...))' and '(c(c3)...)',
  so EMC never assigns c2 or c3, and alkane carbons are typed 'c'.

Molecules are RDKit molecules with explicit hydrogens; aromaticity is RDKit's default model.
"""

import re
from pathlib import Path

from rdkit import Chem


BOND_SYMBOLS = {
    "-": Chem.BondType.SINGLE,
    "=": Chem.BondType.DOUBLE,
    "#": Chem.BondType.TRIPLE,
    ":": Chem.BondType.AROMATIC,
    "~": None,
}

TEMPLATE_TOKEN = re.compile(r"\s*([\(\)\[\]>]|[-=#:~]|\*|[A-Z][A-Za-z]?)")


def normalize_element(symbol: str) -> str:
    # 'SI' appears once in pcff_templates.dat and is read as Si by EMC.
    if symbol == "*":
        return symbol
    return symbol[0].upper() + symbol[1:].lower()


def parse_template(template_text: str) -> list[dict]:
    """
    Parse one template into a list of template atoms in order of appearance (atom 1 first).
    Each atom is a dict: element ('*' for any), bond (to its parent; None for atom 1), children (indices), tests (dict).
    """
    tokens = TEMPLATE_TOKEN.findall(template_text)

    if "".join(tokens) != re.sub(r"\s", "", template_text):
        raise ValueError(f"Cannot parse template '{template_text}'.")

    atoms = []
    stack = []
    position = 0

    while position < len(tokens):
        token = tokens[position]

        if token in "([":
            position += 1
            bond = None

            if tokens[position] == ">":
                if atoms:
                    raise ValueError(f"Template '{template_text}': '>' must mark the first atom.")
                position += 1
            elif tokens[position] in BOND_SYMBOLS:
                bond = tokens[position]
                position += 1
            else:
                raise ValueError(f"Template '{template_text}': neighbour without a bond symbol.")

            atom = {
                "element": normalize_element(tokens[position]),
                "bond": bond,
                "children": [],
                "tests": {},
            }
            position += 1

            if stack:
                atoms[stack[-1]]["children"].append(len(atoms))
            elif atoms:
                raise ValueError(f"Template '{template_text}': more than one top-level atom.")

            stack.append(len(atoms))
            atoms.append(atom)

        elif token in ")]":
            stack.pop()
            position += 1

        else:
            raise ValueError(f"Template '{template_text}': unexpected token '{token}'.")

    if stack or not atoms:
        raise ValueError(f"Template '{template_text}': unbalanced brackets.")

    return atoms


def parse_atom_test(template_atom: dict, keyword: str, value: str) -> None:
    keyword = keyword.lower()
    value = value.split("!")[0].strip()

    if keyword == "allowed_elements":
        template_atom["tests"]["allowed_elements"] = {normalize_element(element.strip()) for element in value.split(",")}
    elif keyword == "disallowed_elements":
        template_atom["tests"]["disallowed_elements"] = {normalize_element(element.strip()) for element in value.split(",")}
    elif keyword == "aromaticity":
        if value.upper() not in ("AROMATIC", "NON_AROMATIC"):
            raise ValueError(f"Unknown aromaticity test '{value}'.")
        template_atom["tests"]["aromatic"] = value.upper() == "AROMATIC"
    elif keyword == "ring":
        match = re.fullmatch(r"(NON_)?PLANAR\((\d+)\)", value.upper())
        if match is None:
            raise ValueError(f"Unknown ring test '{value}'.")
        template_atom["tests"]["ring_size"] = int(match.group(2))
    elif keyword == "formal_charge":
        template_atom["tests"]["formal_charge"] = int(value)
    elif keyword == "mass_number":
        template_atom["tests"]["mass_number"] = int(value)
    elif keyword == "hybridization":
        # Stored for hybridization_mismatches only; typing does not apply it (EMC behaviour, see the module docstring).
        if value.upper() not in ("SP", "SP2", "SP3"):
            raise ValueError(f"Unknown hybridization test '{value}'.")
        template_atom["tests"]["hybridization"] = value.upper()
    else:
        raise ValueError(f"Unknown atom test '{keyword}'.")


def read_templates(templates_path: Path) -> dict:
    """
    Read pcff_templates.dat.

    Returns {"templates": {type: [template atoms list, ...]}, "precedence": tree},
    where the tree is a nested (type, [children]) structure with root '?'.
    """
    lines = templates_path.read_text().splitlines()

    templates = {}
    current_type = None
    current_template = None
    current_test_atom = None
    precedence_lines = []
    in_precedence = False

    for line in lines:
        stripped = line.strip()

        if in_precedence:
            if stripped.startswith("end_precedence"):
                in_precedence = False
            elif not stripped.startswith("!"):
                precedence_lines.append(stripped.split("!")[0])
            continue

        if not stripped or stripped.startswith("!"):
            continue

        # 'template (...)' without a colon also occurs and is accepted by EMC; templates may contain ':' (aromatic bonds).
        # 'type oh' without a colon occurs once as well.
        if stripped.startswith("template"):
            keyword, separator, value = "template", ":", stripped[len("template") :].strip().removeprefix(":")
        elif re.fullmatch(r"type\s+\S+", stripped):
            keyword, separator, value = "type", ":", stripped.split()[1]
        else:
            keyword, separator, value = stripped.partition(":")
            keyword = keyword.strip()

        if keyword == "precedence":
            in_precedence = True
        elif keyword == "type":
            current_type = value.strip()
            templates.setdefault(current_type, [])
        elif keyword == "template":
            current_template = parse_template(value.strip())
            templates[current_type].append(current_template)
        elif keyword == "atom_test":
            current_test_atom = current_template[int(value) - 1]
        elif keyword in ("end_test", "end_type"):
            current_test_atom = None
        elif current_test_atom is not None and separator:
            parse_atom_test(current_test_atom, keyword, value)
        else:
            raise ValueError(f"{templates_path}: cannot interpret line '{stripped}'.")

    precedence = parse_precedence(" ".join(precedence_lines))

    return {"templates": templates, "precedence": precedence}


def parse_precedence(text: str) -> tuple:
    """Parse '(? (h(hsi)(hc)) (cp ...) ...)' into (type, [children])."""
    tokens = re.findall(r"\(|\)|[^\s()]+", text)
    position = 0

    def parse_node():
        nonlocal position

        if tokens[position] != "(":
            raise ValueError("Precedence: expected '('.")
        position += 1

        node_type = tokens[position]
        position += 1
        children = []

        while tokens[position] != ")":
            children.append(parse_node())

        position += 1
        return (node_type, children)

    root = parse_node()

    if position != len(tokens) or root[0] != "?":
        raise ValueError("Precedence: expected a single tree with root '?'.")

    return root


# --- Matching -------------------------------------------------------------------------------------------------


def atom_passes_tests(template_atom: dict, atom: Chem.Atom, apply_hybridization: bool) -> bool:
    element = atom.GetSymbol()

    if template_atom["element"] != "*" and template_atom["element"] != element:
        return False

    tests = template_atom["tests"]

    if "allowed_elements" in tests and element not in tests["allowed_elements"]:
        return False
    if "disallowed_elements" in tests and element in tests["disallowed_elements"]:
        return False
    if "aromatic" in tests and atom.GetIsAromatic() != tests["aromatic"]:
        return False
    if "ring_size" in tests and not atom.IsInRingSize(tests["ring_size"]):
        return False
    if "formal_charge" in tests and atom.GetFormalCharge() != tests["formal_charge"]:
        return False
    if "mass_number" in tests and atom.GetIsotope() != tests["mass_number"]:
        return False
    # str(Chem.HybridizationType.SP3) is 'SP3'.
    if apply_hybridization and "hybridization" in tests and str(atom.GetHybridization()) != tests["hybridization"]:
        return False

    return True


def bond_matches(bond_symbol: str, bond: Chem.Bond) -> bool:
    required_type = BOND_SYMBOLS[bond_symbol]
    return required_type is None or bond.GetBondType() == required_type


def match_children(
    template: list[dict],
    child_indices: list[int],
    molecule: Chem.Mol,
    atom: Chem.Atom,
    neighbour_indices: list[int],
    apply_hybridization: bool,
) -> bool:
    """Assign template children to distinct neighbours (backtracking); each child must match its neighbour recursively."""
    if not child_indices:
        return True

    child = template[child_indices[0]]

    for position, neighbour_index in enumerate(neighbour_indices):
        bond = molecule.GetBondBetweenAtoms(atom.GetIdx(), neighbour_index)

        if not bond_matches(child["bond"], bond):
            continue

        neighbour = molecule.GetAtomWithIdx(neighbour_index)

        if not match_atom(template, child_indices[0], molecule, neighbour, parent_index=atom.GetIdx(), apply_hybridization=apply_hybridization):
            continue

        remaining = neighbour_indices[:position] + neighbour_indices[position + 1 :]

        if match_children(template, child_indices[1:], molecule, atom, remaining, apply_hybridization):
            return True

    return False


def match_atom(
    template: list[dict],
    template_index: int,
    molecule: Chem.Mol,
    atom: Chem.Atom,
    parent_index: int | None,
    apply_hybridization: bool,
) -> bool:
    template_atom = template[template_index]

    if not atom_passes_tests(template_atom, atom, apply_hybridization):
        return False

    neighbour_indices = [neighbour.GetIdx() for neighbour in atom.GetNeighbors() if neighbour.GetIdx() != parent_index]
    child_indices = template_atom["children"]

    # The typed atom must have exactly the listed neighbours; nested atoms need at least the listed ones.
    if parent_index is None and child_indices and len(child_indices) != len(neighbour_indices):
        return False

    if len(child_indices) > len(neighbour_indices):
        return False

    return match_children(template, child_indices, molecule, atom, neighbour_indices, apply_hybridization)


def type_matches(templates: dict, type_name: str, molecule: Chem.Mol, atom: Chem.Atom, apply_hybridization: bool) -> bool:
    return any(
        match_atom(template, 0, molecule, atom, parent_index=None, apply_hybridization=apply_hybridization)
        for template in templates.get(type_name, [])
    )


def assign_atom_types(molecule: Chem.Mol, typing_rules: dict) -> list[str]:
    """
    Return the PCFF type of every atom of an RDKit molecule with explicit hydrogens.
    Raises ValueError for atoms that no type matches.
    """
    if any(atom.GetTotalNumHs() != 0 for atom in molecule.GetAtoms()):
        raise ValueError("The molecule must have explicit hydrogen atoms (Chem.AddHs).")

    templates = typing_rules["templates"]
    atom_types = []
    untyped_atoms = []

    for atom in molecule.GetAtoms():
        node_type, children = typing_rules["precedence"]

        # Descend the precedence tree: at each level the first matching child is selected.
        while True:
            selected = None

            for child in children:
                if type_matches(templates, child[0], molecule, atom, apply_hybridization=False):
                    selected = child
                    break

            if selected is None:
                break

            node_type, children = selected

        if node_type == "?":
            untyped_atoms.append(f"{atom.GetSymbol()}{atom.GetIdx()}")

        atom_types.append(node_type)

    if untyped_atoms:
        raise ValueError(f"No PCFF type matches atoms {', '.join(untyped_atoms)}.")

    return atom_types


def hybridization_mismatches(molecule: Chem.Mol, typing_rules: dict) -> list[tuple[int, str, str]]:
    """
    Return (atom index, PCFF type, RDKit hybridization) for every atom whose type matches only because hybridization tests are skipped.

    The typing follows EMC and does not apply the templates' hybridization tests (module docstring).
    An atom is listed when no template of its assigned type matches once those tests are applied with RDKit's hybridization,
    e.g. the central carbon of allene (RDKit SP), typed with the generic sp3 carbon 'c'.
    RDKit's hybridization (from connectivity, lone pairs, and conjugation) need not be the one the template author intended, so a listed atom calls for inspection, not necessarily a fix.
    """
    atom_types = assign_atom_types(molecule, typing_rules)
    mismatches = []

    for atom, atom_type in zip(molecule.GetAtoms(), atom_types):
        if not type_matches(typing_rules["templates"], atom_type, molecule, atom, apply_hybridization=True):
            mismatches.append((atom.GetIdx(), atom_type, str(atom.GetHybridization())))

    return mismatches


# --- Systems of many molecules ----------------------------------------------------------------------------------


def element_from_mass(mass_amu: float) -> str:
    """Return the element whose standard atomic mass is within 0.1 amu of mass_amu."""
    periodic_table = Chem.GetPeriodicTable()
    candidates = [
        periodic_table.GetElementSymbol(atomic_number)
        for atomic_number in range(1, 87)
        if abs(periodic_table.GetAtomicWeight(atomic_number) - mass_amu) < 0.1
    ]

    if len(candidates) != 1:
        raise ValueError(f"Cannot identify the element of mass {mass_amu} amu (candidates {candidates}).")

    return candidates[0]


def connected_components(n_atoms: int, bonds: list[tuple[int, int]]) -> list[list[int]]:
    """Return the molecules as sorted lists of atom indices, ordered by their first atom."""
    neighbours = [[] for atom in range(n_atoms)]

    for atom_i, atom_j in bonds:
        neighbours[atom_i].append(atom_j)
        neighbours[atom_j].append(atom_i)

    component_of = [None] * n_atoms
    components = []

    for start in range(n_atoms):
        if component_of[start] is not None:
            continue

        component = [start]
        component_of[start] = len(components)
        frontier = [start]

        while frontier:
            atom = frontier.pop()

            for neighbour in neighbours[atom]:
                if component_of[neighbour] is None:
                    component_of[neighbour] = len(components)
                    component.append(neighbour)
                    frontier.append(neighbour)

        components.append(sorted(component))

    return components


def match_component_to_molecule(elements: list[str], bonds: list[tuple[int, int]], component: list[int], molecule: Chem.Mol) -> list[int] | None:
    """
    Map the atoms of one connected component (elements + bonds, no bond orders) onto an RDKit molecule with explicit hydrogens.
    Returns, for every component atom in order, the index of the corresponding molecule atom, or None if they are not the same graph.
    """
    if len(component) != molecule.GetNumAtoms():
        return None

    local_index = {atom: position for position, atom in enumerate(component)}
    component_graph = Chem.RWMol()

    for atom in component:
        component_graph.AddAtom(Chem.Atom(elements[atom]))

    n_component_bonds = 0
    for atom_i, atom_j in bonds:
        if atom_i in local_index:
            component_graph.AddBond(local_index[atom_i], local_index[atom_j], Chem.BondType.SINGLE)
            n_component_bonds += 1

    if n_component_bonds != molecule.GetNumBonds():
        return None

    component_graph.UpdatePropertyCache(strict=False)
    Chem.FastFindRings(component_graph)

    # Compare only elements and connectivity: bond orders are unknown in the component graph.
    query_parameters = Chem.AdjustQueryParameters.NoAdjustments()
    query_parameters.makeBondsGeneric = True
    query = Chem.AdjustQueryProperties(molecule, query_parameters)

    match = component_graph.GetSubstructMatch(query)

    if not match:
        return None

    # match[molecule atom] = component atom; invert it.
    molecule_index_of_component_atom = [None] * len(component)
    for molecule_atom, component_atom in enumerate(match):
        molecule_index_of_component_atom[component_atom] = molecule_atom

    return molecule_index_of_component_atom


def assign_system_atom_types(elements: list[str], bonds: list[tuple[int, int]], molecules: list[Chem.Mol], typing_rules: dict) -> list[str]:
    """
    Type every atom of a system given as elements and bonds (0-based), such as a structure built by a packing tool.

    Every connected component must be the same graph as one of the RDKit molecules (explicit hydrogens),
    which supply the bond orders, aromaticity, and formal charges that the typing needs.
    """
    molecule_types = [assign_atom_types(molecule, typing_rules) for molecule in molecules]

    atom_types = [None] * len(elements)

    for component in connected_components(len(elements), bonds):
        for molecule, types in zip(molecules, molecule_types):
            mapping = match_component_to_molecule(elements, bonds, component, molecule)

            if mapping is not None:
                for component_atom, molecule_atom in zip(component, mapping):
                    atom_types[component_atom] = types[molecule_atom]
                break
        else:
            raise ValueError(f"Molecule starting at atom {component[0]} matches none of the given molecules.")

    return atom_types
