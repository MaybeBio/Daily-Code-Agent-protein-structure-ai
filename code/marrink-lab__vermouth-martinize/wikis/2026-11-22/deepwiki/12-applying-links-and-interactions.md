# Applying Links and Interactions

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [doc/source/_static/.empty_for_git](doc/source/_static/.empty_for_git)
- [doc/source/conf.py](doc/source/conf.py)
- [requirements-docs.txt](requirements-docs.txt)
- [vermouth/edge_tuning.py](vermouth/edge_tuning.py)
- [vermouth/geometry.py](vermouth/geometry.py)
- [vermouth/processors/add_molecule_edges.py](vermouth/processors/add_molecule_edges.py)
- [vermouth/processors/do_links.py](vermouth/processors/do_links.py)
- [vermouth/processors/tune_cystein_bridges.py](vermouth/processors/tune_cystein_bridges.py)
- [vermouth/tests/data/dna-short.pdb](vermouth/tests/data/dna-short.pdb)
- [vermouth/tests/test_add_molecule_edges.py](vermouth/tests/test_add_molecule_edges.py)
- [vermouth/tests/test_edge_tuning.py](vermouth/tests/test_edge_tuning.py)
- [vermouth/tests/test_ffinput.py](vermouth/tests/test_ffinput.py)
- [vermouth/tests/test_geometry.py](vermouth/tests/test_geometry.py)
- [vermouth/tests/test_links.py](vermouth/tests/test_links.py)
- [vermouth/tests/test_native_forcefield.py](vermouth/tests/test_native_forcefield.py)
- [vermouth/tests/test_tune_cystein_bridges.py](vermouth/tests/test_tune_cystein_bridges.py)

</details>



## Purpose and Scope

This document explains how vermouth applies links and interactions to molecules in the processing pipeline. Links are crucial mechanisms that define connections between residues, modify molecules by adding or removing atoms, and establish interactions between atoms. This page focuses on the `DoLinks` processor, which is responsible for applying links from a molecule's force field to the molecule itself.

For information about force field mapping that precedes link application, see [Force Field Mapping](#3.2). For information about structural features that may be applied after links, see [Structural Features](#3.4).

## What are Links?

Links represent ways of connecting residues in a molecule. They define modifications that should be applied when specific patterns are found in a molecule. Links can:

1. Add or remove atoms
2. Modify atom properties
3. Add or remove interactions (bonds, angles, dihedrals, etc.)
4. Define order relationships between residues

```mermaid
graph TD
    subgraph "Link Definition"
        Pattern["Atom patterns"]
        Interactions["Interactions to add"]
        RemovedInter["Interactions to remove"]
        Features["Features"]
        Meta["Metadata"]
    end

    Link --> Pattern
    Link --> Interactions
    Link --> RemovedInter
    Link --> Features
    Link --> Meta

    subgraph "Molecule"
        A1["Atom 1"]
        A2["Atom 2"]
        A3["Atom 3"]
        A1 --- A2
        A2 --- A3
    end

    Link -.applies to.-> Molecule
```

Sources: [vermouth/processors/do_links.py:290-326]()

## Link Matching Process

Before a link can be applied, the system must find where in the molecule the link matches. This matching process is at the heart of link application.

### Matching Algorithm

The matching process follows these steps:

1. Check if the molecule's metadata matches the link's metadata
2. Find subgraph isomorphisms between the link and the molecule
3. Verify non-edges (connections that should not exist)
4. Check if any pattern matches
5. Verify order relationships between matched residues

```mermaid
flowchart TD
    Start["Start matching"] --> CheckMeta["Check molecule metadata\nvs link metadata"]
    CheckMeta -- "Match" --> FindIso["Find subgraph isomorphisms"]
    CheckMeta -- "No match" --> End["No match found"]
    
    FindIso --> CheckNonEdges["Check non-edges\n(connections that shouldn't exist)"]
    CheckNonEdges -- "Valid" --> CheckPatterns["Check if patterns match"]
    CheckNonEdges -- "Invalid" --> NextMatch["Try next isomorphism"]
    
    CheckPatterns -- "Match" --> CheckOrders["Check residue orders"]
    CheckPatterns -- "No match" --> NextMatch
    
    CheckOrders -- "Valid" --> MatchFound["Match found!"]
    CheckOrders -- "Invalid" --> NextMatch
    
    NextMatch --> FindIso
    
    MatchFound --> End
```

Sources: [vermouth/processors/do_links.py:237-274]()

### Atom Matching

A critical part of the link matching process is determining whether atoms in the molecule match atoms in the link. This is handled by the `_atoms_match` function.

```mermaid
flowchart TD
    Start["Compare nodes"] --> CheckMods["Check modification matching"]
    CheckMods -- "Match" --> CheckAttrs["Check attribute matching"]
    CheckMods -- "No match" --> NoMatch["No match"]
    
    CheckAttrs -- "Match" --> Match["Match found"]
    CheckAttrs -- "No match" --> NoMatch
```

Sources: [vermouth/processors/do_links.py:27-53]()

### Order Constraints

One of the more complex aspects of link matching is handling "order" constraints. Order specifies the relationship between residues and can be:

- An integer: Defines the expected distance in residue ID
- A series of `>`: Residue must have a larger residue ID than a reference
- A series of `<`: Residue must have a smaller residue ID than a reference
- A series of `*`: Defines a different residue without specified order

```mermaid
graph TD
    Order["Order Constraints"] --> Int["Integer\n(e.g., 1, -2)"]
    Order --> Series["Series symbols"]
    
    Series --> Greater["Series of >\n(e.g., >, >>)"]
    Series --> Less["Series of <\n(e.g., <, <<<)"]
    Series --> Star["Series of *\n(e.g., *, ****)"]
    
    Int --> Example1["Example: order=1\nRequires resid difference of 1"]
    Greater --> Example2["Example: order='>'\nRequires larger resid"]
    Less --> Example3["Example: order='<<'\nRequires much smaller resid"]
    Star --> Example4["Example: order='**'\nRequires different resid"]
```

Sources: [vermouth/processors/do_links.py:126-196](), [vermouth/tests/test_links.py:26-184]()

## Applying Links

Once a match is found, the `DoLinks` processor applies the link to the molecule:

1. Replace or remove atoms as specified in the link
2. Remove interactions specified by the link
3. Add new interactions defined by the link
4. Update molecule log entries

```mermaid
flowchart TD
    Start["DoLinks.run_molecule()"] --> GetLinks["Get links from force field"]
    GetLinks --> MatchLink["Find matches for each link"]
    
    subgraph "For each match"
        ProcessNodes["Process nodes\n(replace or remove atoms)"]
        RemoveInteractions["Remove specified interactions"]
        AddInteractions["Add new interactions"]
        UpdateLog["Update log entries"]
    end
    
    MatchLink --> ProcessNodes
    ProcessNodes --> RemoveInteractions
    RemoveInteractions --> AddInteractions
    AddInteractions --> UpdateLog
    
    UpdateLog --> Return["Return modified molecule"]
```

Sources: [vermouth/processors/do_links.py:290-326]()

### Atom Modifications

Links can modify atoms in two primary ways:

1. **Replace attributes**: Update atom properties like name, type, charge, etc.
2. **Remove atoms**: Entirely remove atoms from the molecule

```mermaid
flowchart TD
    Link["Link with node attributes"] --> NodeCheck{"Node has 'replace' attribute?"}
    
    NodeCheck -- "Yes" --> RemoveCheck{"replace.atomname is None?"}
    NodeCheck -- "No" --> NoChange["No change to atom"]
    
    RemoveCheck -- "Yes" --> RemoveAtom["Remove atom from molecule"]
    RemoveCheck -- "No" --> UpdateAtom["Update atom attributes"]
```

Sources: [vermouth/processors/do_links.py:301-307]()

### Interaction Management

Links modify interactions in two ways:

1. **Remove interactions**: Using the link's `removed_interactions` attribute
2. **Add interactions**: Using the link's `interactions` attribute

Each interaction is defined by:
- Interaction type (e.g., bonds, angles, dihedrals)
- Atoms involved
- Parameters (strength, equilibrium values, etc.)

```mermaid
flowchart TD
    StartInteractions["Process interactions"] --> RemoveExisting["Remove specified interactions"]
    RemoveExisting --> AddNew["Add new interactions"]
    
    subgraph "Building an interaction"
        BuildAtoms["Map link atoms to molecule atoms"]
        EvalParams["Evaluate interaction parameters"]
        CreateInteraction["Create new interaction object"]
    end
    
    AddNew --> BuildAtoms
    BuildAtoms --> EvalParams
    EvalParams --> CreateInteraction
    CreateInteraction --> AddToMol["Add to molecule"]
```

Sources: [vermouth/processors/do_links.py:308-318](), [vermouth/processors/do_links.py:277-287]()

## Example of Link Application

Let's walk through a conceptual example of applying a link to create a peptide bond between amino acid residues.

```mermaid
graph TB
    subgraph "Before Link Application"
        subgraph "Residue 1"
            R1C["C"] --- R1O["O"]
            R1C --- R1["Other atoms"]
        end
        
        subgraph "Residue 2"
            R2N["N"] --- R2H["H"]
            R2N --- R2["Other atoms"]
        end
    end
    
    subgraph "Peptide Bond Link"
        LC["C{'resid': 0}"]
        LN["N{'resid': 1}"]
        LC --- LN
        LCOH["Remove O-H\nAdd C-N bond"]
    end
    
    subgraph "After Link Application"
        subgraph "Connected Residues"
            AR1C["C"] --- AR2N["N"]
            AR1C --- AR1["Other atoms"]
            AR2N --- AR2["Other atoms"]
        end
    end
    
    "Before Link Application" --> "Peptide Bond Link"
    "Peptide Bond Link" --> "After Link Application"
```

Sources: [vermouth/processors/do_links.py:290-326]()

## Working with Orders in Links

The order system in links is particularly powerful for defining relationships between residues. This section explores how orders work in practice.

### Order Interpretation

The `_interpret_order` function converts an order specification into a type and value:

```mermaid
flowchart TD
    Start["_interpret_order(order)"] --> OrderType{"What type is order?"}
    
    OrderType -- "Number" --> CheckInt{"Is it an integer?"}
    OrderType -- "String/Sequence" --> CheckChar{"First character?"}
    OrderType -- "Other" --> Error["Raise ValueError"]
    
    CheckInt -- "Yes" --> ReturnNum["Return ('number', order)"]
    CheckInt -- "No" --> Error
    
    CheckChar -- "> or <" --> ReturnSign["Return ('><', sign * length)"]
    CheckChar -- "*" --> ReturnStar["Return ('*', length)"]
    CheckChar -- "Other" --> Error
```

Sources: [vermouth/processors/do_links.py:88-123](), [vermouth/tests/test_links.py:189-206]()

### Order Matching

The `match_order` function is responsible for determining if two residues satisfy their order constraints:

```mermaid
flowchart TD
    Start["match_order(order1, resid1, order2, resid2)"] --> GetOrders["Get order types and values"]
    
    GetOrders --> Case{"Case analysis"}
    
    Case -- "order1 is number" --> NumCase["Check number cases"]
    Case -- "order1 is >< (< or >)" --> DirCase["Check direction cases"]
    Case -- "order1 is *" --> StarCase["Check star cases"]
    
    NumCase --> CheckMatch{"Do constraints match?"}
    DirCase --> CheckMatch
    StarCase --> CheckMatch
    
    CheckMatch -- "Yes" --> ReturnTrue["Return True"]
    CheckMatch -- "No" --> ReturnFalse["Return False"]
```

Sources: [vermouth/processors/do_links.py:126-234](), [vermouth/tests/test_links.py:26-184]()

## DoLinks Processor Implementation

The `DoLinks` processor is a key component in the vermouth processing pipeline. It is responsible for applying links from a molecule's force field to the molecule.

```mermaid
classDiagram
    class Processor {
        +run_system(system)
        +run_molecule(molecule)
    }
    
    class DoLinks {
        +run_molecule(molecule)
    }
    
    Processor <|-- DoLinks
    
    class Link {
        +nodes
        +edges
        +removed_interactions
        +interactions
        +patterns
        +features
        +molecule_meta
        +log_entries
    }
    
    DoLinks ..> Link : "applies"
```

Sources: [vermouth/processors/do_links.py:290-326]()

## Real-World Applications

Links are used extensively in Vermouth for various purposes:

1. **Peptide bonds**: Connecting amino acid residues in proteins
2. **Nucleic acid connections**: Creating bonds in DNA/RNA structures
3. **Post-translational modifications**: Adding chemical groups to proteins
4. **Cystein bridges**: Creating disulfide bonds between cystein residues
5. **Terminal capping**: Modifying termini of protein chains

```mermaid
graph LR
    subgraph "Common Link Applications"
        PeptideBond["Peptide Bonds"]
        NucleicBond["Nucleic Acid Connections"]
        PostTrans["Post-translational Modifications"]
        CysBridge["Cystein Bridges"]
        TermCap["Terminal Capping"]
    end
    
    Link["Link Mechanism"] --> PeptideBond
    Link --> NucleicBond
    Link --> PostTrans
    Link --> CysBridge
    Link --> TermCap
```

Sources: [vermouth/processors/do_links.py:290-326](), [vermouth/processors/tune_cystein_bridges.py:1-115]()

## Conclusions

Links are a powerful mechanism in Vermouth for modifying molecular structures. They provide a flexible way to define how residues should be connected and what interactions should be present. The `DoLinks` processor applies these links to molecules, enabling complex transformations to be performed automatically.

Key points to remember:
- Links define patterns, atoms, and interactions
- Matching is a multi-step process considering topology and attributes
- Order constraints provide flexible ways to express residue relationships
- Links can add, remove, or modify atoms and interactions

Understanding links is essential for working with the Vermouth system, especially when creating custom force fields or handling complex molecular structures.

---