

This page provides an in-depth examination of PLUMED2's reweighting architecture for extracting unbiased free energy surfaces from biased molecular dynamics simulations. For advanced developers, understanding the implementation patterns and integration mechanisms enables proper extension and optimization of these critical analysis tools.

Reweighting in PLUMED2 operates on a fundamental statistical mechanics principle: when a bias potential V(x,t) is applied during simulation, the resulting trajectory samples a modified probability distribution. To recover the unbiased ensemble properties, we must apply appropriate statistical weights that account for the bias effect. The framework provides multiple specialized methods tailored to different biasing scenarios and ensemble transformations.

Sources: [src/bias/ReweightBase.h](src/bias/ReweightBase.h), [src/bias/ReweightBase.cpp](src/bias/ReweightBase.cpp)

## Core Architecture: ReweightBase Framework

The reweighting architecture follows an object-oriented design pattern centered around the `ReweightBase` abstract class, which serves as the foundation for all reweighting implementations. This class inherits from both `ActionWithValue` and `ActionWithArguments`, allowing it to function within PLUMED's action execution model while accepting multiple input arguments for bias values.

```cpp
class ReweightBase :
  public ActionWithValue,
  public ActionWithArguments {
protected:
  double simtemp;  // Temperature at simulation conditions
public:
  virtual bool buildsWeightStore() const { return false; }
  virtual void calculateWeights( const unsigned& nframes ) {}
  virtual double getLogWeight() = 0;  // Pure virtual method
  virtual double getWeight( const unsigned& iweight ) const {
    plumed_error();
  }
  virtual void clearData() {}
};
```

The framework enforces temperature specification either through the MD engine or via the `TEMP` keyword, with validation preventing execution without thermal information. Each reweighting implementation overrides the `getLogWeight()` method to compute the logarithm of the appropriate weight factor, which is then exposed as a scalar value for use in subsequent analysis actions like `HISTOGRAM` or `AVERAGE`.

Sources: [src/bias/ReweightBase.h](src/bias/ReweightBase.h#L28-L52), [src/bias/ReweightBase.cpp](src/bias/ReweightBase.cpp#L40-L56)

## Weighted Histogram Analysis Method (WHAM)

WHAM implements the Weighted Histogram Analysis Method for combining multiple biased trajectories, particularly useful in parallel tempering or umbrella sampling scenarios. The algorithm operates by iteratively solving the self-consistent equations that maximize the likelihood of observing the combined dataset across all biased simulations.

```cpp
// Iterative WHAM convergence loop
for(unsigned iter=0; iter<maxiter; ++iter) {
  // Store previous normalization factors
  for(unsigned j=0; j<Z.size(); ++j) {
    oldZ[j]=Z[j];
  }
  // Recompute weights for each frame
  for(unsigned j=0; j<final_weights.size(); ++j) {
    double ew=0;
    for(unsigned k=0; k<Z.size(); ++k) {
      ew += expv[j*Z.size()+k]  / Z[k];
    }
    final_weights[j] = 1.0 / ew;
    norm += final_weights[j];
  }
  // Normalize weights
  for(unsigned j=0; j<final_weights.size(); ++j) {
    final_weights[j] /= norm;
  }
  // Update partition function estimates
  for(unsigned j=0; j<final_weights.size(); ++j) {
    for(unsigned k=0; k<Z.size(); ++k) {
      Z[k] += final_weights[j]*expv[j*Z.size()+k];
    }
  }
}
```

The mathematical foundation derives from maximizing the probability:

$$P(\underline{T}) \propto \prod_{j=1}^M \prod_{k=1}^N (c_k w_{kj} p_j)^{t_{kj}}$$

where $w_{kj} = e^{+\beta V_k(x_j)}$ represents the bias factor for configuration $j$ from trajectory $k$. The implementation uses a binless formulation that avoids histogram binning by working directly with individual frames, requiring only that all bias values be properly collected across replicas.

Sources: [src/wham/Wham.cpp](src/wham/Wham.cpp#L59-L233)

## Static Bias Reweighting: REWEIGHT_BIAS

For simulations with time-independent or slowly-varying bias potentials, `REWEIGHT_BIAS` provides straightforward weight calculation based on the Boltzmann factor of the bias energy. This applies to scenarios like harmonic restraints, umbrella potentials, or static energy landscape biases.

```cpp
double ReweightBias::getLogWeight() {
  double bias=0.0;
  for(unsigned i=0; i<getNumberOfArguments(); ++i) {
    bias+=getArgument(i);
  }
  return bias / simtemp;
}
```

The implementation computes $\ln(w) = \frac{V(x,t')}{k_B T}$, where $V(x,t')$ represents the cumulative bias from all specified bias actions. The resulting weights can be used to reconstruct unbiased probability distributions:

$$\langle P(s',t) \rangle = \frac{\sum_{t'}^t \delta(s(x) - s') \exp\left(+\frac{V(x,t')}{k_B T}\right)}{\sum_{t'}^t \exp\left(+\frac{V(x,t')}{k_B T}\right)}$$

This method assumes the bias varies slowly relative to the sampling timescale, making it suitable for harmonic restraints but inappropriate for metadynamics where the bias evolves continuously.

Sources: [src/bias/ReweightBias.cpp](src/bias/ReweightBias.cpp#L68-L99)

## Metadynamics Reweighting: REWEIGHT_METAD

Metadynamics presents unique reweighting challenges because the bias potential $V(s,t)$ evolves continuously as Gaussian kernels are added throughout the simulation. The `REWEIGHT_METAD` action implements the reweighting algorithm specifically designed for time-dependent biases, requiring the metadynamics bias to be computed on a grid with periodic calculation of the $c(t)$ normalization factor.

```cpp
double ReweightMetad::getLogWeight() {
  double bias=0.0;
  for(unsigned i=0; i<getNumberOfArguments(); ++i) {
    bias+=getArgument(i);
  }
  return bias / simtemp;
}
```

While the mathematical form appears identical to static bias reweighting, the critical distinction lies in how the bias values are obtained. In metadynamics, the bias argument passed to `REWEIGHT_METAD` must be the `.rbias` output from the metadynamics action, which represents the reweighting bias rather than the instantaneous bias potential. This reweighting bias accounts for the time-averaged nature of the metadynamics process and enables accurate reconstruction of the free energy surface.

> [!TIP]
> The `.rbias` value differs from `.bias` in metadynamics outputs: `.bias` represents the instantaneous potential applied at the current time, while `.rbias` includes the cumulative effect needed for proper reweighting. Always use `.rbias` with REWEIGHT_METAD to ensure correct statistical weights.

Sources: [src/bias/ReweightMetad.cpp](src/bias/ReweightMetad.cpp#L68-L99)

## Temperature and Pressure Reweighting: REWEIGHT_TEMP_PRESS

The `REWEIGHT_TEMP_PRESS` action provides sophisticated reweighting capabilities for transforming ensemble averages across different thermodynamic conditions. This method is essential for extracting properties at temperatures or pressures different from those used in the original simulation, particularly when combined with enhanced sampling techniques.

The implementation handles four distinct transformation scenarios:

| Scenario | Input Parameters | Weight Formula | Physical Meaning |
|----------|-----------------|----------------|------------------|
| **Constant Volume Temperature Change** | `REWEIGHT_TEMP`, `ENERGY` | $(\beta - \beta')E(\mathbf{R})$ | NVT → NVT' ensemble transformation |
| **Constant Pressure Temperature Change** | `REWEIGHT_TEMP`, `PRESSURE`, `ENERGY`, `VOLUME` | $(\beta - \beta')(E + P\mathcal{V})$ | NPT → NPT' ensemble transformation |
| **Constant Temperature Pressure Change** | `REWEIGHT_PRESSURE`, `PRESSURE`, `VOLUME` | $\beta(P - P')\mathcal{V}$ | NPT → NP'T ensemble transformation |
| **Full Temperature/Pressure Change** | `REWEIGHT_TEMP`, `REWEIGHT_PRESSURE`, `PRESSURE`, `ENERGY`, `VOLUME` | $(\beta - \beta')E + (\beta P - \beta'P')\mathcal{V}$ | NPT → NP'T' ensemble transformation |

```cpp
double ReweightTemperaturePressure::getLogWeight() {
  double energy=0.0, volume=0.0;
  for(unsigned i=0; i<myenergy.size(); ++i) {
    energy+=getArgument(i);
  }
  for(unsigned i=0; i<myvol.size(); ++i) {
    volume+=getArgument(myenergy.size()+i);
  }
  
  if (rtemp_>=0 && press_<0 && rpress_<0) {
    return ((1.0/simtemp)- (1.0/rtemp_))*energy;
  }
  else if (rtemp_>=0 && press_>=0 && rpress_<0) {
    return ((1.0/simtemp)- (1.0/rtemp_))*energy + ((1.0/simtemp) - (1.0/rtemp_))*press_*volume;
  }
  // ... additional cases
}
```

When combining with bias reweighting, the complete weight becomes the product of individual weight factors:

$$\langle O(\mathbf{R},\mathcal{V})\rangle_{\xi'} = \frac{\langle O(\mathbf{R},\mathcal{V}) w(\mathbf{R},\mathcal{V}) e^{\beta V(\mathbf{s})}\rangle_{\xi,V}}{\langle w(\mathbf{R},\mathcal{V}) e^{\beta V(\mathbf{s})}\rangle_{\xi,V}}$$

> [!TIP]
> Always shift energy and volume values before reweighting to avoid numerical overflow in exponential calculations. Use COMBINE or CUSTOM actions to center values around zero while preserving physical differences.

Sources: [src/bias/ReweightTemperaturePressure.cpp](src/bias/ReweightTemperaturePressure.cpp#L187-L298)

## Integration with Analysis Actions

Reweighting weights integrate seamlessly with PLUMED's analysis framework through the `LOGWEIGHTS` parameter common to histogram and averaging actions. This parameter accepts one or more weight labels, combining them multiplicatively to produce the final statistical weight for each frame.

```plumed
# Multi-dimensional histogram with reweighting
hB: HISTOGRAM ...
  ARG=a
  GRID_MIN=0.0
  GRID_MAX=pi
  GRID_BIN=100
  BANDWIDTH=0.1
  LOGWEIGHTS=bias_weights,temp_press_weights
...

# Free energy surface reconstruction
fes: CONVERT_TO_FES ARG=hB TEMP=300
DUMPGRID ARG=fes STRIDE=1 FILE=fes.dat
```

The histogram accumulation process applies weights through kernel density estimation, where each frame contributes to the histogram according to:

$$h(s') = \sum_{t'} w(t') K(s(x(t')) - s')$$

where $K$ is the kernel function and $w(t')$ represents the combined reweighting weight. The `CONVERT_TO_FES` action then transforms the histogram to a free energy surface using $F(s) = -k_B T \ln P(s)$.

Sources: [regtest/wham/rt-wham/plumed.dat](regtest/wham/rt-wham/plumed.dat#L17-L25)

## Implementation Patterns for Custom Reweighting

Developers extending the reweighting framework should follow established patterns for consistency with existing actions:

1. **Inherit from ReweightBase**: Ensure proper integration with the action framework
2. **Override getLogWeight()**: Return logarithm of weight rather than weight itself for numerical stability
3. **Register keywords properly**: Use `addInputKeyword()` with appropriate data types and constraints
4. **Provide documentation**: Include mathematical derivations and usage examples in PLUMEDDOC comments
5. **Handle temperature validation**: Ensure proper error messages when temperature is unspecified

The architecture supports both online reweighting (during simulation) and offline analysis (post-processing trajectories through READ actions), providing flexibility for different workflow requirements.

Sources: [src/bias/ReweightBase.h](src/bias/ReweightBase.h#L28-L59)

## Next Steps

For practical implementation guidance, consult [Metadynamics Variants](14-metadynamics-variants) to understand how different metadynamics approaches affect reweighting strategies. The [Umbrella Sampling and WHAM](5-umbrella-sampling-and-wham) tutorial provides hands-on examples combining umbrella potentials with WHAM analysis. Advanced developers should review the [Bias Method Implementation](25-creating-new-bias-methods) guide for extending reweighting capabilities with custom bias forms.