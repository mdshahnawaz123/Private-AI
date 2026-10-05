import os
import sys

# Add current dir to path to import main
sys.path.append(os.getcwd())

import main

project = "C3085 - 3EH -Expo Hills"
query = "Tower 6 Level 2 Floor GFA"

# Retrieve top 10 chunks from vectorstore
try:
    vs = main.get_vectorstore(project)
    if vs:
        # BM25 + FAISS
        bm25_idx = main._get_bm25(project, vs)
        docs_vec = vs.similarity_search_with_score(query, k=15)
        print("--- VECTOR RESULTS ---")
        for i, (d, score) in enumerate(docs_vec):
            print(f"Rank: {i+1} | Score: {score}")
            print(f"Metadata: {d.metadata}")
            print(f"Content:\n{d.page_content}\n")
            print("-" * 50)
            
        print("--- HYBRID RESULTS (AS RUN BY RETRIEVE_CONTEXT) ---")
        # Reproduce retrieve_context without permissions
        v_docs = [d[0] for d in docs_vec]
        b_docs = []
        if bm25_idx:
            try:
                # bm25_idx.search returns [(doc_idx, score)]
                # we need to map to actual docs
                b_res = bm25_idx.search(query, k=15)
                ds = getattr(vs, "docstore", None)
                docs = list(ds._dict.values()) if ds is not None and hasattr(ds, "_dict") else []
                b_docs = [docs[idx] for idx, _ in b_res]
            except Exception as e:
                print("BM25 error:", e)
        
        merged = main._rrf_merge(v_docs, b_docs, limit=5)
        for i, d in enumerate(merged):
            print(f"Hybrid Rank: {i+1}")
            print(f"Metadata: {d.metadata}")
            print(f"Content:\n{d.page_content}\n")
            print("=" * 50)
            
    else:
        print("Vectorstore not found.")
except Exception as e:
    import traceback
    traceback.print_exc()

