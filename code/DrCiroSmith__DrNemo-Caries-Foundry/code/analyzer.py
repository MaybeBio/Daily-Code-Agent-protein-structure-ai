#!/usr/bin/env python3
import os
import csv
import sys
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

try:
    import ollama
    HAS_OLLAMA = True
except ImportError:
    HAS_OLLAMA = False
    print("⚠️ Ollama package not found. Run: pip install ollama")

try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

load_dotenv()

BASE_DIR = Path.home() / "drnemo_research"
RESULTS_DIR = BASE_DIR / "results"
SCORES_FILE = RESULTS_DIR / "master_scores.csv"
ANALYSIS_DIR = RESULTS_DIR / "analysis"

# We use an Ollama model for fast, local inference
MODEL_ID = os.environ.get("OLLAMA_MODEL", "llama3")

def init_env():
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

def generate_clinical_synthesis(job_id, plddt, iptm, composite):
    content = None
    engine = None
    prompt_text = f"""You are a dual-certified Dentist and Data Scientist conducting research on oral pathogens.
Analyze the following computational structural prediction for job: {job_id}.
- Local Distance Difference Test (pLDDT) Score: {plddt} (out of 100)
- Interface pTM (iPTM) Score: {iptm} (out of 1.0)
- Composite Score (pLDDT/100 * iPTM): {composite:.3f}

Context rules:
- pLDDT > 70 indicates good confidence in the structural fold.
- iPTM > 0.8 is an excellent indication of an interaction interface.
- Composite Score > 0.72 is a High-Confidence Discovery (BLUE).
- Composite Score > 0.42 is a Promising Interaction (GREEN).

Write a short, highly professional clinical analysis (1-2 paragraphs) evaluating whether this predicted interaction is structurally stable and has high enough affinity to warrant further *in-vitro* wet-lab validation for targeted antimicrobial therapies against oral pathogens.
"""

    messages = [
        {"role": "user", "content": prompt_text}
    ]
    
    github_token = os.environ.get("GITHUB_TOKEN")
    used_model = MODEL_ID
    
    # 1. Try GitHub Models (Copilot)
    if github_token and HAS_OPENAI:
        print(f"💭 {job_id}: Thinking with GitHub Models API ({MODEL_ID})...")
        try:
            client = OpenAI(base_url="https://models.inference.ai.azure.com", api_key=github_token)
            response = client.chat.completions.create(model=os.environ.get("GITHUB_MODEL", "gpt-4o"), messages=messages)
            content = response.choices[0].message.content
            engine = f"GitHub ({os.environ.get('GITHUB_MODEL', 'gpt-4o')})"
        except Exception as e:
            print(f"⚠️ GitHub Inference failed ({e}). Trying NVIDIA NIM...")

    # 2. Try NVIDIA NIM (Scale Backup with 3-key rotation)
    if not content:
        raw_keys = os.environ.get("NGC_API_KEYS", "")
        nv_keys = [k.strip() for k in raw_keys.split(",") if k.strip()]
        for key in nv_keys:
            try:
                nv_client = OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=key)
                response = nv_client.chat.completions.create(
                    model="meta/llama-3.1-405b-instruct",
                    messages=messages,
                    temperature=0.2,
                    max_tokens=600
                )
                print(f"💭 {job_id}: Thinking with NVIDIA NIM (Llama 405B)...")
                content = response.choices[0].message.content
                engine = "NVIDIA NIM (Llama 405B)"
                break
            except Exception as e:
                print(f"⚠️ NVIDIA NIM key failed ({e}). Trying next...")

    # 3. Local Fallback (Ollama)
    if not content and HAS_OLLAMA:
        print(f"💭 {job_id}: Thinking with Local Ollama ({MODEL_ID})...")
        try:
            response = ollama.chat(model=MODEL_ID, messages=messages)
            content = response['message']['content']
            engine = f"Local Ollama ({MODEL_ID})"
        except Exception as e:
            print(f"❌ Error communicating with Ollama: {e}")
            return "Analysis failed due to Local LLM error."

    if not content:
        return "No LLM interface available. Define GITHUB_TOKEN, NGC_API_KEYS, or install ollama."
    
    # --- COMPLIANCE LOGGING ---
    try:
        from compliance_logger import log_medgemma_inference
        # Re-using the same function but passing the Ollama model ID
        log_medgemma_inference(job_id, f"ollama/{MODEL_ID}", prompt_text, {"pLDDT": plddt, "iPTM": iptm, "Composite_Score": composite})
    except ImportError:
        pass
    # --------------------------
    
    return content

def analyze_unprocessed_results():
    if not SCORES_FILE.exists():
        print("No master_scores.csv found yet. Skipping analysis.")
        return

    # To avoid repeating work, we check which jobs already have an analysis file
    analyzed_jobs = set()
    for file in ANALYSIS_DIR.glob("*.md"):
        analyzed_jobs.add(file.stem)

    jobs_to_process = []
    
    with open(SCORES_FILE, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['Status'] == "SUCCESS" and row['Job_ID'] not in analyzed_jobs:
                jobs_to_process.append(row)

    if not jobs_to_process:
        print("🧠 Clinical Analysis: All completed jobs have already been analyzed.")
        return

    if not HAS_OLLAMA and not (HAS_OPENAI and os.environ.get("GITHUB_TOKEN")):
        print("🧠 Clinical Analysis: Skipped. No LLM available (install ollama or set GITHUB_TOKEN).")
        return

    print(f"🧠 Loading Local Reasoning Model ({MODEL_ID} via Ollama)...")

    for job in jobs_to_process:
        job_id = job['Job_ID']
        print(f"🔬 Synthesizing clinical report for {job_id}...")
        
        plddt = float(job.get('pLDDT', 0))
        iptm = float(job.get('iPTM', 0))
        try:
            composite = float(job.get('Composite_Score'))
        except (TypeError, ValueError):
            composite = (plddt / 100.0) * iptm
            
        analysis_text = generate_clinical_synthesis(
            job_id=job_id, 
            plddt=plddt, 
            iptm=iptm,
            composite=composite
        )
        
        report_path = ANALYSIS_DIR / f"{job_id}.md"
        with open(report_path, 'w', encoding="utf-8") as f:
            f.write(f"# Clinical Synthesis: {job_id}\n\n")
            f.write(f"**pLDDT Score:** {plddt}\n")
            f.write(f"**iPTM Score:** {iptm}\n")
            f.write(f"**Composite Score:** {composite:.3f}\n")
            f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write("## Clinical Analysis\n")
            f.write(analysis_text)
            
        print(f"✅ Saved analysis report: {report_path.name}")

if __name__ == "__main__":
    init_env()
    analyze_unprocessed_results()
