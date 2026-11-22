# Backbone RMSD of a protein along a trajectory, against its starting (NMR) structure:
#   julia --project=analysis analysis/protein.jl SYSTEM.vsys TRAJ.vtrj LABEL
# Writes results/rmsd_<label>.csv and prints the mean over the second half.
using Printf
using Statistics
using VerletAnalysis

function main(args)
    vsys, traj, label = args
    names = read_atom_names(vsys)
    # the starting positions are the coordinates in the .vsys file
    lines = readlines(vsys)
    i0 = findfirst(l -> startswith(l, "atoms "), lines)
    n = length(names)
    ref = Matrix{Float64}(undef, 3, n)
    resn = String[]
    for k in 1:n
        f = split(lines[i0+k])
        ref[:, k] = parse.(Float64, f[10:12])
        push!(resn, f[2])
    end
    backbone = [k for k in 1:n if resn[k] ∉ ("HOH", "WAT", "NA", "CL") && names[k] in ("N", "CA", "C")]
    frames, _, times = read_vtrj(traj)
    r = [rmsd(x, ref, backbone) for x in frames]
    open(joinpath("results", "rmsd_$(label).csv"), "w") do f
        println(f, "time_ps,backbone_rmsd_nm")
        for (t, v) in zip(times, r)
            @printf(f, "%.2f,%.5f\n", t, v)
        end
    end
    half = r[length(r)÷2+1:end]
    @printf("%s: %d backbone atoms, %d frames over %.0f ps, RMSD second half %.3f +- %.3f nm (max %.3f)\n", label, length(backbone),
            length(frames), times[end] - times[1], mean(half), std(half), maximum(r))
end

main(ARGS)
