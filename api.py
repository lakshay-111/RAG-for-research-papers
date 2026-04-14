import os
import io
import json
import asyncio
import aiohttp
import PyPDF2
import arxiv
import docx
import chromadb
from chromadb.utils import embedding_functions
from dotenv import load_dotenv
import openai

from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List

# Load environment variables
load_dotenv()

openai_api_key = os.getenv("OPENROUTER_API_KEY")
if not openai_api_key:
    # Just to prevent instant crash if env is not ready yet, but it should be
    print("Warning: OPENROUTER_API_KEY is not set.")

openai.api_key = openai_api_key
openai.api_base = "https://openrouter.ai/api/v1"

client = chromadb.PersistentClient(path="./chroma_db")
arxiv_client = arxiv.Client()
default_ef = embedding_functions.DefaultEmbeddingFunction()

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("frontend", exist_ok=True)


async def extract_text_from_page(page):
    return page.extract_text()

async def extract_text_from_pdf(pdf_content):
    pdf_file = io.BytesIO(pdf_content)
    pdf_reader = PyPDF2.PdfReader(pdf_file)
    
    async def process_page(i):
        current_page = await extract_text_from_page(pdf_reader.pages[i])
        if i == 0:
            return current_page
        else:
            previous_page = await extract_text_from_page(pdf_reader.pages[i-1])
            overlap = len(previous_page) // 3
            return previous_page[-overlap:] + current_page

    tasks = [asyncio.create_task(process_page(i)) for i in range(len(pdf_reader.pages))]
    texts = await asyncio.gather(*tasks)
    return texts

async def extract_text_from_docx_bytes(docx_content):
    """Extract text from Word document bytes."""
    doc = docx.Document(io.BytesIO(docx_content))
    current_text = "\n".join([para.text for para in doc.paragraphs])
    
    texts = []
    chunk_size = 2000
    for i in range(0, len(current_text), chunk_size):
        texts.append(current_text[i:i+chunk_size])
    
    return texts if texts else [current_text]

async def fetch_pdf(session, url, semaphore):
    async with semaphore:
        async with session.get(url) as response:
            return await response.read()


@app.get("/api/collections")
async def get_collections():
    collections = client.list_collections()
    return {"collections": [c.name for c in collections]}


class ArxivSearchRequest(BaseModel):
    query: str
    search_mode: str = "relevance"
    n_results: int = 3

@app.post("/api/arxiv/search")
async def search_arxiv_route(req: ArxivSearchRequest):
    try:
        sanitized_input = "".join(c if c.isalnum() or c in "-_" else "_" for c in req.query.lower())
        collection_name = f"arxiv_search_{sanitized_input}"[:50]
        collection_name = collection_name.rstrip("_-") or "arxiv_search_default"
        
        collection = client.get_or_create_collection(name=collection_name, embedding_function=default_ef)

        search = arxiv.Search(
            query=req.query,
            max_results=req.n_results,
            sort_by=arxiv.SortCriterion.SubmittedDate if req.search_mode == 'latest' else arxiv.SortCriterion.Relevance
        )
        results = list(arxiv_client.results(search))

        if not results:
            return {"status": "error", "message": "No results found."}

        semaphore = asyncio.Semaphore(10)
        async with aiohttp.ClientSession() as session:
            tasks = [asyncio.create_task(fetch_pdf(session, result.pdf_url, semaphore)) for result in results]
            pdf_contents = await asyncio.gather(*tasks)

            async def process_paper(i, result, pdf_content):
                pages = await extract_text_from_pdf(pdf_content)
                paper_data = {
                    "title": result.title,
                    "authors": [author.name for author in result.authors],
                    "summary": result.summary,
                    "url": result.pdf_url
                }
                collection.add(
                    documents=pages,
                    metadatas=[{"title": result.title, "page": j} for j in range(len(pages))],
                    ids=[f"paper_{i+1}_page_{j}" for j in range(len(pages))]
                )
                
                json_file = "paper_metadata.json"
                if os.path.exists(json_file):
                    with open(json_file, "r+") as file:
                        try:
                            data = json.load(file)
                        except:
                            data = []
                        data.append(paper_data)
                        file.seek(0)
                        json.dump(data, file, indent=4)
                else:
                    with open(json_file, "w") as file:
                        json.dump([paper_data], file, indent=4)

            await asyncio.gather(*[process_paper(i, result, pdf_content) for i, (result, pdf_content) in enumerate(zip(results, pdf_contents))])

        return {"status": "success", "collection_name": collection_name, "message": f"Processed {len(results)} papers."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/local/upload")
async def upload_local_files(files: List[UploadFile] = File(...)):
    try:
        # Create a unique local collection
        collection_name = "local_documents"
        collection = client.get_or_create_collection(name=collection_name, embedding_function=default_ef)
        
        paper_id = collection.count() # start ids from current count
        processed_files = []

        for uploaded_file in files:
            content = await uploaded_file.read()
            file_name = uploaded_file.filename
            
            if file_name.lower().endswith('.pdf'):
                pages = await extract_text_from_pdf(content)
            elif file_name.lower().endswith('.docx'):
                pages = await extract_text_from_docx_bytes(content)
            else:
                continue

            paper_data = {"title": file_name, "authors": ["Local Upload"], "summary": f"Locally uploaded document", "url": "local"}
            
            collection.add(
                documents=pages,
                metadatas=[{"title": file_name, "page": j} for j in range(len(pages))],
                ids=[f"local_paper_{paper_id}_page_{j}" for j in range(len(pages))]
            )
            
            json_file = "paper_metadata.json"
            if os.path.exists(json_file):
                with open(json_file, "r+") as file:
                    try:
                        data = json.load(file)
                    except:
                        data = []
                    data.append(paper_data)
                    file.seek(0)
                    json.dump(data, file, indent=4)
            else:
                with open(json_file, "w") as file:
                    json.dump([paper_data], file, indent=4)
            
            processed_files.append(file_name)
            paper_id += 1

        return {"status": "success", "collection_name": collection_name, "files": processed_files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class ChatRequest(BaseModel):
    query: str
    collection_name: str
    n_chunks: int = 3

@app.post("/api/chat")
async def chat_route(req: ChatRequest):
    try:
        collection = client.get_collection(name=req.collection_name, embedding_function=default_ef)
        results = collection.query(
            query_texts=[req.query],
            n_results=req.n_chunks
        )
        
        chunks = []
        for i, (doc, metadata) in enumerate(zip(results['documents'][0], results['metadatas'][0])):
            chunks.append(f"Chunk {i+1} from {metadata.get('title', 'Unknown')}, Page {metadata.get('page', 0)}: {doc}")
            
        prompt = f"Based on the following chunks of information from documents, please answer this question: {req.query}\n\n"
        prompt += "\n\n".join(chunks)

        def generate():
            response = openai.ChatCompletion.create(
                model="google/gemma-2-9b-it", # Matching the CLI script
                stream=True,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that answers questions based on scientific paper excerpts Format nicely using markdown."},
                    {"role": "user", "content": prompt}
                ]
            )
            for chunk in response:
                if 'choices' in chunk and len(chunk['choices']) > 0:
                    delta = chunk['choices'][0].get('delta', {})
                    content = delta.get('content', '')
                    if content:
                        yield content

        return StreamingResponse(generate(), media_type="text/event-stream")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Mount frontend at the very end
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
