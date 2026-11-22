/* The C interface of the CUDA plugin (verlet_cuda.dll / libverlet_cuda.so).
 * It computes the nonbonded real-space terms, the exclusion corrections and
 * reciprocal-space PME on the GPU in single precision with double-precision
 * energy sums; the engine adds the bonded terms (Fortran, on the CPU, while
 * the GPU works), the self energy and the dispersion correction. */
#ifndef VERLET_CUDA_PLUGIN_H
#define VERLET_CUDA_PLUGIN_H

#ifdef __cplusplus
extern "C" {
#endif

#if defined(_WIN32)
#define VC_EXPORT __declspec(dllexport)
#else
#define VC_EXPORT __attribute__((visibility("default")))
#endif

/* returns 0 on success, otherwise writes a message into err */
VC_EXPORT int vc_create(void** ctx, int n, const double* charge, const double* sigma, const double* epsilon, int n_excl,
                        const int* excl_pairs, double cutoff, double skin, char* err, int errlen);
VC_EXPORT int vc_set_pme(void* ctx, double alpha, int nx, int ny, int nz, int order);
/* new charges (e.g. an alchemical solute scaled by lambda); used from the next vc_begin */
VC_EXPORT int vc_set_charges(void* ctx, const double* charge);
/* starts the computation (asynchronous); rebuild: rebuild the neighbor list */
VC_EXPORT int vc_begin(void* ctx, const double* pos, const double* box, int rebuild, int want_energy);
/* waits; adds the forces (kJ/mol/nm) to forces[3n]; energy[4] = LJ, Coulomb real, Coulomb reciprocal, exclusion correction */
VC_EXPORT int vc_end(void* ctx, double* forces, double* energy);
VC_EXPORT const char* vc_device(void* ctx);
VC_EXPORT void vc_destroy(void* ctx);

#ifdef __cplusplus
}
#endif
#endif
