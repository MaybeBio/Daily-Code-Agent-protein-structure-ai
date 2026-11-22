# Hydration free energy from the alchemical windows written by `verlet fep`:
#   julia --project=analysis analysis/fep.jl run/fep 15 [T]
# MBAR over all states, and TI over the two stages (charges, then Lennard-Jones).
# Writes results/fep_water.json.
using Printf
using Statistics
using VerletAnalysis

const KB = 0.00831446261815324

function main(args)
    dir, K = args[1], parse(Int, args[2])
    T = length(args) >= 3 ? parse(Float64, args[3]) : 298.15
    beta = 1 / (KB * T)
    data = [read_csv(joinpath(dir, "state$k.csv")) for k in 0:K-1]
    N = [length(d["time_ps"]) for d in data]
    # reduced energies of every sample in every state (the PV term is the same for all states of a sample)
    u = vcat([hcat([beta .* d["u$j"] for j in 0:K-1]...) for d in data]...)
    f, ferr = mbar(u, N)
    dG_decouple = f[end] / beta
    dG_err = ferr[end] / beta
    # TI: <dU/dlambda_q> along the charge stage (lambda_lj = 1), <dU/dlambda_lj> along the LJ stage
    function lambdas(k)  # from the header: "# state k of K: lambda_q X lambda_lj Y; ..."
        m = match(r"lambda_q ([0-9.]+) lambda_lj ([0-9.]+)", readline(joinpath(dir, "state$k.csv")))
        (parse(Float64, m[1]), parse(Float64, m[2]))
    end
    lam = [lambdas(k) for k in 0:K-1]
    q_stage = [k for k in 1:K if lam[k][2] == 1.0]
    lj_stage = [k for k in 1:K if lam[k][1] == 0.0]
    stats(key, ks) = ([block_average(data[k][key])[1] for k in ks], [block_average(data[k][key])[2] for k in ks])
    mq, eq = stats("du_dq", q_stage)
    mlj, elj = stats("du_dlj", lj_stage)
    order_q = sortperm([lam[k][1] for k in q_stage])
    order_lj = sortperm([lam[k][2] for k in lj_stage])
    ti_q, ti_q_err = ti([lam[k][1] for k in q_stage][order_q], mq[order_q], eq[order_q])
    ti_lj, ti_lj_err = ti([lam[k][2] for k in lj_stage][order_lj], mlj[order_lj], elj[order_lj])
    # integral from 0 to 1 of dU/dlambda is G(1) - G(0) = -(G(decoupled) - G(coupled)) for each stage
    ti_hyd = ti_q + ti_lj
    ti_err = sqrt(ti_q_err^2 + ti_lj_err^2)
    @printf("MBAR: dG_hyd = %.2f +- %.2f kJ/mol   TI: %.2f +- %.2f kJ/mol (charges %.2f, LJ %.2f)\n", -dG_decouple, dG_err, ti_hyd, ti_err,
            ti_q, ti_lj)
    open(joinpath("results", "fep_water.json"), "w") do io
        write(io, to_json(Dict(
            "states" => [[l[1], l[2]] for l in lam], "samples_per_state" => N,
            "mbar_free_energy_kT" => f, "mbar_err_kT" => ferr,
            "dG_hydration_mbar_kJ_mol" => -dG_decouple, "dG_hydration_mbar_err" => dG_err,
            "dG_hydration_ti_kJ_mol" => ti_hyd, "dG_hydration_ti_err" => ti_err,
            "ti_charge_kJ_mol" => ti_q, "ti_lj_kJ_mol" => ti_lj,
            "experiment_kJ_mol" => -26.5,
            "notes" => "TIP3P water in 499 TIP3P waters, 298.15 K, 1 bar; experiment: -6.32 kcal/mol (Ben-Naim and Marcus 1984)",
        )))
    end
end

main(ARGS)
