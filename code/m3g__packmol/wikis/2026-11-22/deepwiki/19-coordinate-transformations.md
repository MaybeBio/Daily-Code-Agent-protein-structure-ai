# Coordinate Transformations

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/computef.f90](src/computef.f90)
- [src/computeg.f90](src/computeg.f90)
- [src/initial.f90](src/initial.f90)

</details>



## Purpose and Scope

This page documents Packmol's coordinate transformation system, which converts between three representations: generalized coordinates (center of mass + Euler angles), reference coordinates (molecular templates), and Cartesian coordinates (3D atom positions). These transformations are fundamental to the optimization process and appear in every function and gradient evaluation.

For information about how these coordinates are used in the optimization loop, see [Optimization Engine (GENCAN)](#4.4). For details on how Cartesian coordinates are used in spatial queries, see [Spatial Management System](#4.5).

---

## Overview of Coordinate Representations

Packmol maintains three distinct coordinate representations to enable efficient optimization of molecular packing:

```mermaid
graph TB
    GEN["Generalized Coordinates<br/>(x array)<br/>Position: xcm[3]<br/>Orientation: beta, gamma, theta"]
    REF["Reference Coordinates<br/>(coor array)<br/>Molecular template<br/>Atom positions relative to CM"]
    CART["Cartesian Coordinates<br/>(xcart array)<br/>Final 3D positions<br/>All atoms in space"]
    
    GEN -->|"eulerrmat<br/>compcart"| CART
    REF -->|"compcart"| CART
    
    CART -->|"Chain rule<br/>dv1beta, dv2beta, etc."| GRAD["Gradient in<br/>Generalized Space<br/>(g array)"]
    
    style GEN fill:#f9f9f9
    style REF fill:#f9f9f9
    style CART fill:#f9f9f9
    style GRAD fill:#f9f9f9
```

**Sources:** [src/computef.f90:38-72](), [src/computeg.f90:39-66](), [src/initial.f90:121-138]()

---

## Generalized Coordinates (x array)

The optimization variables are stored in the `x(n)` array using a two-block structure:

| Block | Range | Content | Description |
|-------|-------|---------|-------------|
| Position | `1` to `ntotmol*3` | `xcm[1:3]` for each molecule | Center of mass coordinates (x, y, z) |
| Orientation | `ntotmol*3+1` to `n` | `beta, gamma, theta` for each molecule | Euler angles defining rotation |

The array is accessed using index variables `ilubar` (position block) and `ilugan` (angle block):

```mermaid
graph LR
    subgraph "x array structure"
        POS["Position Block<br/>ilubar indices<br/>Molecule 1: x[1:3]<br/>Molecule 2: x[4:6]<br/>...<br/>Molecule N: x[3N-2:3N]"]
        ANG["Angle Block<br/>ilugan indices<br/>Molecule 1: x[3N+1:3N+3]<br/>Molecule 2: x[3N+4:3N+6]<br/>...<br/>Molecule N: x[6N-2:6N]"]
    end
    
    POS --> ITER1["ilubar += 3<br/>per molecule"]
    ANG --> ITER2["ilugan += 3<br/>per molecule"]
    
    style POS fill:#f9f9f9
    style ANG fill:#f9f9f9
```

### Position Block Layout

For a system with `ntype` molecule types, each containing `nmols(itype)` molecules:

```fortran
ilubar = 0
do itype = 1, ntype
  do imol = 1, nmols(itype)
    xcm(1:3) = x(ilubar+1:ilubar+3)  ! Center of mass
    ilubar = ilubar + 3
  end do
end do
```

**Sources:** [src/computef.f90:40-52](), [src/initial.f90:89-116]()

### Angle Block Layout

The Euler angles follow the same molecule ordering as positions, starting at offset `ntotmol*3`:

```fortran
ilugan = ntotmol*3
do itype = 1, ntype
  do imol = 1, nmols(itype)
    beta  = x(ilugan+1)
    gamma = x(ilugan+2)
    theta = x(ilugan+3)
    ilugan = ilugan + 3
  end do
end do
```

Angles can be constrained to specific ranges using `constrain_rot(itype, axis)` and `rot_bound(itype, axis, 1:2)`. Unconstrained angles are initialized in the full range `[0, 2π]`.

**Sources:** [src/computef.f90:56-58](), [src/initial.f90:96-116](), [src/initial.f90:431-458]()

---

## Reference Coordinates (coor array)

The `coor` array stores template molecular structures with atom positions relative to the molecular center of mass:

| Array | Dimensions | Content |
|-------|------------|---------|
| `coor(idatom, 1:3)` | `maxatom × 3` | Reference (x, y, z) for each atom |
| `idfirst(itype)` | `ntype` | Index of first atom for molecule type |
| `natoms(itype)` | `ntype` | Number of atoms per molecule type |

Atoms are accessed using an offset pattern:

```fortran
idatom = idfirst(itype) - 1
do iatom = 1, natoms(itype)
  idatom = idatom + 1
  ! coor(idatom, 1:3) contains reference coordinates
end do
```

These reference coordinates are read from PDB or XYZ files during input parsing and remain constant throughout optimization. They define the rigid molecular geometry.

**Sources:** [src/computef.f90:64-68](), [src/computeg.f90:61-65](), [src/initial.f90:56-70]()

---

## Cartesian Coordinates (xcart array)

The `xcart(icart, 1:3)` array stores the actual 3D positions of all atoms in the system:

```mermaid
graph TB
    subgraph "xcart array"
        MOV["Movable Atoms<br/>icart: 1 to ntotat-nfixedat<br/>Updated each iteration"]
        FIX["Fixed Atoms<br/>icart: ntotat-nfixedat+1 to ntotat<br/>Constant positions"]
    end
    
    MOV --> CELL["setcell()<br/>Assign to spatial cells"]
    MOV --> DIST["Distance calculations<br/>fparc, gparc"]
    MOV --> CONST["Constraint checks<br/>comprest, gwalls"]
    
    FIX --> FCELL["Fixed cell lists<br/>latomfix"]
    
    style MOV fill:#f9f9f9
    style FIX fill:#f9f9f9
```

The `icart` index increments linearly through all atoms:

```fortran
icart = 0
do itype = 1, ntype
  do imol = 1, nmols(itype)
    do iatom = 1, natoms(itype)
      icart = icart + 1
      ! xcart(icart, 1:3) contains Cartesian position
    end do
  end do
end do
```

Additional metadata arrays indexed by `icart`:
- `ibtype(icart)`: Molecule type index
- `ibmol(icart)`: Molecule number within type
- `fixedatom(icart)`: Boolean flag for fixed atoms
- `latomnext(icart)`: Linked list pointer for spatial indexing

**Sources:** [src/computef.f90:42-101](), [src/initial.f90:123-165]()

---

## Transformation: Generalized to Cartesian

### Step 1: Euler Rotation Matrix (eulerrmat)

The `eulerrmat` subroutine computes three basis vectors `v1`, `v2`, `v3` from Euler angles:

```mermaid
graph LR
    ANGLES["Euler Angles<br/>beta, gamma, theta"] --> TRIG["Trigonometric<br/>Functions<br/>cb, sb, cg, sg, ct, st"]
    TRIG --> V1["v1[3]<br/>First basis vector"]
    TRIG --> V2["v2[3]<br/>Second basis vector"]
    TRIG --> V3["v3[3]<br/>Third basis vector"]
    
    V1 --> ROT["Rotation Matrix<br/>[v1 | v2 | v3]"]
    V2 --> ROT
    V3 --> ROT
    
    style ANGLES fill:#f9f9f9
    style ROT fill:#f9f9f9
```

The rotation matrix columns are:

```
v1 = [ sb*sg*ct + cb*cg,   sb*cg*ct - cb*sg,   sb*st ]
v2 = [ cb*sg*ct - sb*cg,   cb*cg*ct + sb*sg,   cb*st ]
v3 = [      -sg*st,             cg*st,           ct   ]
```

Where: `cb = cos(beta)`, `sb = sin(beta)`, `cg = cos(gamma)`, `sg = sin(gamma)`, `ct = cos(theta)`, `st = sin(theta)`

**Sources:** [src/computef.f90:60](), [src/computeg.f90:60](), [src/initial.f90:130]()

### Step 2: Cartesian Composition (compcart)

The `compcart` subroutine applies the rotation matrix and translation:

```mermaid
graph LR
    XCM["Center of Mass<br/>xcm[3]"] --> ADD["Vector Addition"]
    COOR["Reference Position<br/>coor[idatom, 1:3]"] --> ROT["Matrix-Vector<br/>Multiplication<br/>v1, v2, v3"]
    ROT --> ADD
    ADD --> XCART["Cartesian Position<br/>xcart[icart, 1:3]"]
    
    style XCM fill:#f9f9f9
    style COOR fill:#f9f9f9
    style XCART fill:#f9f9f9
```

The mathematical formula:

```
xcart[icart, :] = xcm[:] + coor[idatom, 1] * v1[:] 
                         + coor[idatom, 2] * v2[:] 
                         + coor[idatom, 3] * v3[:]
```

This transformation appears in three key locations:

1. **Initial point generation:** [src/initial.f90:126-138]()
2. **Function evaluation:** [src/computef.f90:52-72]()
3. **Gradient evaluation:** [src/computeg.f90:54-66]()

**Sources:** [src/computef.f90:72](), [src/computeg.f90:66](), [src/initial.f90:135]()

---

## Full Transformation Pipeline

```mermaid
flowchart TD
    START["Start with x array"] --> EXTRACT["Extract for molecule imol:<br/>xcm = x[ilubar+1:ilubar+3]<br/>beta = x[ilugan+1]<br/>gamma = x[ilugan+2]<br/>theta = x[ilugan+3]"]
    
    EXTRACT --> EULER["call eulerrmat(beta, gamma, theta, v1, v2, v3)"]
    
    EULER --> LOOP["Loop over atoms:<br/>do iatom = 1, natoms(itype)"]
    
    LOOP --> COMP["call compcart(<br/>  xcart[icart,1:3],<br/>  xcm,<br/>  coor[idatom,1:3],<br/>  v1, v2, v3)"]
    
    COMP --> STORE["xcart[icart,:] now contains<br/>3D Cartesian position"]
    
    STORE --> MORE{"More<br/>atoms?"}
    MORE -->|Yes| INCR["icart += 1<br/>idatom += 1"]
    INCR --> LOOP
    MORE -->|No| NEXT["ilubar += 3<br/>ilugan += 3<br/>Next molecule"]
    
    style START fill:#f9f9f9
    style EULER fill:#e8f4f8
    style COMP fill:#e8f4f8
    style STORE fill:#f9f9f9
```

**Sources:** [src/computef.f90:40-108](), [src/computeg.f90:43-96]()

---

## Gradient Transformation via Chain Rule

Computing gradients requires the reverse transformation: from Cartesian gradient `gxcar(icart, k)` to generalized gradient `g(n)`.

### Cartesian Gradient Accumulation

During function evaluation, gradients are accumulated in `gxcar`:

```fortran
gxcar(icart, 1:3) = 0.d0  ! Reset
! Distance penalties contribute via gparc
! Constraint penalties contribute via gwalls
```

**Sources:** [src/computeg.f90:33](), [src/computeg.f90:69-71](), [src/computeg.f90:99-143]()

### Position Gradient (Direct)

The gradient with respect to center of mass is straightforward:

```fortran
do k = 1, 3
  g(k1+k) = g(k1+k) + gxcar(icart, k)
end do
```

This is a direct copy because `∂xcart/∂xcm = I` (identity matrix).

**Sources:** [src/computeg.f90:212-214]()

### Angle Gradient (Chain Rule)

The gradient with respect to Euler angles requires the chain rule:

```
g(k2+1) += Σ_k [∂xcart_k/∂beta  * gxcar(icart, k)]
g(k2+2) += Σ_k [∂xcart_k/∂gamma * gxcar(icart, k)]
g(k2+3) += Σ_k [∂xcart_k/∂theta * gxcar(icart, k)]
```

The partial derivatives are:

```
∂xcart_k/∂beta  = coor[idatom,1] * dv1beta[k]  + coor[idatom,2] * dv2beta[k]  + coor[idatom,3] * dv3beta[k]
∂xcart_k/∂gamma = coor[idatom,1] * dv1gamma[k] + coor[idatom,2] * dv2gamma[k] + coor[idatom,3] * dv3gamma[k]
∂xcart_k/∂theta = coor[idatom,1] * dv1theta[k] + coor[idatom,2] * dv2theta[k] + coor[idatom,3] * dv3theta[k]
```

**Sources:** [src/computeg.f90:217-234]()

### Rotation Matrix Derivatives

The `dv*` arrays contain derivatives of the rotation matrix basis vectors:

```mermaid
graph TB
    subgraph "Derivative Arrays"
        DVB["dv1beta, dv2beta, dv3beta<br/>∂[v1,v2,v3]/∂beta"]
        DVG["dv1gamma, dv2gamma, dv3gamma<br/>∂[v1,v2,v3]/∂gamma"]
        DVT["dv1theta, dv2theta, dv3theta<br/>∂[v1,v2,v3]/∂theta"]
    end
    
    TRIG["Trigonometric<br/>cb, sb, cg, sg, ct, st"] --> DVB
    TRIG --> DVG
    TRIG --> DVT
    
    DVB --> CHAIN["Chain Rule<br/>Multiplication"]
    DVG --> CHAIN
    DVT --> CHAIN
    
    COOR["coor[idatom,1:3]"] --> CHAIN
    GXCAR["gxcar[icart,k]"] --> CHAIN
    
    CHAIN --> GRAD["g[k2+1:k2+3]"]
    
    style DVB fill:#f9f9f9
    style DVG fill:#f9f9f9
    style DVT fill:#f9f9f9
```

Example derivatives for `dv1beta`:

```fortran
dv1beta(1) = - cb * sg * ct - sb * cg
dv1beta(2) = - cb * cg * ct + sb * sg
dv1beta(3) =   cb * st
```

All 27 derivatives (9 per angle) are computed from trigonometric functions in [src/computeg.f90:162-204]().

**Sources:** [src/computeg.f90:158-204](), [src/computeg.f90:217-234]()

---

## Index Management Pattern

The transformation code follows a consistent index management pattern across all three arrays:

```mermaid
graph LR
    subgraph "Index Variables"
        K1["k1, k2<br/>Generalized gradient<br/>Position and angle offsets"]
        ILUBAR["ilubar, ilugan<br/>Generalized coordinates<br/>Position and angle offsets"]
        ICART["icart<br/>Cartesian coordinates<br/>Linear atom index"]
        IDATOM["idatom<br/>Reference coordinates<br/>Template atom index"]
    end
    
    K1 --> GARRAY["g array"]
    ILUBAR --> XARRAY["x array"]
    ICART --> XCARR["xcart array"]
    IDATOM --> COORR["coor array"]
    
    style K1 fill:#f9f9f9
    style ILUBAR fill:#f9f9f9
    style ICART fill:#f9f9f9
    style IDATOM fill:#f9f9f9
```

Typical loop structure:

```fortran
k1 = 0              ! Position gradient offset
k2 = ntotmol * 3    ! Angle gradient offset
ilubar = 0          ! Position variable offset
ilugan = ntotmol*3  ! Angle variable offset
icart = 0           ! Cartesian atom index

do itype = 1, ntype
  idatom = idfirst(itype) - 1  ! Reference offset
  
  do imol = 1, nmols(itype)
    ! Use ilubar, ilugan for x array access
    ! Use icart for xcart array access
    ! Use idatom for coor array access
    
    do iatom = 1, natoms(itype)
      icart = icart + 1
      idatom = idatom + 1
      ! Process atom
    end do
    
    ilubar = ilubar + 3
    ilugan = ilugan + 3
    k1 = k1 + 3
    k2 = k2 + 3
  end do
end do
```

**Sources:** [src/computeg.f90:147-241](), [src/computef.f90:40-108]()

---

## Type Masking with comptype

The `comptype(itype)` boolean array controls which molecule types are included in transformations:

| Mode | `comptype` State | Purpose |
|------|------------------|---------|
| Full optimization | All `.true.` | All molecules optimized together |
| Type-specific (via `swaptype`) | One type `.true.`, rest `.false.` | Isolate single molecule type |
| Initialization | Per-phase | Sequential constraint satisfaction |

This masking appears in loops:

```fortran
if(.not.comptype(itype)) then
  icart = icart + nmols(itype)*natoms(itype)
  cycle
end if
```

When a type is masked, its atoms are skipped but `icart` still increments to maintain consistent indexing.

**Sources:** [src/computef.f90:45-48](), [src/computeg.f90:49-52](), [src/initial.f90:44-45]()

---

## Performance Considerations

The coordinate transformation is performed in every function and gradient evaluation, making it performance-critical:

1. **Function evaluations:** Transform all atoms to compute distances and constraints
2. **Gradient evaluations:** Transform all atoms, then apply chain rule for all atoms
3. **Typical call frequency:** Hundreds to thousands of times per optimization

Key optimizations:
- In-place updates of `xcart` array
- Reuse of trigonometric values (`cb`, `sb`, etc.)
- Cell indexing built during transformation to avoid separate pass
- Skipping masked types via `comptype`

The transformation cost is O(ntotat) where `ntotat` is the total number of atoms. This is acceptable since subsequent distance calculations are O(ntotat) using cell indexing (see [Spatial Management System](#4.5)).

**Sources:** [src/computef.f90:1-154](), [src/computeg.f90:1-244]()

---