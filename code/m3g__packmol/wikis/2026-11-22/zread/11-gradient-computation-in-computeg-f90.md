

The gradient computation subsystem in packmol implements analytical derivatives for the molecular packing optimization problem, transforming geometric constraints into gradient information that drives the GENCAN optimization algorithm. This system operates through a multi-stage pipeline: coordinate transformation, pairwise interaction gradients, spatial constraint gradients, and chain-rule backpropagation to optimization variables.

## Architectural Overview

The gradient computation follows a structured flow that mirrors the objective function evaluation while computing derivatives for all optimization variables simultaneously:

```mermaid
flowchart TD
    A[Input: x vector<br/>(baricenters + Euler angles)] --> B[Coordinate Transformation<br/>eulerrmat + compcart]
    B --> C[Initialize Gradient Arrays<br/>gxcar(:,:) = 0]
    C --> D[Spatial Constraint Gradients<br/>gwalls for each atom restraint]
    D --> E[Cell Indexing Setup<br/>Build neighbor lists]
    E --> F[Pairwise Distance Gradients<br/>gparc via cell neighbor traversal]
    F --> G[Chain Rule Backpropagation<br/>Transform gxcar → g]
    G --> H[Output: g vector<br/>Gradients for all variables]
    
    style B fill:#e1f5fe
    style F fill:#e1f5fe
    style G fill:#fff3e0
```

The computational strategy separates gradient accumulation into Cartesian space (`gxcar`) from the final optimization variable space (`g`), enabling efficient computation of pairwise interactions before applying the coordinate transformation derivatives.

## Coordinate Transformation and Gradient Accumulation

The gradient computation begins by transforming the optimization variable vector `x` (containing molecular baricenters and Euler angles) into Cartesian coordinates for all atoms, simultaneously initializing the Cartesian gradient array:

```fortran
! Reset gradients
gxcar(:,:) = 0.d0
```

The transformation loop iterates over all molecule types and individual molecules, extracting baricenter coordinates (`ilubar` index) and Euler angles (`ilugan` index) from the optimization vector. For each molecule, the rotation matrix is computed via `eulerrmat(beta,gama,teta,v1,v2,v3)` and applied to transform reference coordinates to Cartesian space [polartocart.f90#L22-L37]. This mirrors the transformation in the objective function [computef.f90#L44-L63], ensuring consistency between function and gradient computations.

During the coordinate transformation phase, each atom undergoes spatial constraint gradient evaluation:

```fortran
! Gradient relative to the wall distance
do iratcount = 1, nratom(icart)
   irest = iratom(icart,iratcount)
   call gwalls(icart,irest)
end do
```

This accumulates gradient contributions from all spatial restraints (boxes, spheres, cylinders, planes) into `gxcar(icart,:)` for each atom. The `gwalls` subroutine computes analytical derivatives for various constraint types, adding contributions proportional to constraint violations.

## Cell Indexing and Neighbor Search

For computational efficiency in gradient calculation, atoms are organized into a three-dimensional cell grid that enables O(N) neighbor detection rather than O(N²) pairwise checks:

```fortran
if(.not.init1) then
   call setcell(xcart(icart,:),cell)
   ! Atom linked list
   latomnext(icart) = latomfirst(cell(1),cell(2),cell(3))
   latomfirst(cell(1),cell(2),cell(3)) = icart
   
   ! cell with atoms linked list
   if ( empty_cell(cell(1),cell(2),cell(3))) then
      empty_cell(cell(1),cell(2),cell(3)) = .false.
      icell = index_cell(cell,ncells)
      lcellnext(icell) = lcellfirst
      lcellfirst = icell
   end if
   
   ibtype(icart) = itype
   ibmol(icart) = imol
end if
```

The `setcell` routine maps each atom's Cartesian coordinates to integer cell indices based on the system dimensions and cell size [cell_indexing.f90#L16-L22]. Atoms are linked within cells using `latomfirst` and `latomnext` arrays, while non-empty cells are tracked via `lcellfirst` and `lcellnext` to enable efficient traversal. This infrastructure is shared with the objective function [computef.f90#L65-L76].

## Pairwise Distance Gradients

The core computational load occurs during pairwise distance gradient calculation, which traverses all atom pairs that could potentially violate minimum distance constraints. The algorithm systematically checks interactions within each cell and with neighboring cells:

```fortran
! Gradient relative to minimum distance
icell = lcellfirst
do while( icell > 0 )
   call icell_to_cell(icell,ncells,cell)
   icart = latomfirst(i,j,k)
   do while( icart > 0 )
      if(comptype(ibtype(icart))) then
         ! Interactions inside cell
         call gparc(icart,latomnext(icart))
         ! Interactions of cells that share faces (6 faces - 3 forward)
         call gparc(icart,latomfirst(cell_ind(i+1, ncells(1)),j,k))
         call gparc(icart,latomfirst(i,cell_ind(j+1, ncells(2)),k))
         call gparc(icart,latomfirst(i,j,cell_ind(k+1, ncells(3))))
         ! Interactions of cells that share axes (12 edges - 6 forward)
         ! ... 6 edge interactions ...
         ! Interactions of cells that share vertices (8 vertices, 4 forward)
         ! ... 4 vertex interactions ...
      end if
      icart = latomnext(icart)
   end do
   icell = lcellnext(icell)
end do
```

This systematic neighbor traversal checks all 26 neighboring cells (3 face-sharing + 12 edge-sharing + 8 vertex-sharing) but only 13 forward directions to avoid double counting. The `gparc` subroutine computes gradient contributions for each atom pair:

```fortran
tol = (radius(icart)+radius(jcart))**2
vdiff = delta_vector(xcart(icart,:), xcart(jcart,:), pbc_length)
datom = (vdiff(1))**2 + (vdiff(2))**2 + (vdiff(3))**2
if( datom < tol ) then
   dtemp = fscale(icart)*fscale(jcart) * 4.d0 * (datom - tol)
   xdiff = dtemp*vdiff(1)
   gxcar(icart,1)= gxcar(icart,1) + xdiff
   gxcar(jcart,1)= gxcar(jcart,1) - xdiff
   ! ... repeat for y and z components ...
end if
```

The gradient computation follows from the penalty function f = scale × (r - r_min)⁴, with ∂f/∂x = 4 × scale × (r - r_min)³ × (x/r). The implementation uses squared distances to avoid unnecessary square root calculations [gparc.f90#L42-L63]. For periodic boundary conditions, `delta_vector` computes the minimum-image displacement using the system box dimensions [pbc.f90#L18-L22].

The algorithm efficiently skips irrelevant pairs through several filters:
- Fixed molecule pairs (both atoms fixed) contribute no gradients
- Atoms from the same molecule are excluded
- Pairs beyond their combined distance threshold are ignored
- These checks reduce computational complexity significantly for sparse violation scenarios

## Chain Rule Transformation to Optimization Variables

After computing all Cartesian gradients in `gxcar(:,:)`, the final stage transforms these back to gradient components for the optimization variables using the chain rule. This requires computing derivatives of the coordinate transformation with respect to each optimization parameter:

The transformation from optimization variables to Cartesian coordinates for an atom is:

```
x_cart = x_cm + R(β,γ,θ) × x_ref
```

where R is the rotation matrix parameterized by Euler angles (β, γ, θ). The gradient transformation requires:

```
∂f/∂x_cm = ∂f/∂x_cart × ∂x_cart/∂x_cm = gxcar
∂f/∂β = ∂f/∂x_cart × ∂x_cart/∂β = gxcar × (∂R/∂β × x_ref)
∂f/∂γ = ∂f/∂x_cart × ∂x_cart/∂γ = gxcar × (∂R/∂γ × x_ref)
∂f/∂θ = ∂f/∂x_cart × ∂x_cart/∂θ = gxcar × (∂R/∂θ × x_ref)
```

The implementation precomputes the rotation matrix derivatives for each molecule:

```fortran
cb = dcos(beta); sb = dsin(beta)
cg = dcos(gama); sg = dsin(gama)
ct = dcos(teta); st = dsin(teta)

dv1beta(1) = - cb * sg * ct - sb * cg
dv2beta(1) = - sb * sg * ct + cb * cg
dv3beta(1) = 0.d0

dv1gama(1) = - sb * cg * ct - cb * sg
dv2gama(1) =   cb * cg * ct - sb * sg
dv3gama(1) =   cg * st

dv1teta(1) =   sb * sg * st
dv2teta(1) = - cb * sg * st
dv3teta(1) =   sg * ct

! ... similar for other components ...
```

These derivative vectors represent ∂v₁/∂β, ∂v₂/∂β, ∂v₃/∂β (and similarly for γ, θ), where v₁, v₂, v₃ are the column vectors of the rotation matrix. The complete derivative matrix contains 27 components (9 matrix elements × 3 angles).

The gradient accumulation for each molecule loops over all atoms, applying the chain rule transformation:

```fortran
idatom = idfirst(itype) - 1
do iatom = 1, natoms(itype)
   icart = icart + 1
   idatom = idatom + 1
   
   ! Baricenter gradients (direct mapping)
   do k = 1, 3
      g(k1+k) = g(k1+k) + gxcar(icart, k)
   end do
   
   ! Angle gradients (chain rule with rotation derivatives)
   do k = 1, 3
      g(k2 + 1) = g(k2 + 1) &
         + (coor(idatom,1) * dv1beta(k) &
         + coor(idatom, 2) * dv2beta(k) &
         + coor(idatom, 3) * dv3beta(k)) &
         * gxcar(icart, k)
      
      g(k2 + 2) = g(k2 + 2) &
         + (coor(idatom,1) * dv1gama(k) &
         + coor(idatom, 2) * dv2gama(k) &
         + coor(idatom, 3) * dv3gama(k)) &
         * gxcar(icart, k)
      
      g(k2 + 3) = g(k2 + 3) &
         + (coor(idatom,1)  * dv1teta(k) &
         + coor(idatom, 2) * dv2teta(k) &
         + coor(idatom, 3) * dv3teta(k)) &
         * gxcar(icart, k)
   end do
end do
```

The indices `k1` and `k2` track the position in the optimization vector: `k1` for baricenter coordinates and `k2` for Euler angles. The expression `(coor(idatom,1) × dv1beta(k) + coor(idatom,2) × dv2beta(k) + coor(idatom,3) × dv3beta(k))` computes the k-th component of ∂R/∂β × x_ref.

## Gradient Verification

Packmol includes a gradient verification facility that compares analytical gradients with finite-difference approximations for validation:

```fortran
call computef(n,x,fx)
call computeg(n,x,g)

do i = 1, n
   error = 1.d20
   step = 1.d-2
   do while(error.gt.1.d-6.and.step.ge.1.d-20)
      call discret(i,n,x,gcomp,step)
      if(dmin1(abs(g(i)),abs(gcomp)).gt.1.d-10) then
         steperror = abs( ( gcomp - g(i) ) / g(i) )
      else
         steperror = abs( gcomp - g(i) )
      end if
      if( steperror .lt. error ) then
         error = steperror
         gbest = gcomp
         stepbest = step
      end if
      step = step / 10.d0
   end do
end do
```

The `discret` subroutine computes central finite differences: `∂f/∂x ≈ (f(x+h) - f(x-h)) / (2h)` [comparegrad.f90#L79-L88]. This verification can be enabled in input files using the `chkgrad` keyword and is particularly valuable during algorithm development or debugging complex constraint configurations.

> [!TIP]
> The analytical gradient implementation assumes differentiable penalty functions throughout. The use of squared distance comparisons (e.g., `datom < tol`) maintains differentiability as the function approaches zero, avoiding discontinuities that could destabilize the gradient-based optimization.

## Performance Considerations

The gradient computation design emphasizes efficiency through several key strategies:

**Computational Complexity**: The cell indexing approach reduces pairwise interaction checking from O(N²) to approximately O(N) for typical molecular packing problems, where N is the total number of atoms. The constant factor depends on the cell size relative to the maximum interaction distance.

**Memory Access Patterns**: The linked-list cell structure enables cache-friendly traversal patterns during neighbor checking. Atoms within a cell are processed sequentially before moving to neighboring cells.

**Numerical Precision**: All intermediate calculations use double precision (64-bit) floating point arithmetic, ensuring sufficient precision for gradient-based optimization even when violation penalties become large.

**Conditional Optimization**: The algorithm includes multiple early-exit conditions:
- Fixed molecule pairs are skipped immediately
- Atoms exceeding their combined radius threshold avoid distance calculations
- Empty cells are not traversed

> [!TIP]
> The `init1` flag controls cell structure initialization. When `init1 = .true.` (typically during initial stages), cell indexing is bypassed to avoid overhead when gradients are needed but spatial positions are still evolving significantly. This adaptive strategy balances accuracy with computational efficiency across optimization iterations.

## Data Structures and Memory Layout

The gradient computation relies on several key data structures from the `compute_data` module:

| Structure | Dimensions | Purpose | Access Pattern |
|-----------|------------|---------|----------------|
| `gxcar(:,:)` | (ntotat, 3) | Cartesian gradient accumulator | Read/write per atom |
| `xcart(:,:)` | (ntotat, 3) | Cartesian coordinates | Read-only during gradient calc |
| `coor(:,:)` | (ntotat, 3) | Reference coordinates | Read-only for chain rule |
| `latomfirst(:,:,:)` | (ncells) × 3 | Head of atom linked lists | Indexed access during traversal |
| `latomnext(:)` | (ntotat) | Next atom in cell | Sequential traversal |
| `radius(:)` | (ntotat) | Interaction radii | Read-only per atom pair |
| `fscale(:)` | (ntotat) | Scaling factors | Read-only per atom pair |

The array layout is optimized for column-major access patterns typical in Fortran, with the spatial dimension as the fastest-varying index. This layout enables efficient vectorization of the gradient accumulation loops.

## Integration with Optimization Algorithm

The gradient vector `g` returned by `computeg` directly serves the GENCAN optimization algorithm, which implements a gradient-based method for box-constrained optimization. The gradient provides the direction of steepest ascent in the objective function, guiding the search toward configurations that minimize overlap violations while satisfying spatial constraints.

The mathematical consistency between the objective function [computef.f90] and its gradient [computeg.f90] is critical for optimization convergence. Both functions use identical coordinate transformations, cell indexing logic, and penalty function formulations, ensuring that ∇f accurately represents the true gradient of f.

## Further Exploration

For deeper understanding of related components:

- **Objective Function**: See [Objective Function Design in computef.f90](10-objective-function-design-in-computef-f90) for the penalty function formulation being differentiated
- **Coordinate Systems**: [Molecular Coordinate Systems](13-molecular-coordinate-systems-baricenter-and-euler-angles) explains the Euler angle convention in detail
- **Optimization Algorithm**: [GENCAN Optimization Method Overview](9-gencan-optimization-method-overview) describes how gradients drive the optimization
- **Spatial Constraints**: [Spatial Constraints Syntax](5-spatial-constraints-syntax-box-sphere-plane-cylinder) documents the constraint types handled by `gwalls`
- **Cell Indexing**: [Cell Indexing for Efficient Neighbor Search](14-cell-indexing-for-efficient-neighbor-search) details the spatial partitioning algorithm
- **Periodic Boundaries**: [Periodic Boundary Conditions (PBC) Configuration](8-periodic-boundary-conditions-pbc-configuration) explains how PBC affects gradient calculations
