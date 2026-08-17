# RAG Pipeline Review & Improvement Plan

## Current Implementation Analysis

### 1. **Chunking Strategy** ⚠️ Needs Improvement

**Current State:**
- Uses `RecursiveCharacterTextSplitter` with fixed parameters:
  - `chunk_size=800` characters
  - `chunk_overlap=150` characters
  - Fixed separators: `["\n\n", "\n", ". ", " ", ""]`

**Issues:**
- ❌ Fixed chunk size doesn't adapt to content type
- ❌ No semantic awareness (may split related concepts)
- ❌ Doesn't respect document structure (headings, sections)
- ❌ Overlap may not preserve context effectively
- ❌ No consideration for sentence boundaries in some cases

**Impact:** Can lead to:
- Loss of context when splitting related information
- Incomplete answers if key information spans chunks
- Poor retrieval when queries match split concepts

---

### 2. **Embedding Model** ⚠️ Can Be Improved

**Current State:**
- Model: `sentence-transformers/all-mpnet-base-v2`
- 768-dimensional embeddings
- Single embedding per chunk

**Issues:**
- ⚠️ While good, newer models offer better performance
- ❌ No query-specific embeddings
- ❌ Single vector per chunk (no multi-vector approach)

**Better Options:**
- `BAAI/bge-large-en-v1.5` (1024 dims, better accuracy)
- `intfloat/e5-large-v2` (1024 dims, excellent for retrieval)
- `sentence-transformers/all-MiniLM-L6-v2` (faster, good for large datasets)

---

### 3. **Retrieval Strategy** ⚠️ Basic Implementation

**Current State:**
- Simple similarity search with FAISS
- `k=5` for both CSV and documents
- Hybrid retrieval combining CSV (2) + Documents (2) + extras (2)
- No reranking
- No query expansion

**Issues:**
- ❌ No reranking (initial retrieval may not be optimal)
- ❌ No query expansion/rewriting
- ❌ No metadata filtering
- ❌ No score thresholding (low-quality chunks may be included)
- ❌ Fixed k value doesn't adapt to query complexity
- ❌ No hybrid search (semantic + keyword)

**Impact:**
- May retrieve irrelevant chunks
- Missing relevant chunks that don't match query embedding well
- No way to filter by document type, date, etc.

---

### 4. **Prompting Strategy** ⚠️ Basic Template

**Current State:**
```python
RAG_PROMPT_TEMPLATE = """
You are a STRICT question-answering system.
You must follow the BOT INSTRUCTIONS exactly and Answer user queries based on the provided context below.
Do not explain how you generate answers.

BOT INSTRUCTIONS:
{bot_instructions}

CONTEXT:
{retrieved_chunks}

CHAT HISTORY (Optional for better conversation):
{history}

USER QUESTION:
{query}
"""
```

**Issues:**
- ❌ No few-shot examples
- ❌ No citation format
- ❌ No structured output format
- ❌ No instruction for handling "I don't know" scenarios
- ❌ No emphasis on using only provided context
- ❌ History format is basic (could be better structured)

**Impact:**
- LLM may hallucinate or use external knowledge
- No source attribution
- Inconsistent response format
- May not handle edge cases well

---

### 5. **LLM Configuration** ✅ Good

**Current State:**
- Model: `llama-3.1-8b-instant` (Groq)
- Temperature: `0.2` (good for accuracy)

**Status:** ✅ Appropriate for RAG

---

## Improvement Recommendations

### Priority 1: High Impact, Low Effort

1. **Enhanced Prompting** 🚀
   - Add citation format
   - Add few-shot examples
   - Better "I don't know" handling
   - Structured output format

2. **Query Expansion** 🚀
   - Generate query variations
   - Use LLM to rewrite queries
   - Expand with synonyms/keywords

3. **Reranking** 🚀
   - Use cross-encoder for reranking
   - Reorder retrieved chunks by relevance

### Priority 2: High Impact, Medium Effort

4. **Better Chunking** 🚀
   - Semantic chunking
   - Document-aware chunking
   - Adaptive chunk sizes

5. **Hybrid Search** 🚀
   - Combine semantic + keyword search
   - BM25 for keyword matching
   - Weighted combination

6. **Better Embeddings** 🚀
   - Upgrade to better model
   - Consider multi-vector embeddings

### Priority 3: Medium Impact, Higher Effort

7. **Metadata Filtering**
8. **Adaptive k Selection**
9. **Score Thresholding**
10. **Query Classification**

---

## Implementation Plan

See the improved code files for detailed implementations.
