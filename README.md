# RAG for research papers

A Retrieval-Augmented Generation system for searching and asking questions about ArXiv papers and local documents.

## Features
- Download papers from ArXiv
- Upload local PDF and Word documents
- Semantic search with ChromaDB
- AI-powered Q&A using Google Gemma 2 via OpenRouter

## Setup
1. Clone: `git clone https://github.com/USERNAME/arxiv-rag-researcher.git`
2. Create venv: `python -m venv venv`
3. Activate: `venv\Scripts\activate`
4. Install: `pip install -r requirements.txt`
5. Add `.env` with `OPENROUTER_API_KEY="your-key"`
6. Run: `python arxiv-rag-researcher.py`

## Usage
- Option 1: Download papers from ArXiv
- Option 2: Upload local PDFs/Word docs
- Ask questions about the documents
