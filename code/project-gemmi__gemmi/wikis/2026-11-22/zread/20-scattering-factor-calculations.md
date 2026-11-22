

The scattering factor calculations in Gemmi provide comprehensive support for X-ray, electron, and neutron diffraction analysis. This system enables crystallographers to compute atomic form factors, structure factors, and electron densities with high precision while maintaining computational efficiency through FFT-based approaches.

## Atomic Form Factor Foundations

### X-ray Form Factors

Gemmi implements the International Tables of Crystallography Vol. C (ITC) parametrization for X-ray atomic form factors using 4 Gaussian functions plus a constant term [docs/scattering.rst](docs/scattering.rst#L20-L23). The coefficients are accessible through the `IT92Coef` class in C++ ([include/gemmi/it92.hpp](include/gemmi/it92.hpp)) or as properties of elements in Python:

```python
>>> fe_coef = gemmi.Element('Fe').it92
>>> fe_coef.a  # Gaussian amplitudes
[11.7695, 7.3573, 3.5222, 2.3045]
>>> fe_coef.b  # Gaussian widths  
[4.7611, 0.3072, 15.3535, 76.8805]
>>> fe_coef.c  # Constant term
1.0369
```

The coefficients can be normalized for compatibility with programs like Refmac, and charge states can be controlled via the `IT92_set_ignore_charge()` function [docs/scattering.rst](docs/scattering.rst#L35-L55).

### Electron Form Factors

Electron scattering uses the C4322 parametrization from International Tables Volume C, table 4.3.2.2, with 5 Gaussian functions [docs/scattering.rst](docs/scattering.rst#L140-L150). Unlike X-ray factors, electron form factors don't include anomalous scattering contributions:

```python
>>> fe_coef = gemmi.Element('Fe').c4322
>>> fe_coef.a  # 5 Gaussian amplitudes
[0.3946, 1.2725, 1.7031, 2.314, 1.4795]
>>> fe_coef.b  # 5 Gaussian widths
[0.2717, 2.0443, 7.6007, 29.9714, 86.2265]
```

### Neutron Scattering Lengths

Neutron calculations use bound coherent scattering lengths from NCNR data, implemented in the `neutron92.hpp` header [docs/scattering.rst](docs/scattering.rst#L170-L185). For most elements, this provides a single value, with special handling for deuterium:

```python
>>> h_neut = gemmi.Element('H').neutron92
>>> h_neut.get_coefs()  # fm (10^-15 m)
[-3.739]
>>> gemmi.Element('D').neutron92.get_coefs()
[6.671]
```

## Anomalous Scattering Calculations

The Cromer-Liberman algorithm computes wavelength-dependent anomalous dispersion factors (f' and f") for elements Z=3 to Z=92 [docs/scattering.rst](docs/scattering.rst#L85-L120). This implementation, based on the Larch project and Brennan-Cowan routines, provides the same results as the `f1f2_cl` function:

```python
>>> gemmi.cromer_liberman(z=34, energy=gemmi.hc/0.71073)  # Se at 0.71073Å
(-0.09201..., 2.23336...)
```

The algorithm has known limitations: it fails for wavelengths < 0.16 Å for heavy elements and > 2.67 Å for very heavy elements. For more accurate results, Chantler's NIST data tables or XrayDB may be preferred.

## Structure Factor Computation Methods

### Direct Summation Approach

Gemmi provides `StructureFactorCalculator` classes for direct structure factor calculation through atomic summation [docs/scattering.rst](docs/scattering.rst#L190-L230). While computationally intensive for macromolecules, this method serves as a reference for validating FFT-based calculations:

```python
>>> calc_x = gemmi.StructureFactorCalculatorX(st.cell)
>>> calc_x.calculate_sf_from_model(st[0], (3,4,5))
(54.50873...+53.39498...j)
```

The calculators support addends for incorporating anomalous scattering or other corrections:

```python
>>> calc_x.addends.set(gemmi.Element('Cu'), 0.2655)  # Add f' for Cu
>>> calc_x.addends.add_cl_fprime(energy)  # Add f' for all elements
```

### FFT-Based Density Calculations

For efficient macromolecular calculations, Gemmi uses density grids transformed via FFT. The `DensityCalculator` classes manage grid setup, density calculation, and transformation [docs/scattering.rst](docs/scattering.rst#L280-L350):

```python
>>> dencalc = gemmi.DensityCalculatorX()
>>> dencalc.d_min = 2.5  # Resolution limit
>>> dencalc.rate = 1.5   # Oversampling rate
>>> dencalc.grid.setup_from(st)
>>> dencalc.put_model_density_on_grid(st[0])
>>> sf_grid = gemmi.transform_map_to_f_phi(dencalc.grid)
```

#### Accuracy Parameters

Two key parameters control calculation accuracy:

- **`cutoff`** (default: 1e-5): Determines atomic radius where density ≈ cutoff
- **`blur`** (default: 0): Artificial B-factor for improved accuracy

The optimal blur value depends on resolution, grid density, and B-factor distribution. Gemmi provides Refmac-compatible blur calculation:

```python
>>> dencalc.set_refmac_compatible_blur(st[0], allow_negative=False)
>>> dencalc.blur
31.01648695048263
```

## Advanced Applications

### Mott-Bethe Formula

Electron scattering can be computed from X-ray form factors using the Mott-Bethe formula [docs/scattering.rst](docs/scattering.rst#L420-L470). This approach uses f_x - Z as form factors and applies a d²-dependent correction factor:

```python
>>> calc_x = gemmi.StructureFactorCalculatorX(st.cell)
>>> calc_x.addends.subtract_z()  # Use f_x - Z
>>> sf = calc_x.calculate_sf_from_model(st[0], (3,4,5))
>>> calc_x.mott_bethe_factor() * sf  # Apply Mott-Bethe correction
(54.065...+52.968...j)
```

### Scaling and Bulk Solvent Correction

The `Scaling` class handles anisotropic scaling and bulk solvent correction simultaneously [docs/scattering.rst](docs/scattering.rst#L500-L680). The solvent correction follows:

**F_sol** = k_sol exp(-B_sol s²/4) **F_mask**

Combined with overall scaling:

**F_tot** = k_ov exp(-sᵀ B_ov s / 4) (**F_cryst** + **F_sol**)

Parameters are optimized using Levenberg-Marquardt least squares:

```python
>>> scaling = gemmi.Scaling(st.cell, st.find_spacegroup())
>>> scaling.use_solvent = True
>>> scaling.prepare_points(f_cryst, f_obs, f_mask)
>>> scaling.fit_isotropic_b_approximately()
>>> wssr = scaling.fit_parameters()
>>> print(f'R-factor: {scaling.calculate_r_factor():.2%}')
R-factor: 17.73%
```

## Implementation Architecture

The scattering factor system is organized across several key headers:

- **`elem.hpp`**: Element definitions and basic properties
- **`it92.hpp`**: X-ray form factor coefficients (4 Gaussian + constant)
- **`c4322.hpp`**: Electron form factor coefficients (5 Gaussian)  
- **`neutron92.hpp`**: Neutron scattering lengths
- **`fprime.hpp`**: Cromer-Liberman anomalous scattering implementation
- **`calculate.hpp`**: Calculator class templates and interfaces

The modular design allows independent use of each scattering type while maintaining consistent interfaces across C++ and Python bindings.

This comprehensive system provides crystallographers with the tools needed for accurate diffraction calculations across multiple experimental techniques, from basic form factor evaluation to complete structure factor computation with advanced corrections.