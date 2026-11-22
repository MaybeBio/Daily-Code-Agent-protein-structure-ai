# Output File Formats

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [app/packmol.f90](app/packmol.f90)
- [src/checkpoint.f90](src/checkpoint.f90)
- [src/getinp.f90](src/getinp.f90)
- [src/input.f90](src/input.f90)
- [src/output.f90](src/output.f90)

</details>



This page documents the output file formats supported by Packmol and the options available for customizing the generated structure files. For information about input file syntax, see [Input File Format](#3.1). For command-line usage, see [Command-Line Interface](#3.5).

## Purpose and Scope

Packmol generates molecular structure files in multiple formats suitable for molecular dynamics simulation packages. The output generation process is implemented in [src/output.f90]() and controlled by keywords in the input file. This page covers:

- Supported output file formats (PDB, Tinker XYZ, standard XYZ, CHARMM CRD)
- Format-specific options and customization
- Residue numbering schemes
- Connectivity information handling
- Restart file generation

## Supported Output Formats

Packmol supports four primary output formats, controlled by the `filetype` keyword in the input file:

| Format | Keyword | File Extension | Primary Use Case |
|--------|---------|----------------|------------------|
| PDB | `filetype pdb` | `.pdb` | Protein Data Bank format, widely used for biomolecular simulations |
| Tinker XYZ | `filetype tinker` | `.xyz` | Tinker molecular modeling package format with connectivity |
| Standard XYZ | `filetype xyz` | `.xyz` | Simple Cartesian coordinate format |
| CHARMM CRD | `writecrd <file>` | `.crd` | CHARMM coordinate format (supplemental to PDB) |

**Sources:** [src/output.f90:1-599](), [src/getinp.f90:146-149]()

### Format Selection Logic

```mermaid
graph TD
    START["Input File Processing<br/>getinp.f90"] --> CHECK_FILETYPE["Check 'filetype' keyword<br/>getinp.f90:setsizes"]
    CHECK_FILETYPE --> PDB_CHECK{"filetype == 'pdb'?"}
    CHECK_FILETYPE --> TINKER_CHECK{"filetype == 'tinker'?"}
    CHECK_FILETYPE --> XYZ_CHECK{"filetype == 'xyz'?"}
    
    PDB_CHECK -->|Yes| SET_PDB["pdb = .true.<br/>input.f90"]
    TINKER_CHECK -->|Yes| SET_TINKER["tinker = .true.<br/>input.f90"]
    XYZ_CHECK -->|Yes| SET_XYZ["xyz = .true.<br/>input.f90"]
    
    SET_PDB --> CHECK_CRD{"writecrd keyword?"}
    CHECK_CRD -->|Yes| SET_CRD["crd = .true.<br/>getinp.f90:146-149"]
    CHECK_CRD -->|No| OUTPUT_CALL
    SET_CRD --> OUTPUT_CALL
    SET_TINKER --> OUTPUT_CALL
    SET_XYZ --> OUTPUT_CALL
    
    OUTPUT_CALL["output subroutine<br/>output.f90:9"] --> WRITE_RESTART["Write restart files<br/>output.f90:46-89"]
    WRITE_RESTART --> FORMAT_BRANCH{"Which format?"}
    
    FORMAT_BRANCH -->|xyz| WRITE_XYZ["Write XYZ output<br/>output.f90:93-131"]
    FORMAT_BRANCH -->|pdb| WRITE_PDB["Write PDB output<br/>output.f90:134-469"]
    FORMAT_BRANCH -->|tinker| WRITE_TINKER["Write Tinker output<br/>output.f90:473-536"]
    
    WRITE_PDB --> CHECK_CRD_OUT{"crd == .true.?"}
    CHECK_CRD_OUT -->|Yes| WRITE_CRD_FILE["Write CRD file<br/>output.f90:302-312"]
    CHECK_CRD_OUT -->|No| DONE
    WRITE_CRD_FILE --> DONE["Output files written"]
    WRITE_XYZ --> DONE
    WRITE_TINKER --> DONE
```

**Sources:** [src/getinp.f90:146-272](), [src/output.f90:9-539](), [src/input.f90:47-50]()

## PDB Format Output

The PDB (Protein Data Bank) format is the most feature-rich output option, supporting multiple customization options.

### PDB File Structure

```mermaid
graph LR
    subgraph "PDB Output Structure"
        HEADER["HEADER line<br/>output.f90:151-157"]
        REMARK["REMARK lines<br/>output.f90:151-162"]
        CRYST1["CRYST1 (if PBC)<br/>output.f90:164-171"]
        ATOMS["ATOM/HETATM records<br/>output.f90:218-320"]
        TER["TER records (optional)<br/>output.f90:319,425"]
        CONECT["CONECT records<br/>output.f90:429-465"]
        END_REC["END record<br/>output.f90:466"]
    end
    
    HEADER --> REMARK
    REMARK --> CRYST1
    CRYST1 --> ATOMS
    ATOMS --> TER
    TER --> CONECT
    CONECT --> END_REC
```

**Sources:** [src/output.f90:134-469]()

### PDB Output Options

The following table summarizes PDB-specific options that can be set in the input file:

| Keyword | Effect | Default | Code Reference |
|---------|--------|---------|----------------|
| `add_amber_ter` | Add TER records between molecules | `false` | [src/getinp.f90:126-128]() |
| `amber_ter_preserve` | Preserve TER records from input files | `false` | [src/getinp.f90:129-131]() |
| `add_box_sides [value]` | Add CRYST1 record with box dimensions | `false` | [src/getinp.f90:150-158]() |
| `hexadecimal_indices` | Use hexadecimal for atom/residue indices >9999/99999 | `false` | [src/getinp.f90:98-99]() |
| `resnumbers <0\|1\|2\|3>` | Residue numbering scheme (per structure) | Auto-detect | [src/getinp.f90:825-827]() |
| `changechains` | Alternate chain IDs for molecules (per structure) | `false` | [src/getinp.f90:822-824]() |
| `chain <char>` | Force specific chain identifier (per structure) | Auto | [src/getinp.f90:833-835]() |
| `connect <yes\|no>` | Include connectivity (CONECT records) | `yes` | [src/getinp.f90:828-832]() |
| `segid <identifier>` | Set segment identifier for CRD format | Empty | [src/getinp.f90:836-838]() |

**Sources:** [src/getinp.f90:126-158](), [src/getinp.f90:812-868]()

### Residue Numbering Schemes

Packmol supports four residue numbering schemes controlled by the `resnumbers` keyword within each `structure...end structure` block:

```mermaid
graph TD
    START["Residue Numbering<br/>output.f90:270-284"] --> SCHEME{"resnumbers value"}
    
    SCHEME -->|0| MODE0["Mode 0: By Molecule<br/>iires = mod(imol, 9999)<br/>output.f90:271-272"]
    SCHEME -->|1| MODE1["Mode 1: From Input<br/>iires = imark (from PDB)<br/>output.f90:274-275"]
    SCHEME -->|2| MODE2["Mode 2: Sequential<br/>iires = mod(imark-ifres+irescount, 9999)<br/>output.f90:277-278"]
    SCHEME -->|3| MODE3["Mode 3: Absolute Molecule<br/>iires = mod(iimol, 9999)<br/>output.f90:280-281"]
    
    MODE0 --> HANDLE_ZERO["If iires == 0:<br/>iires = 9999<br/>output.f90:283"]
    MODE1 --> HANDLE_ZERO
    MODE2 --> HANDLE_ZERO
    MODE3 --> HANDLE_ZERO
    
    HANDLE_ZERO --> WRITE_ATOM["Write ATOM/HETATM line<br/>output.f90:287-300"]
```

**Sources:** [src/output.f90:270-284](), [src/getinp.f90:849-857]()

### Atom Index Formatting

When atom or residue indices exceed PDB format limits, Packmol can automatically switch to hexadecimal representation:

```mermaid
graph LR
    subgraph "Index Formatting Functions"
        I5HEX["i5hex function<br/>output.f90:541-551"]
        I4HEX["i4hex function<br/>output.f90:553-563"]
    end
    
    subgraph "Logic"
        CHECK5["i > 99999 or<br/>hexadecimal_indices?"]
        CHECK4["i > 9999 or<br/>hexadecimal_indices?"]
    end
    
    I5HEX --> CHECK5
    CHECK5 -->|Yes| HEX5["write(i5hex,'(z5)')"]
    CHECK5 -->|No| DEC5["write(i5hex,'(i5)')"]
    
    I4HEX --> CHECK4
    CHECK4 -->|Yes| HEX4["write(i4hex,'(z4)')"]
    CHECK4 -->|No| DEC4["write(i4hex,'(i4)')"]
```

**Sources:** [src/output.f90:541-563](), [src/getinp.f90:98-99]()

### PDB Atom Line Format

The PDB atom line follows the standard PDB format specification with customizable indices:

```
Column  Field        Content
------  -----        -------
1-6     Record type  "ATOM  " or "HETATM"
7-11    Atom serial  Integer (or hex if >99999)
13-16   Atom name    From input PDB
18-21   Residue name From input PDB  
22      Chain ID     From chain/changechains logic
23-26   Residue seq  Integer (or hex if >9999)
27      Insertion    From input PDB
31-38   X coord      Computed position
39-46   Y coord      Computed position
47-54   Z coord      Computed position
55-80   Other fields From input PDB (B-factor, etc.)
```

**Sources:** [src/output.f90:135-137](), [src/output.f90:287-300]()

## Tinker XYZ Format

The Tinker format includes atomic connectivity information required by the Tinker molecular modeling package.

### Tinker Output Structure

```mermaid
graph TD
    START["Write Tinker Output<br/>output.f90:473-536"] --> HEADER["Write header line<br/>natoms + title<br/>output.f90:479"]
    
    HEADER --> INIT["Initialize counters<br/>ilubar, ilugan, icart<br/>output.f90:481-486"]
    
    INIT --> TYPE_LOOP["For each molecule type<br/>output.f90:488"]
    
    TYPE_LOOP --> CHECK_FIXED{"Fixed molecule?"}
    
    CHECK_FIXED -->|No| MOVABLE["Process movable molecules<br/>output.f90:490-516"]
    CHECK_FIXED -->|Yes| FIXED["Process fixed molecules<br/>output.f90:518-531"]
    
    MOVABLE --> TRANSFORM["Transform coordinates<br/>eulerrmat + compcart<br/>output.f90:500-506"]
    FIXED --> WRITE_FIXED["Write fixed coords<br/>output.f90:528"]
    
    TRANSFORM --> ADJ_CONNECT["Adjust connectivity indices<br/>ntcon = nconnect + i_ref_atom<br/>output.f90:508"]
    
    ADJ_CONNECT --> WRITE_LINE["Write Tinker atom line<br/>output.f90:509"]
    WRITE_FIXED --> WRITE_LINE_F["Write Tinker atom line<br/>output.f90:528"]
    
    WRITE_LINE --> TYPE_LOOP
    WRITE_LINE_F --> TYPE_LOOP
    
    TYPE_LOOP -->|Done| CLOSE["Close file<br/>output.f90:535"]
```

**Sources:** [src/output.f90:473-536]()

### Tinker Atom Line Format

Each atom line in Tinker format contains:

```
Field       Content
-----       -------
Atom index  Sequential integer
Element     3-character element symbol
X, Y, Z     Cartesian coordinates (3 x 10.6 format)
Connects    Up to 9 connectivity indices
```

The connectivity indices are adjusted to reflect the absolute atom numbering in the output file using the formula: `ntcon(k) = nconnect(idatom,k) + i_ref_atom`.

**Sources:** [src/output.f90:475](), [src/output.f90:507-509]()

## Standard XYZ Format

The simplest output format, containing only atom types and Cartesian coordinates.

### XYZ Output Process

```mermaid
graph LR
    START["Write XYZ Output<br/>output.f90:93-131"] --> COUNT["Write atom count<br/>output.f90:95"]
    COUNT --> TITLE["Write title line<br/>output.f90:96"]
    TITLE --> LOOP["Loop over molecule types<br/>output.f90:102-128"]
    
    LOOP --> CHECK{"Fixed?"}
    CHECK -->|No| TRANSFORM["Transform coords<br/>eulerrmat + compcart<br/>output.f90:106-116"]
    CHECK -->|Yes| WRITE_FIXED["Write fixed coords<br/>coor(idatom,1:3)<br/>output.f90:126"]
    
    TRANSFORM --> WRITE_MOV["Write movable coords<br/>ele + xcart<br/>output.f90:116"]
    
    WRITE_MOV --> LOOP
    WRITE_FIXED --> LOOP
    LOOP -->|Done| CLOSE["Close file<br/>output.f90:130"]
```

**Sources:** [src/output.f90:93-131]()

### XYZ Line Format

```
Format: element_symbol  x_coord  y_coord  z_coord
Example: C     12.345678    23.456789    34.567890
```

The format string is: `"( tr2,a3,tr2,3(tr2,f14.6) )"` which produces 3-character element symbols followed by three 14.6 floating-point coordinates.

**Sources:** [src/output.f90:116](), [src/output.f90:126]()

## CHARMM CRD Format

The CHARMM CRD format is written as a supplemental output when `writecrd` is specified, always in conjunction with PDB output.

### CRD File Structure

```mermaid
graph TD
    START["CRD Output<br/>output.f90:141-149"] --> HEADER["Write TITLE lines<br/>output.f90:143-147"]
    HEADER --> NATOMS["Write atom count + 'EXT'<br/>output.f90:148"]
    NATOMS --> ATOM_LOOP["Write atom records<br/>output.f90:302-312"]
    
    ATOM_LOOP --> FORMAT_LINE["Format atom line<br/>crd_format string<br/>output.f90:138"]
    
    FORMAT_LINE --> FIELDS["Fields:<br/>atom_id, residue_id<br/>residue_name, atom_name<br/>x, y, z<br/>segid, residue_str<br/>charge"]
    
    FIELDS --> WRITE["Write CRD line<br/>output.f90:309-311"]
```

**Sources:** [src/output.f90:138-149](), [src/output.f90:302-312]()

### CRD Format Specification

The CRD format string is: `'(2I10,2X,A8,2X,A8,3F20.10,2X,A8,2X,A8,F20.10)'`

| Field | Format | Description |
|-------|--------|-------------|
| Atom serial | I10 | Atom index (10 digits) |
| Residue serial | I10 | Residue index (10 digits) |
| Residue name | A8 | 8-character residue name |
| Atom name | A8 | 8-character atom name |
| X, Y, Z | 3F20.10 | Coordinates (20.10 format each) |
| Segment ID | A8 | 8-character segment identifier |
| Residue string | A8 | Residue number as string |
| Charge | F20.10 | Atomic charge (written as 0.0) |

The CRD format supports up to 99,999,999 residues before wrapping (vs. 9,999 for PDB).

**Sources:** [src/output.f90:138](), [src/output.f90:302-312](), [src/getinp.f90:883-886]()

## Connectivity Information

Connectivity (CONECT records in PDB, connectivity indices in Tinker) is read from input files and written to output files.

### Connectivity Writing Process

```mermaid
graph TD
    START["write_connect subroutine<br/>output.f90:565-598"] --> CHECK["Check maxcon(iiat)<br/>output.f90:573"]
    CHECK -->|0| RETURN["Return (no connectivity)<br/>output.f90:573"]
    CHECK -->|>0| INIT["Initialize CONECT line<br/>output.f90:577"]
    
    INIT --> LOOP["Loop over connections<br/>output.f90:578-597"]
    
    LOOP --> ADD_INDEX["Add connection index<br/>i5hex(nconnect+ifirst-1)<br/>output.f90:579"]
    
    ADD_INDEX --> CHECK_FINISH{"Last connection or<br/>line full (5 atoms)?"}
    
    CHECK_FINISH -->|Yes| WRITE_LINE["Write CONECT line<br/>output.f90:583,592"]
    CHECK_FINISH -->|No| CHECK_ORDER{"Next index ><br/>current index?"}
    
    CHECK_ORDER -->|Yes| CONTINUE["Add to same line<br/>output.f90:588"]
    CHECK_ORDER -->|No| NEW_LINE["Start new CONECT line<br/>output.f90:594"]
    
    WRITE_LINE --> LOOP
    CONTINUE --> LOOP
    NEW_LINE --> LOOP
    
    LOOP -->|Done| RETURN_END["Return"]
```

**Sources:** [src/output.f90:565-598]()

### CONECT Record Format

CONECT records follow PDB format specifications:
- Maximum of 4 bonded atoms per line (excluding the central atom)
- Multiple CONECT lines for atoms with >4 bonds
- Indices must be in increasing order
- Uses `i5hex` formatting for hexadecimal support

**Sources:** [src/output.f90:565-598](), [src/output.f90:541-551]()

## Restart Files

Packmol can write restart files containing generalized coordinates (center of mass + Euler angles) for molecular configurations.

### Restart File Structure

```mermaid
graph TD
    START["Write Restart Files<br/>output.f90:46-89"] --> CHECK_ALL{"restart_to(0)<br/>!= 'none'?"}
    
    CHECK_ALL -->|Yes| WRITE_ALL["Write all-system restart<br/>output.f90:48-63"]
    CHECK_ALL -->|No| TYPE_LOOP
    
    WRITE_ALL --> LOOP_ALL["For each molecule:<br/>xcm(1:3), angles(1:3)<br/>output.f90:57-61"]
    LOOP_ALL --> TYPE_LOOP["Check per-type restarts<br/>output.f90:68-89"]
    
    TYPE_LOOP --> CHECK_TYPE{"restart_to(itype)<br/>!= 'none'?"}
    
    CHECK_TYPE -->|Yes| WRITE_TYPE["Write type-specific restart<br/>output.f90:71-84"]
    CHECK_TYPE -->|No| SKIP["Skip to next type<br/>output.f90:85-88"]
    
    WRITE_TYPE --> LOOP_TYPE["For each molecule of type:<br/>xcm(1:3), angles(1:3)<br/>output.f90:78-82"]
    
    LOOP_TYPE --> TYPE_LOOP
    SKIP --> TYPE_LOOP
    TYPE_LOOP -->|Done| MAIN_OUTPUT["Continue to main output"]
```

**Sources:** [src/output.f90:46-89]()

### Restart File Format

Each line in a restart file contains 6 floating-point values in scientific notation:

```
x_cm  y_cm  z_cm  beta  gama  teta
```

Where:
- `x_cm, y_cm, z_cm`: Center of mass coordinates
- `beta, gama, teta`: Euler angles (in radians)

Format string: `"(6(tr1,es23.16))"` - 6 values with 23.16 scientific notation

**Sources:** [src/output.f90:58]()

### Restart File Usage

Restart files are specified per structure or globally:

```
# Global restart files
restart_from <input_file>    # Read initial positions
restart_to <output_file>      # Write final positions

# Per-structure restart files  
structure ...
  restart_from <input_file>   # For this structure type only
  restart_to <output_file>    # For this structure type only
end structure
```

Fixed molecules cannot use restart files, as validated during input processing.

**Sources:** [src/getinp.f90:889-928](), [app/packmol.f90:153-158]()

## Coordinate Transformation for Output

All movable molecules undergo coordinate transformation from generalized coordinates to Cartesian coordinates before output.

### Transformation Pipeline

```mermaid
graph LR
    GEN["Generalized Coords<br/>x array: xcm + angles"] --> EULER["Euler Rotation Matrix<br/>eulerrmat(beta,gama,teta)<br/>output.f90:110,243"]
    
    EULER --> ROT_MAT["Rotation vectors<br/>v1, v2, v3"]
    
    ROT_MAT --> COMP["Compose Cartesian<br/>compcart(xcart,xcm,coor,v1,v2,v3)<br/>output.f90:115,263"]
    
    COMP --> CART["Cartesian Coords<br/>xcart array"]
    
    subgraph "For Fixed Molecules"
        FIXED_IN["coor array<br/>(from input)"] --> FIXED_OUT["Direct output<br/>No transformation"]
    end
```

**Sources:** [src/output.f90:106-116](), [src/output.f90:239-263]()

### Variable Indexing

The output subroutine uses several index variables to traverse the coordinate arrays:

| Variable | Purpose | Usage |
|----------|---------|-------|
| `ilubar` | Index into center-of-mass positions (`x(1:3*ntotmol)`) | [output.f90:55,97]() |
| `ilugan` | Index into Euler angles (`x(3*ntotmol+1:6*ntotmol)`) | [output.f90:56,98]() |
| `icart` | Index into Cartesian coordinate array `xcart` | [output.f90:99,113]() |
| `idatom` | Index into reference coordinate array `coor` | [output.f90:111,114]() |
| `i_ref_atom` | Running atom counter for output file | [output.f90:176,262]() |

**Sources:** [src/output.f90:55-99](), [src/output.f90:173-177]()

## Output File Name Specification

The output file name is specified using the `output` keyword in the input file:

```
output <filename>
```

The filename is validated during input processing. If missing or incorrectly specified, Packmol exits with an error.

**Sources:** [src/getinp.f90:258-272]()

### Output Filename Handling

```mermaid
graph TD
    START["Input Processing<br/>getinp.f90:258"] --> INIT["Initialize xyzout = '####'<br/>getinp.f90:260"]
    
    INIT --> SEARCH["Search for 'output' keyword<br/>getinp.f90:261-266"]
    
    SEARCH --> FOUND{"Found output keyword?"}
    
    FOUND -->|Yes| SET["Set xyzout = keyword(iline,2)<br/>getinp.f90:263-264"]
    FOUND -->|No| CHECK
    
    SET --> CHECK{"xyzout == '####'?"}
    
    CHECK -->|Yes| ERROR["ERROR: Output file not specified<br/>getinp.f90:268-270"]
    CHECK -->|No| DISPLAY["Display output filename<br/>getinp.f90:272"]
    
    ERROR --> EXIT["exit_code_input_error"]
    DISPLAY --> CONTINUE["Continue processing"]
```

**Sources:** [src/getinp.f90:258-272]()

---