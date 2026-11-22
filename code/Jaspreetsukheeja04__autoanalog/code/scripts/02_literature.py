import requests
import pandas as pd
import json
import time
import os

disease  = snakemake.config["disease"]
receptor = snakemake.config["receptor"]
out_path = snakemake.output[0]
os.makedirs(os.path.dirname(out_path), exist_ok=True)

print("=" * 45)
print("STEP 2: LITERATURE MINING")
print("=" * 45)

queries = [
    f"{receptor} {disease}",
    f"{receptor} inhibitor drug discovery",
    f"{receptor} microglial signalling pain",
    f"{receptor} antagonist analogue",
    f"{disease} chronic pain treatment",
]

# ── PUBMED ────────────────────────────────
def search_pubmed(query, max_results=20):
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    try:
        r = requests.get(f"{base}/esearch.fcgi",
            params={"db":"pubmed","term":query,
                    "retmax":max_results,
                    "retmode":"json"},
            timeout=30)
        ids = r.json()["esearchresult"]["idlist"]
        papers = []
        for pmid in ids:
            try:
                r2 = requests.get(
                    f"{base}/esummary.fcgi",
                    params={"db":"pubmed",
                            "id":pmid,
                            "retmode":"json"},
                    timeout=30)
                data = r2.json().get(
                    "result",{}).get(pmid,{})
                papers.append({
                    "source":   "PubMed",
                    "pmid":     pmid,
                    "title":    data.get("title",""),
                    "year":     data.get(
                        "pubdate","")[:4],
                    "journal":  data.get("source",""),
                    "authors":  data.get(
                        "authors",[{}])[0].get(
                        "name","") if data.get(
                        "authors") else "",
                    "citations":0,
                    "query":    query,
                })
                time.sleep(0.3)
            except Exception:
                continue
        return papers
    except Exception as e:
        print(f"  PubMed error: {e}")
        return []

# ── SEMANTIC SCHOLAR ──────────────────────
def search_semantic(query, max_results=15):
    try:
        url = ("https://api.semanticscholar.org"
               "/graph/v1/paper/search")
        r = requests.get(url,
            params={"query":query,
                    "limit":max_results,
                    "fields":"title,year,authors,"
                    "citationCount,venue"},
            timeout=30)
        papers = []
        if r.status_code == 200:
            for p in r.json().get("data",[]):
                papers.append({
                    "source":   "SemanticScholar",
                    "pmid":     "",
                    "title":    p.get("title",""),
                    "year":     p.get("year",""),
                    "journal":  p.get("venue",""),
                    "authors":  p.get(
                        "authors",[{}])[0].get(
                        "name","") if p.get(
                        "authors") else "",
                    "citations":p.get(
                        "citationCount",0),
                    "query":    query,
                })
        return papers
    except Exception as e:
        print(f"  SemanticScholar error: {e}")
        return []

# ── EUROPE PMC ────────────────────────────
def search_europepmc(query, max_results=15):
    try:
        url = ("https://www.ebi.ac.uk/europepmc"
               "/webservices/rest/search")
        r = requests.get(url,
            params={"query":query,
                    "format":"json",
                    "pageSize":max_results,
                    "resultType":"core"},
            timeout=30)
        papers = []
        if r.status_code == 200:
            for p in r.json().get(
                    "resultList",{}).get(
                    "result",[]):
                papers.append({
                    "source":   "EuropePMC",
                    "pmid":     p.get("pmid",""),
                    "title":    p.get("title",""),
                    "year":     p.get("pubYear",""),
                    "journal":  p.get(
                        "journalTitle",""),
                    "authors":  p.get(
                        "authorString",""),
                    "citations":p.get(
                        "citedByCount",0),
                    "query":    query,
                })
        return papers
    except Exception as e:
        print(f"  EuropePMC error: {e}")
        return []

# ── OPENALEX ──────────────────────────────
def search_openalex(query, max_results=15):
    try:
        url = "https://api.openalex.org/works"
        r = requests.get(url,
            params={"search":query,
                    "per-page":max_results,
                    "select":"title,"
                    "publication_year,"
                    "cited_by_count,"
                    "primary_location,"
                    "authorships"},
            timeout=30)
        papers = []
        if r.status_code == 200:
            for p in r.json().get("results",[]):
                loc = p.get(
                    "primary_location",{}) or {}
                source = loc.get("source",{}) or {}
                journal = source.get(
                    "display_name","")
                authors = p.get(
                    "authorships",[])
                author = ""
                if authors:
                    a = authors[0].get(
                        "author",{}) or {}
                    author = a.get(
                        "display_name","")
                papers.append({
                    "source":   "OpenAlex",
                    "pmid":     "",
                    "title":    p.get("title",""),
                    "year":     p.get(
                        "publication_year",""),
                    "journal":  journal,
                    "authors":  author,
                    "citations":p.get(
                        "cited_by_count",0),
                    "query":    query,
                })
        return papers
    except Exception as e:
        print(f"  OpenAlex error: {e}")
        return []

# ── RUN ALL SEARCHES ──────────────────────
all_papers = []
for query in queries:
    print(f"\nSearching: {query}")
    pm = search_pubmed(query, 20)
    ss = search_semantic(query, 15)
    ep = search_europepmc(query, 15)
    oa = search_openalex(query, 15)
    total = len(pm)+len(ss)+len(ep)+len(oa)
    all_papers.extend(pm+ss+ep+oa)
    print(f"  PubMed={len(pm)} "
          f"Semantic={len(ss)} "
          f"EuropePMC={len(ep)} "
          f"OpenAlex={len(oa)} "
          f"Total={total}")
    time.sleep(1)

# ── DEDUPLICATE ───────────────────────────
df = pd.DataFrame(all_papers)
df = df.dropna(subset=["title"])
df = df[df["title"].str.strip() != ""]
df["title_lower"] = df["title"].str.lower()\
    .str.strip()
df = df.sort_values(
    "citations", ascending=False)
df = df.drop_duplicates(
    subset=["title_lower"])
df = df.drop(columns=["title_lower"])
df = df.reset_index(drop=True)

df.to_csv(out_path, index=False)

print("\n" + "=" * 45)
print("LITERATURE SUMMARY")
print("=" * 45)
print(f"Total unique papers: {len(df)}")
print(f"Top 5 by citations:")
for _, r in df.head(5).iterrows():
    print(f"  {r['citations']:4d} | "
          f"{str(r['title'])[:55]}")
print("\nStep 2 complete")
