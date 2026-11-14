"""Local Research Document Vault for LEXNIS Marketing Agency.

Extracts text from PDF, DOCX, PPTX, XLSX, CSV, JSON, MD, TXT, HTML locally without cloud APIs.
Chunks text deterministically and provides stable chunk identifiers for evidence citation.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .database import repository, NotFound


@dataclass
class DocumentChunk:
    chunk_id: str
    document_id: str
    index: int
    text: str
    page_number: Optional[int] = None
    character_range: Tuple[int, int] = (0, 0)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["character_range"] = list(self.character_range)
        return d


@dataclass
class DocumentMetadata:
    document_id: str
    client_id: str
    filename: str
    content_hash: str
    mime_type: str
    page_count: int
    char_count: int
    chunk_count: int
    ingested_at: str
    source_type: str = "upload"
    language: str = "en"
    extraction_status: str = "SUCCESS"
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class DocumentVault:
    """Manages document storage, local text extraction, and stable chunking."""

    def __init__(self, storage_dir: Optional[Path] = None):
        self.storage_dir = storage_dir or (Path(__file__).resolve().parents[1] / "output/agency/documents")
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def ingest_bytes(
        self,
        client_id: str,
        filename: str,
        data: bytes,
        mime_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """Ingest raw document bytes, compute SHA-256 hash, extract text, and chunk."""
        content_hash = hashlib.sha256(data).hexdigest()
        doc_id = f"doc_{content_hash[:16]}"

        # Infer mime type if missing
        ext = Path(filename).suffix.lower()
        if not mime_type:
            mime_type = self._infer_mime(ext)

        # Save document original safely
        client_dir = self.storage_dir / client_id
        client_dir.mkdir(parents=True, exist_ok=True)
        dest_path = client_dir / f"{doc_id}{ext}"
        dest_path.write_bytes(data)

        # Extract text based on file format
        extracted_text, page_count, err = self._extract_text(dest_path, ext, data)

        # Chunk text
        chunks = self._chunk_text(doc_id, extracted_text)

        meta = DocumentMetadata(
            document_id=doc_id,
            client_id=client_id,
            filename=filename,
            content_hash=content_hash,
            mime_type=mime_type,
            page_count=page_count,
            char_count=len(extracted_text),
            chunk_count=len(chunks),
            ingested_at=datetime.now(timezone.utc).isoformat(),
            extraction_status="SUCCESS" if not err else "PARTIAL",
            error=err,
        )

        # Save parsed chunks and metadata JSON
        doc_record = {
            "metadata": meta.to_dict(),
            "extracted_text": extracted_text,
            "chunks": [c.to_dict() for c in chunks],
        }
        json_path = client_dir / f"{doc_id}.json"
        json_path.write_text(json.dumps(doc_record, ensure_ascii=False, indent=2), encoding="utf-8")

        return doc_record

    def get_document(self, client_id: str, doc_id: str) -> Optional[Dict[str, Any]]:
        json_path = self.storage_dir / client_id / f"{doc_id}.json"
        if not json_path.exists():
            return None
        return json.loads(json_path.read_text(encoding="utf-8"))

    def list_documents(self, client_id: str) -> List[Dict[str, Any]]:
        client_dir = self.storage_dir / client_id
        if not client_dir.exists():
            return []
        docs = []
        for p in client_dir.glob("doc_*.json"):
            try:
                rec = json.loads(p.read_text(encoding="utf-8"))
                docs.append(rec["metadata"])
            except Exception:
                continue
        return sorted(docs, key=lambda x: x.get("ingested_at", ""), reverse=True)

    def search_chunks(self, client_id: str, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Keyword/substring search over document chunks."""
        q = query.lower()
        results = []
        for doc in self.list_documents(client_id):
            full_doc = self.get_document(client_id, doc["document_id"])
            if not full_doc:
                continue
            for ch in full_doc.get("chunks", []):
                if q in ch["text"].lower():
                    results.append({
                        "document_id": doc["document_id"],
                        "filename": doc["filename"],
                        "chunk_id": ch["chunk_id"],
                        "page_number": ch.get("page_number"),
                        "text": ch["text"],
                    })
                    if len(results) >= limit:
                        return results
        return results

    def _infer_mime(self, ext: str) -> str:
        mime_map = {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".csv": "text/csv",
            ".json": "application/json",
            ".txt": "text/plain",
            ".md": "text/markdown",
            ".html": "text/html",
        }
        return mime_map.get(ext, "application/octet-stream")

    def _extract_text(self, file_path: Path, ext: str, data: bytes) -> Tuple[str, int, Optional[str]]:
        text = ""
        pages = 1
        err = None

        try:
            if ext in {".txt", ".md"}:
                text = data.decode("utf-8", errors="replace")
            elif ext == ".csv":
                lines = data.decode("utf-8", errors="replace").splitlines()
                reader = csv.reader(lines)
                text = "\n".join([" | ".join(row) for row in reader if row])
            elif ext == ".json":
                parsed = json.loads(data.decode("utf-8", errors="replace"))
                text = json.dumps(parsed, ensure_ascii=False, indent=2)
            elif ext == ".pdf":
                try:
                    from pypdf import PdfReader
                    reader = PdfReader(str(file_path))
                    pages = len(reader.pages)
                    extracted = [p.extract_text() or "" for p in reader.pages]
                    text = "\n\n--- Page Break ---\n\n".join(extracted)
                except Exception as e:
                    # Fallback raw ASCII string extraction if pypdf is not installed
                    ascii_strings = re.findall(r"[a-zA-Z0-9\s.,!?:;'\"]{4,}", data.decode("latin1", errors="ignore"))
                    text = " ".join(ascii_strings)
                    err = f"PDF parser fallback: {str(e)}"
            elif ext == ".docx":
                try:
                    import docx
                    doc = docx.Document(str(file_path))
                    text = "\n".join([p.text for p in doc.paragraphs if p.text])
                except Exception as e:
                    # Fallback zip extract word/document.xml
                    import zipfile
                    with zipfile.ZipFile(str(file_path)) as z:
                        xml_content = z.read("word/document.xml").decode("utf-8", errors="ignore")
                        text = re.sub(r"<[^>]+>", " ", xml_content)
                    err = f"DOCX zip fallback: {str(e)}"
            elif ext == ".pptx":
                try:
                    import pptx
                    prs = pptx.Presentation(str(file_path))
                    pages = len(prs.slides)
                    slide_texts = []
                    for s in prs.slides:
                        st = [shape.text for shape in s.shapes if hasattr(shape, "text") and shape.text]
                        slide_texts.append("\n".join(st))
                    text = "\n\n--- Slide Break ---\n\n".join(slide_texts)
                except Exception as e:
                    err = f"PPTX fallback: {str(e)}"
            elif ext == ".xlsx":
                try:
                    import openpyxl
                    wb = openpyxl.load_workbook(str(file_path), data_only=True)
                    pages = len(wb.sheetnames)
                    sheet_texts = []
                    for name in wb.sheetnames:
                        ws = wb[name]
                        rows = []
                        for row in ws.iter_rows(values_only=True):
                            r_str = " | ".join([str(c) for c in row if c is not None])
                            if r_str:
                                rows.append(r_str)
                        sheet_texts.append(f"Sheet: {name}\n" + "\n".join(rows))
                    text = "\n\n".join(sheet_texts)
                except Exception as e:
                    err = f"XLSX fallback: {str(e)}"
            elif ext == ".html":
                raw = data.decode("utf-8", errors="replace")
                text = re.sub(r"<[^>]+>", " ", raw)
            else:
                text = data.decode("utf-8", errors="replace")
        except Exception as ex:
            err = str(ex)
            text = data.decode("utf-8", errors="replace")

        return text.strip(), pages, err

    def _chunk_text(self, doc_id: str, text: str, chunk_size: int = 1000, overlap: int = 150) -> List[DocumentChunk]:
        """Split text into deterministic chunks with stable identifiers."""
        if not text:
            return []

        chunks: List[DocumentChunk] = []
        prefix = doc_id[:12]
        idx = 0
        start = 0
        text_len = len(text)

        while start < text_len:
            end = min(start + chunk_size, text_len)
            # Try to break at a paragraph or sentence boundary if not at end
            if end < text_len:
                p_break = text.rfind("\n\n", start, end)
                if p_break > start + (chunk_size // 2):
                    end = p_break + 2
                else:
                    s_break = text.rfind(". ", start, end)
                    if s_break > start + (chunk_size // 2):
                        end = s_break + 2

            chunk_str = text[start:end].strip()
            if chunk_str:
                chunk_id = f"{prefix}_c{idx:03d}"
                chunks.append(DocumentChunk(
                    chunk_id=chunk_id,
                    document_id=doc_id,
                    index=idx,
                    text=chunk_str,
                    character_range=(start, end),
                ))
                idx += 1

            start = max(start + 1, end - overlap)

        return chunks


document_vault = DocumentVault()

