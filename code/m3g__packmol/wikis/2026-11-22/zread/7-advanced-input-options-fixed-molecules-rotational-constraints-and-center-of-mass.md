

This page explores three powerful input options that provide fine-grained control over molecular placement and orientation in Packmol: fixed molecule positioning, rotational constraints for oriented systems, and center of mass calculations for precise molecular positioning. These advanced features are essential for building complex biomolecular assemblies where specific spatial arrangements and orientations are required.

## Fixed Molecules

The `fixed` keyword allows you to position molecules at precise coordinates in space, preventing them from moving during optimization. This is particularly useful for positioning a protein in a solvent box, creating substrate-bound enzyme complexes, or maintaining specific molecular interactions.

When you specify a fixed molecule, Packmol reads the six parameters that define its position and orientation in space. The `fixed` keyword syntax requires three positional coordinates (x, y, z) and three rotational parameters that define the molecule's orientation. The code in `getinp.f90` parses these parameters when it encounters the `fixed` keyword [src/getinp.f90#L400-L414]. The system stores these as restriction type 1 in the `ityperest` array, with the six numerical values stored in `restpars`.

During initialization, fixed molecules are handled differently from mobile molecules. In `initial.f90`, the code checks if the `fix` flag is set and then processes fixed molecules separately [src/initial.f90#L125-L149]. The fixed molecule coordinates are copied directly from the input structure file to the Cartesian coordinate array (`xcart`) without modification, and the `fixedatom` flag is set to `.true.` for each atom in the fixed molecule.

```fortran
if(fix) then
  icart = ntotat - nfixedat
  do iftype = ntype + 1, ntype_with_fixed
    idfatom = idfirst(iftype) - 1
    do ifatom = 1, natoms(iftype)
      idfatom = idfatom + 1
      icart = icart + 1
      xcart(icart,1) = coor(idfatom,1)
      xcart(icart,2) = coor(idfatom,2)
      xcart(icart,3) = coor(idfatom,3)
      fixedatom(icart) = .true.
```

A critical safety feature is the validation of fixed molecule positions when using periodic boundary conditions (PBC). The code checks that every atom of every fixed molecule lies within the PBC box boundaries [src/initial.f90#L131-L142]. If any fixed atom falls outside the defined periodic boundaries, Packmol terminates with a clear error message indicating which atom and molecule are problematic.

> [!TIP]
> When using fixed molecules with PBC, ensure your fixed molecule coordinates are properly placed within the box boundaries before running Packmol. The system validates this at initialization to prevent optimization failures due to out-of-bounds atoms.

The optimization process respects the `fixedatom` flags throughout computation. When evaluating the objective function in `computef.f90`, fixed atoms contribute to distance calculations but are excluded from coordinate updates during gradient descent [src/computef.f90#L20-L50].

## Rotational Constraints

Rotational constraints provide control over molecular orientation by limiting the Euler angles (β, γ, θ) that define a molecule's rotation in 3D space. This feature is essential for creating anisotropic systems like lipid bilayers, aligned liquid crystals, or oriented membrane proteins.

The rotational constraint system uses two primary data structures: `constrain_rot(itype,3)` and `rot_bound(itype,3,2)`. The `constrain_rot` array is a three-element logical vector where each element corresponds to one of the Euler angles (beta, gamma, theta). If set to `.true.`, that angle is constrained during optimization [src/initial.f90#L55-L80].

The `rot_bound` array stores the constraint parameters as a 3×2 matrix for each molecule type, where each row represents one Euler angle and the two columns represent the center value and the tolerance range for that angle.

During initial random placement, the code checks rotational constraints for each molecule. In `initial.f90`, when generating random initial orientations, the code applies different strategies based on the constraint settings [src/initial.f90#L55-L80]:

```fortran
if ( constrain_rot(itype,1) ) then
  x(j+1) = ( rot_bound(itype,1,1) - dabs(rot_bound(itype,1,2)) ) + &
           2.d0*rnd()*dabs(rot_bound(itype,1,2))
else
  x(j+1) = twopi*rnd()
end if
```

For constrained angles, the random value is generated within a bounded range centered on `rot_bound(itype,angle,1)` with a width of `2 * rot_bound(itype,angle,2)`. For unconstrained angles, a full 0 to 2π range is used.

> [!TIP]
> Rotational constraints are applied independently to each Euler angle, giving you flexibility to constrain only specific rotational degrees of freedom. For example, you can fix the orientation of lipid headgroups normal to a bilayer while allowing rotation around the bilayer normal axis.

The impact of rotational constraints propagates through the optimization process. When converting between internal coordinates (baricenter + Euler angles) and Cartesian coordinates in `computef.f90`, the constrained angles are used directly from the optimization vector `x` [src/computef.f90#L20-L35]. This ensures that gradient descent operations respect the rotational bounds throughout the optimization.

Rotational constraints work synergistically with spatial constraints. A lipid molecule might be constrained to lie within a box (spatial constraint) while its orientation is constrained to align with the bilayer normal (rotational constraint). Both types of constraints contribute to the objective function penalty terms.

## Center of Mass Calculations

The center of mass (COM) calculation in Packmol serves dual purposes: positioning molecules relative to their geometric center and optimizing computational efficiency by reducing numerical artifacts. The `cenmass` subroutine implements a sophisticated COM calculation that handles both free and fixed molecules according to user specifications.

The algorithm first determines which molecule types require COM calculation. By default, all molecule types have COM calculation enabled (`domass(itype) = .true.`) [src/cenmass.f90#L15-L26]. However, this default can be modified by examining the input file for `fixed` and `centerofmass` keywords:

```fortran
do iline = 1, nlines
  if(keyword(iline,1).eq.'fixed') then
    do itype = 1, ntype
      if(iline.gt.linestrut(itype,1).and. &
         iline.lt.linestrut(itype,2)) then
        domass(itype) = .false.
      end if
    end do
  end if
end do
```

The `centerofmass` or `center` keyword can explicitly enable COM calculation for specific molecule types, even if they would otherwise be excluded [src/cenmass.f90#L27-L39].

The COM computation follows a standard weighted average algorithm. For each molecule type, the code calculates the total mass by summing individual atomic masses from the `amass` array [src/cenmass.f90#L44-L53]. Then, it computes the weighted sum of atomic coordinates and divides by the total mass:

```fortran
do itype = 1, ntype
  idatom = idfirst(itype) - 1
  do iatom = 1, natoms(itype)
    idatom = idatom + 1
    do k = 1, 3
      cm(itype, k) = cm(itype, k)  + coor(idatom, k)*amass(idatom)
    end do
  end do
  do k = 1, 3
    cm(itype, k) = cm(itype, k) / totm(itype)
  end do
end do
```

After computing COM, the system optionally centers molecules by subtracting the COM from each atomic coordinate [src/cenmass.f90#L63-L76]. This transformation moves the molecular origin to its center of mass, which improves numerical stability in distance calculations and makes spatial constraint specifications more intuitive.

The COM calculation has important implications for fixed molecules. When a fixed molecule is specified in the input file, its position and rotation parameters define where the COM should be placed, not any specific atom. This means if you use COM centering on your input structure files, the fixed position parameters will position the COM exactly as specified.

For PBC systems, COM centering can help avoid issues where molecules near periodic boundaries have their centers of mass placed outside the box. However, you should be aware that COM centering modifies the internal coordinates of molecules, which might affect the interpretation of results if the original frame of reference was significant.

The data structures involved in COM calculations include:
- `cm(ntype,3)`: Stores the computed center of mass for each molecule type
- `totm(ntype)`: Stores the total mass for each molecule type
- `domass(ntype)`: Logical flag indicating whether COM should be calculated and applied for each type
- `coor(ntotat,3)`: Atomic coordinates that are modified in place during COM centering

## Practical Configuration Examples

Here are common configuration patterns combining these advanced options:

**Protein Solvation with Fixed Protein:**
```
tolerance 2.0
output system.pdb

structure protein.pdb
  number 1
  fixed 0. 0. 0. 0. 0. 0.
  centerofmass
end structure

structure water.pdb
  number 1000
  inside box 0. 0. 0. 50. 50. 50.
end structure
```

**Lipid Bilayer with Oriented Lipids:**
```
tolerance 2.0
output bilayer.pdb

structure lipid.pdb
  number 200
  inside box 0. 0. -20. 50. 50. 20.
  constrain_rotation
  radius 10.
end structure

structure water.pdb
  number 2000
  outside cylinder 25. 25. 0. 0. 0. 1. 25.
end structure
```

**Fixed Substrate in Active Site:**
```
tolerance 1.5
output complex.pdb

structure enzyme.pdb
  number 1
  fixed 10. 10. 10. 0. 0. 0.
  number 1
  centerofmass
end structure

structure substrate.pdb
  number 1
  inside sphere 12. 12. 12. 3.
end structure
```

## Next Steps

Having mastered these advanced input options, you can now explore how they integrate with the broader system architecture:

- [Periodic Boundary Conditions (PBC) Configuration](8-periodic-boundary-conditions-pbc-configuration) - Learn how fixed molecules and rotational constraints interact with periodic systems
- [Molecular Coordinate Systems: Baricenter and Euler Angles](13-molecular-coordinate-systems-baricenter-and-euler-angles) - Understand the mathematical foundation of the rotation constraints
- [Distance Constraints and Overlap Detection](17-distance-constraints-and-overlap-detection) - See how fixed molecules participate in distance calculations
- [Creating Lipid Bilayers](26-creating-lipid-bilayers) - Practical application of rotational constraints for oriented systems
- [Solvating Proteins with Ions](27-solvating-proteins-with-ions) - Real-world examples using fixed protein scaffolds