# Water properties from NPT runs against experiment:
#   julia --project=analysis analysis/water.jl SYSTEM.vsys LABEL LOG.csv TRAJ.vtrj [LABEL LOG TRAJ ...]
# Writes results/water.json and results/rdf_<label>.csv.
using Printf
using Statistics
using VerletAnalysis

const EXPERIMENT = Dict(
    "density_g_cm3" => 0.99705,          # 298.15 K, 1 bar
    "goo_peak_nm" => 0.280,             # X-ray, Skinner et al. 2013
    "goo_peak_height" => 2.57,
    "diffusion_cm2_s" => 2.299e-5,      # Mills 1973, 298 K
    "potential_per_molecule_kJ_mol" => -41.5,  # -(dH_vap - RT) at 298 K
)

function analyze(names, label, logpath, trajpath)
    log = read_csv(logpath)
    rho, rho_err = block_average(log["density_g_cm3"])
    nwat = count(==("O"), names)
    upot, upot_err = block_average(log["potential"] ./ nwat)
    frames, boxes, times = read_vtrj(trajpath)
    O = findall(==("O"), names)
    H = findall(n -> n in ("H1", "H2"), names)
    mol = cumsum(names .== "O")  # every water starts at its oxygen
    inter = (a, b) -> mol[a] == mol[b]  # intermolecular pairs only, as measured
    r, goo = rdf(frames, boxes, O, O; rmax = 1.0, nbins = 200)
    _, goh = rdf(frames, boxes, O, H; rmax = 1.0, nbins = 200, exclude = inter)
    _, ghh = rdf(frames, boxes, H, H; rmax = 1.0, nbins = 200, exclude = inter)
    k = argmax(goo)
    dt = times[2] - times[1]
    m = msd(frames, O; maxlag = min(length(frames) ÷ 2, Int(round(30 / dt))))
    lag = dt .* collect(1:length(m))
    L = mean(b[1] for b in boxes)
    d_pbc, d_inf = diffusion(lag, m; fit_from = 5.0, fit_to = min(20.0, lag[end]), L = L)
    open(joinpath("results", "rdf_$(label).csv"), "w") do f
        println(f, "r_nm,g_OO,g_OH,g_HH")
        for i in eachindex(r)
            @printf(f, "%.4f,%.5f,%.5f,%.5f\n", r[i], goo[i], goh[i], ghh[i])
        end
    end
    Dict(
        "label" => label, "frames" => length(frames), "time_ps" => times[end] - times[1], "waters" => nwat,
        "density_g_cm3" => rho, "density_err" => rho_err,
        "potential_per_molecule_kJ_mol" => upot, "potential_err" => upot_err,
        "goo_peak_nm" => r[k], "goo_peak_height" => goo[k],
        "diffusion_pbc_cm2_s" => d_pbc, "diffusion_cm2_s" => d_inf, "box_nm" => L,
    )
end

function main(args)
    names = read_atom_names(args[1])
    out = []
    for k in 2:3:length(args)
        res = analyze(names, args[k], args[k+1], args[k+2])
        push!(out, res)
        @printf("%-8s rho %.4f +- %.4f  U %.2f  gOO %.3f nm x %.2f  D %.2e (box) %.2e (infinite)\n", res["label"], res["density_g_cm3"],
                res["density_err"], res["potential_per_molecule_kJ_mol"], res["goo_peak_nm"], res["goo_peak_height"],
                res["diffusion_pbc_cm2_s"], res["diffusion_cm2_s"])
    end
    open(joinpath("results", "water.json"), "w") do f
        write(f, to_json(Dict("experiment" => EXPERIMENT, "runs" => out,
                              "notes" => "TIP3P, 298.15 K, 1 bar, PME 5e-4, cutoff 0.9 nm with dispersion correction; errors are block-average standard errors")))
    end
end

main(ARGS)
