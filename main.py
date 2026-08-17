# app/main.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional
from pathlib import Path
import uvicorn
import json

from fastapi.templating import Jinja2Templates
from fastapi import Request
from fastapi import UploadFile, File, Form
from typing import List
import os
import time
import tempfile

import app.logic.langchain_helper as rag
from langchain_core.documents import Document

from app.logic.langchain_helper import build_documents_from_uploads, index_documents_for_bot, load_retriever_for_bot

from fastapi.staticfiles import StaticFiles

app = FastAPI(title="No-Code Chatbot API")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

templates = Jinja2Templates(directory="app/templates")

# Allow origins you plan to embed widget from (adjust before prod)
origins = [
    "*",  # for development. Replace with your domains for production.
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatQuery(BaseModel):
    query: str
    user_id: str
    bot_id: str

# Request models
class SignupRequest(BaseModel):
    email: str
    password: str

class CreateBotRequest(BaseModel):
    user_id: str
    name: str
    instructions: Optional[str] = ""

class RenameBotRequest(BaseModel):
    name: str


@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "body_class": "no-sidebar"}
    )


@app.post("/chat")
async def chat_endpoint(payload: ChatQuery):
    if not payload.query or not payload.query.strip():
        raise HTTPException(status_code=400, detail="Please enter a valid query.")

    try:
        rag.init_llm_embeddings_and_retriever()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Initialization error: {e}")

    doc_retriever = None
    csv_retriever = None

    if payload.bot_id:
        try:
            doc_retriever = rag.load_retriever_for_bot(payload.bot_id, k=5)
        except Exception:
            doc_retriever = None

        csv_retriever = rag.load_csv_retriever_for_bot(payload.bot_id, k=5)
    else:
        raise HTTPException(status_code=400, detail="bot_id is required")
    
    if not doc_retriever and not csv_retriever:
        raise HTTPException(
            status_code=400,
            detail="This bot has no trained knowledge yet."
        )

    # 🔥 NEW: detect widget user
    is_widget_user = payload.user_id.startswith("widget_")

    # 🔥 NEW: load history ONLY for dashboard users
    history = []
    if not is_widget_user:
        history = rag.get_conversation_history(
            payload.user_id,
            payload.bot_id
        )

    # ================= CONTEXTUALIZE QUERY =================
    # Rewrite the query based on history to resolve pronouns/missing entities
    standalone_query = rag.contextualize_query(payload.query, history, rag.LLM)
    
    # Log the queries for debugging/evaluation
    print(f"\n[RAG Pipeline] Original Query: {payload.query}")
    print(f"[RAG Pipeline] Standalone Query: {standalone_query}\n")
    # ==========================================================

    # ================= HYBRID RETRIEVAL CONFIG =================
    MAX_CHUNKS = 6
    CSV_KEEP = 2
    DOC_KEEP = 2
    # ==========================================================

    # ---- CSV retrieval with scores ----
    csv_hits = []
    if csv_retriever:
        # Pass the contextualized standalone query
        csv_hits = rag.retrieve_csv_with_scores(payload.bot_id, standalone_query, k=5) or [] # [(Document, score)]

    # ---- Document retrieval (PDF / DOCX / TXT) using Two-Stage Hybrid Search ----
    hybrid_candidates = []
    if doc_retriever:
        hybrid_candidates = rag.hybrid_search(
            query=standalone_query, 
            vectorstore=doc_retriever.vectorstore, 
            k=15 # Fetch wide pool for reranking
        ) or []

    # Log retrieved documents for testing visibility
    print(f"[RAG Pipeline] Retrieved {len(csv_hits)} CSV chunks and {len(hybrid_candidates)} Doc hybrid candidates.")

    # ---- Optional Reranking & MMR for Document Chunks ----
    doc_docs = []
    if hybrid_candidates:
        # Step 1: True Cross-Encoder Reranking
        reranked_docs = rag.cross_encoder_rerank(standalone_query, hybrid_candidates, top_k=10)
        
        # Step 2: MMR Diverse Selection
        if rag.EMBEDDINGS:
            query_emb = rag.EMBEDDINGS.embed_query(standalone_query)
            doc_embs = [rag.EMBEDDINGS.embed_query(d.page_content) for d in reranked_docs]
            doc_docs = rag.mmr_selection(query_emb, doc_embs, reranked_docs, top_k=5, lambda_mult=0.7)
        else:
            doc_docs = reranked_docs[:5]

    # ---- Build final context ----
    final_docs = []

    # 1️⃣ Take top CSV chunks
    final_docs.extend([doc for doc, _ in csv_hits[:CSV_KEEP]])

    # 2️⃣ Take top document chunks
    final_docs.extend(doc_docs[:DOC_KEEP])

    # 3️⃣ Fill remaining slots (CSV first, then docs)
    remaining = MAX_CHUNKS - len(final_docs)

    if remaining > 0:
        extra_csv = [doc for doc, _ in csv_hits[CSV_KEEP:]]
        extra_docs = doc_docs[DOC_KEEP:]

        extras = extra_csv + extra_docs
        final_docs.extend(extras[:remaining])

    clean_docs = []

    for d in final_docs:
        if d.metadata.get("type") == "csv":
            # ✅ ONLY answer goes to LLM
            clean_docs.append(
                Document(
                    page_content=d.metadata["answer"],
                    metadata=d.metadata
                )
            )
        else:
            # PDFs / DOCX / TXT unchanged
            clean_docs.append(d)

    combined_docs = clean_docs

    try:
        # Use improved RAG response
        # IMPORTANT: Pass the ORIGINAL query to the text generation, not the standalone query,
        # so the assistant replies naturally to what the user explicitly said.
        result = rag.get_rag_response(
            payload.query,
            history,
            combined_docs,  # 👈 pass docs directly
            rag.LLM,
            payload.bot_id,
            use_query_expansion=False,  # Contextualized query generator is superior for history
            use_reranking=False  # Disabled until Step 2 (True Reranking)
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"RAG/LLM error: {e}")

    # 🔥 NEW: store messages ONLY for dashboard users
    bot_reply = result.get("content") or result.get("text") or ""

    if not is_widget_user:
        try:
            rag.store_message(payload.user_id, payload.bot_id, "user", payload.query)
            rag.store_message(payload.user_id, payload.bot_id, "bot", bot_reply)
        except Exception as e:
            print("DB store error:", e)

    return {
        "response": result.get("content") or result.get("text") or ""
    }


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, bot: str = None):
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "bot_id": bot,
        }
    )


@app.get("/bots/{bot_id}/status")
async def bot_status(bot_id: str):
    trained = rag.is_bot_trained(bot_id)
    return {"trained": trained}


@app.get("/bots/new", response_class=HTMLResponse)
async def create_bot_page(request: Request, bot_id: str = None):
    bot = None
    if bot_id:
        bot = rag.get_bot(bot_id)   # you already have DB access

    return templates.TemplateResponse(
        "create_bot.html",
        {
            "request": request,
            "bot": bot
        }
    )


@app.get("/bots/my")
async def get_my_bots(user_id: str | None = None):
    if not user_id or user_id == "null":
        raise HTTPException(status_code=401, detail="Unauthorized")

    conn = rag._get_db_conn()
    cur = conn.cursor()

    cur.execute(
        "SELECT id, name FROM bots WHERE user_id=%s ORDER BY created_at DESC",
        (user_id,)
    )

    rows = cur.fetchall()
    cur.close()
    conn.close()

    return [
        {"id": row[0], "name": row[1]}
        for row in rows
    ]


@app.post("/bots/{bot_id}/index")
async def index_bot_files(
    bot_id: str,
    csv_files: List[UploadFile] = File(None),
    doc_files: List[UploadFile] = File(None),
    url: str = Form(None),
    text: str = Form(None),
    name: str = Form(None),
    instructions: str = Form(None),
    files_to_remove: str = Form(None)
    ):
    """
    Index uploaded knowledge for a bot.
    Supports:
    - Multiple CSV (Q&A)
    - Multiple documents (PDF/DOCX/TXT)
    - Optional URL / inline text
    """

    try:
        # 1️⃣ Update metadata first (safe, no data loss)
        if name and name.strip():
            rag.update_bot_name(bot_id, name.strip())

        if instructions is not None:
            rag.update_bot_instructions(bot_id, instructions)

        has_csv = bool(csv_files)
        has_docs = bool(doc_files or url or text)

        # 2️⃣ Process file removals first (before early return check)
        files_to_remove_list = []
        has_removals = False
        if files_to_remove:
            try:
                files_to_remove_list = json.loads(files_to_remove)
                has_removals = len(files_to_remove_list) > 0
                for file_op in files_to_remove_list:
                    rag.remove_file_from_bot(bot_id, file_op["id"], file_op["file_type"])
            except json.JSONDecodeError:
                pass  # Ignore invalid JSON

        # 3️⃣ Metadata-only update → stop here (only if no new files AND no removals)
        if not has_csv and not has_docs and not has_removals:
            return {
                "ok": True,
                "message": "Bot updated successfully (no retraining required)."
            }

        # Determine which types have new uploads
        has_new_csv = bool(csv_files)
        has_new_docs = bool(doc_files or url or text)

        # Load existing content from DB to decide what to rebuild
        # NOTE: do this *after* any removals so we see the latest state.
        bot = rag.get_bot(bot_id)
        existing_csv_content = bot.get("csv_content", []) if bot else []
        existing_doc_content = bot.get("doc_content", []) if bot else []

        # Check whether any files remain after removals
        has_any_csv_files = bool(bot.get("csv_files") if bot else [])
        has_any_doc_files = bool(bot.get("doc_files") if bot else [])

        # If there are no new uploads and no existing files at all, abort retrain
        if not has_new_csv and not has_new_docs and not has_any_csv_files and not has_any_doc_files:
            return {
                "ok": False,
                "error_type": "no_files",
                "message": "This bot has no files. Please upload at least one CSV or document before training."
            }

        # 4️⃣ REAL retrain → clean old knowledge ONCE
        # We'll rebuild fresh FAISS indexes from the DB state below.
        rag.delete_faiss_index_for_bot(bot_id)
        rag.delete_csv_faiss_for_bot(bot_id)

        # 5️⃣ Process CSV files
        csv_errors = []
        doc_errors = []
        processed_csv_files = []
        processed_doc_files = []

        # Collect all CSV QA rows we want to end up with after this retrain.
        all_csv_rows = list(existing_csv_content) if existing_csv_content else []

        if csv_files:
            # New CSVs uploaded: append rows tagged by file_id and re-index everything.
            import base64  # ensure available if needed later
            for f in csv_files:
                try:
                    csv_bytes = await f.read()
                    csv_rows = rag.parse_and_validate_csv(csv_bytes)

                    # Store file metadata in database and get stable file_id
                    file_id = rag.add_file_to_bot(bot_id, f.filename, "csv", len(csv_bytes))
                    processed_csv_files.append(f.filename)

                    # Tag each row with the file_id so we can filter on removal
                    for row in csv_rows:
                        row["file_id"] = file_id

                    # Accumulate into the combined list
                    all_csv_rows.extend(csv_rows)
                except ValueError as e:
                    csv_errors.append({
                        "file": f.filename,
                        "error": str(e),
                        "type": "validation_error"
                    })
                except Exception as e:
                    csv_errors.append({
                        "file": f.filename,
                        "error": f"Failed to process CSV: {str(e)}",
                        "type": "processing_error"
                    })

            # After processing all new CSVs, write the combined rows and build FAISS once.
            if all_csv_rows:
                rag.index_csv_qa_faiss(bot_id, all_csv_rows, replace_content=True)
        elif existing_csv_content and not has_new_csv:
            # No new CSVs but we have stored CSVs: rebuild CSV FAISS from DB
            rag.index_csv_qa_faiss(bot_id, existing_csv_content, replace_content=True)

        if csv_errors:
            return {
                "ok": False,
                "error_type": "csv_errors",
                "message": f"CSV processing failed for {len(csv_errors)} file(s)",
                "csv_errors": csv_errors
            }

        # 6️⃣ Process document files
        from io import BytesIO
        import base64

        # We will build a final list of doc_content records that should remain after this retrain.
        final_doc_records = list(existing_doc_content) if existing_doc_content else []

        other_files = []  # for text extraction into FAISS

        if doc_files:
            # We are adding new docs. Ensure final_doc_records only contains records for files that still exist.
            if final_doc_records:
                # Filter existing records based on remaining doc_files (by file_id), but preserve legacy records without file_id.
                bot_doc_files = bot.get("doc_files", []) if bot else []
                remaining_ids = {f["id"] for f in bot_doc_files if isinstance(f, dict) and "id" in f}
                filtered_existing = []
                for rec in final_doc_records:
                    file_id = rec.get("file_id")
                    if file_id is None or file_id in remaining_ids:
                        filtered_existing.append(rec)
                final_doc_records = filtered_existing

                # Existing docs that survived removals must also be re-indexed,
                # so push their decoded content into other_files.
                for rec in final_doc_records:
                    if "content_base64" in rec:
                        try:
                            other_files.append(
                                (rec["filename"], BytesIO(base64.b64decode(rec["content_base64"])))
                            )
                        except Exception:
                            # If decoding fails for a legacy record, skip but continue with others.
                            continue

            # New docs uploaded: append and re-index
            for f in doc_files:
                try:
                    content = await f.read()
                    # Validate file size (max 50MB)
                    if len(content) > 50 * 1024 * 1024:
                        doc_errors.append({
                            "file": f.filename,
                            "error": "File too large (max 50MB)",
                            "type": "size_error"
                        })
                        continue

                    # Validate file extension
                    allowed_extensions = ['.pdf', '.docx', '.txt']
                    if not any(f.filename.lower().endswith(ext) for ext in allowed_extensions):
                        doc_errors.append({
                            "file": f.filename,
                            "error": f"Unsupported file type. Allowed: {', '.join(allowed_extensions)}",
                            "type": "format_error"
                        })
                        continue

                    # Store file metadata in database and get stable file_id
                    file_id = rag.add_file_to_bot(bot_id, f.filename, "doc", len(content))
                    processed_doc_files.append(f.filename)

                    # Record full content in DB payload with file_id
                    final_doc_records.append({
                        "file_id": file_id,
                        "filename": f.filename,
                        "content_base64": base64.b64encode(content).decode()
                    })

                    # Use BytesIO for extraction + FAISS indexing
                    other_files.append((f.filename, BytesIO(content)))
                except Exception as e:
                    doc_errors.append({
                        "file": f.filename,
                        "error": f"Failed to read file: {str(e)}",
                        "type": "read_error"
                    })
        elif existing_doc_content and not has_new_docs:
            # No new docs but we have stored docs: rebuild doc FAISS from DB
            # Filter out any records whose file_id no longer exists in doc_files
            bot_doc_files = bot.get("doc_files", []) if bot else []
            remaining_ids = {f["id"] for f in bot_doc_files if isinstance(f, dict) and "id" in f}

            filtered_existing = []
            for rec in existing_doc_content:
                file_id = rec.get("file_id")
                if file_id is None or file_id in remaining_ids:
                    filtered_existing.append(rec)

            other_files = [
                (rec["filename"], BytesIO(base64.b64decode(rec["content_base64"])))
                for rec in filtered_existing
            ]

        if doc_errors:
            return {
                "ok": False,
                "error_type": "doc_errors", 
                "message": f"Document processing failed for {len(doc_errors)} file(s)",
                "doc_errors": doc_errors
            }

        texts = []
        urls = []
        url_errors = []

        if text:
            if len(text.strip()) == 0:
                url_errors.append({
                    "source": "inline_text",
                    "error": "Text content cannot be empty",
                    "type": "validation_error"
                })
            else:
                texts.append({"text": text, "source": "inline_text"})

        if url:
            try:
                # Basic URL validation
                if not (url.startswith('http://') or url.startswith('https://')):
                    url_errors.append({
                        "source": url,
                        "error": "URL must start with http:// or https://",
                        "type": "validation_error"
                    })
                else:
                    urls.append(url)
            except Exception as e:
                url_errors.append({
                    "source": url,
                    "error": f"Invalid URL format: {str(e)}",
                    "type": "validation_error"
                })

        if url_errors:
            return {
                "ok": False,
                "error_type": "url_errors",
                "message": f"URL/text processing failed for {len(url_errors)} item(s)",
                "url_errors": url_errors
            }

        documents = rag.build_documents_from_uploads(
            uploaded_files=other_files,
            texts=texts,
            urls=urls
        )

        # 7️⃣ Persist doc_content and index documents if present
        if documents:
            try:
                # If we have new docs this run, final_doc_records contains the complete, filtered set.
                if final_doc_records:
                    conn = rag._get_db_conn()
                    cur = conn.cursor()
                    cur.execute(
                        "UPDATE bots SET doc_content = %s::jsonb WHERE id = %s",
                        (json.dumps(final_doc_records), bot_id)
                    )
                    conn.commit()
                    cur.close()
                    conn.close()

                res = rag.index_documents_for_bot(bot_id, documents)
                return {
                    "ok": True,
                    "summary": res,
                    "processed_csv_files": processed_csv_files,
                    "processed_doc_files": processed_doc_files
                }
            except Exception as e:
                return {
                    "ok": False,
                    "error_type": "indexing_error",
                    "message": f"Failed to index documents: {str(e)}",
                    "error": str(e)
                }

        # 8️⃣ Handle different success scenarios
        if has_new_csv and not has_new_docs:
            # Only CSVs uploaded
            return {
                "ok": True, 
                "summary": "CSV knowledge indexed successfully.",
                "processed_csv_files": processed_csv_files,
                "processed_doc_files": processed_doc_files
            }
        elif not has_new_csv and has_new_docs:
            # Only documents uploaded
            return {
                "ok": True, 
                "summary": "Document knowledge indexed successfully.",
                "processed_csv_files": processed_csv_files,
                "processed_doc_files": processed_doc_files
            }
        elif has_new_csv and has_new_docs:
            # Both CSVs and documents uploaded
            return {
                "ok": True, 
                "summary": "Both CSV and document knowledge indexed successfully.",
                "processed_csv_files": processed_csv_files,
                "processed_doc_files": processed_doc_files
            }
        else:
            # No new files but existing content was rebuilt
            return {
                "ok": True, 
                "summary": "Existing knowledge rebuilt successfully.",
                "processed_csv_files": processed_csv_files,
                "processed_doc_files": processed_doc_files
            }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Training failed: {str(e)}")


@app.post("/bots/{bot_id}/rename")
async def rename_bot(bot_id: str, payload: RenameBotRequest):
    rag.update_bot_name(bot_id, payload.name)
    return {"ok": True}


@app.post("/auth/signup")
async def signup(payload: SignupRequest):
    try:
        user_id = rag.create_user(payload.email, payload.password)
    except Exception as e:
        if "UniqueViolation" in type(e).__name__ or "unique" in str(e).lower():
            raise HTTPException(status_code=409, detail="This email is already registered. Please login instead.")
        raise HTTPException(status_code=500, detail=f"Signup failed: {str(e)}")
    return {"ok": True, "user_id": user_id}


@app.post("/auth/login")
async def login(payload: SignupRequest):
    user_id = rag.login_user(payload.email, payload.password)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"ok": True, "user_id": user_id}


@app.post("/bots/create")
async def create_bot(payload: CreateBotRequest):
    bot_id = rag.create_bot(payload.user_id, payload.name, instructions=payload.instructions)
    return {"ok": True, "bot_id": bot_id}


@app.get("/bots/{bot_id}/files")
async def get_bot_files(bot_id: str):
    """Get all files associated with a bot"""
    try:
        files = rag.get_bot_files(bot_id)
        return {"ok": True, "files": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get files: {str(e)}")


@app.delete("/bots/{bot_id}/files/{file_id}")
async def remove_bot_file(bot_id: str, file_id: str, file_type: str):
    """Remove a specific file from a bot"""
    try:
        rag.remove_file_from_bot(bot_id, file_id, file_type)
        return {"ok": True, "message": "File removed successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to remove file: {str(e)}")


@app.delete("/bots/{bot_id}")
async def delete_bot(bot_id: str):
    rag.delete_bot(bot_id)
    return {"ok": True}


if __name__ == "__main__":
    # for local development, run with: python -m app.main
    uvicorn.run()
