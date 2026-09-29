import os
from langchain_community.document_loaders import UnstructuredExcelLoader

path = "C:\\3EH\\ExpoDesignAI\\data\\docs\\HighRise_Structural_Design_Checklist_DBC_1.xlsx"
print("Loading...")
try:
    loader = UnstructuredExcelLoader(path)
    docs = loader.load()
    print("Success. Loaded", len(docs), "documents.")
except Exception as e:
    print("Error:", e)
