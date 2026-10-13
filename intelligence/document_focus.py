"""Resolve explicitly named sources only from the permission-filtered list."""
import re

def named_document(query,documents):
    matches=[d for d in documents if d.get('filename') and re.search(
        r'(?<![\w.-])'+re.escape(d['filename'])+r'(?![\w.-])',query,re.I)]
    if len(matches) == 1:
        return matches[0]
    if matches:
        return None

    # A user may identify a document by its printed project/document code
    # rather than repeat a long upload filename (for example, "C3045 project
    # data sheet"). Focus only when one code and one accessible filename
    # resolve uniquely. Multiple codes or multiple documents stay ambiguous.
    codes = set(re.findall(r'(?<![A-Z0-9])[A-Z]{1,5}\d{3,8}(?![A-Z0-9])', query, re.I))
    if len(codes) != 1:
        return None
    code = next(iter(codes))
    code_matches = [d for d in documents if d.get('filename') and re.search(
        r'(?<![A-Z0-9])' + re.escape(code) + r'(?![A-Z0-9])', d['filename'], re.I)]
    if len(code_matches) == 1:
        return code_matches[0]
    if not code_matches:
        return None

    # A project code can occur on several deliverables. Use explicit document
    # words such as "data sheet" to resolve among those files, and preserve
    # ambiguity when the question supplies no distinguishing description.
    ignored = {"what", "which", "where", "when", "who", "how", "is", "are", "was", "were",
               "the", "a", "an", "for", "in", "on", "of", "to", "from", "listed", "show",
               "shows", "give", "tell", "me", "please", "project", "document", "file"}
    query_words = set(re.findall(r"[a-z0-9]+", query.lower())) - ignored - {code.lower()}
    ranked = []
    for document in code_matches:
        filename_words = set(re.findall(r"[a-z0-9]+", document["filename"].lower())) - {code.lower()}
        ranked.append((len(query_words & filename_words), document))
    best_score = max(score for score, _document in ranked)
    best = [document for score, document in ranked if score == best_score]
    return best[0] if best_score and len(best) == 1 else None
